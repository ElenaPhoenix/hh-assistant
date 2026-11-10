import time
import random
from concurrent.futures import ThreadPoolExecutor, as_completed
from logger import log
from shared_api import call_api, fetch_all_negotiations
from db import get_connection, tables_ready
from ui_helper import (
    print_success,
    print_error,
    print_info,
    print_warning,
    check_stop_key,
)

# Статусы, в которых в чате могут быть новые сообщения от работодателя.
# "discard" включен: там иногда приходит "мягкий отказ" сообщением.
ACTIVE_STATES = {"active", "invited", "response", "discard"}


def _normalize_dt(dt_str):
    if not dt_str:
        return None
    try:
        if len(dt_str) > 5 and dt_str[-5] in "+-" and dt_str[-3] != ":":
            return dt_str[:-2] + ":" + dt_str[-2:]
        return dt_str
    except Exception:
        return dt_str


def _select_chats_to_check(all_items, db_updates):
    """Возвращает список (neg_id, hh_updated) для проверки.

    Дельта-синхронизация: берем чаты в статусах ACTIVE_STATES, у которых
    updated_at из hh отличается от hh_updated_at в БД. Чаты с одинаковым
    updated_at пропускаем - в них нет новых сообщений.
    """
    to_check = []
    for item in all_items:
        neg_id_str = item.get("id")
        if not neg_id_str:
            continue
        try:
            neg_id = int(neg_id_str)
        except (TypeError, ValueError):
            continue

        if neg_id not in db_updates:
            continue

        status_id = (item.get("state") or {}).get("id", "")
        if status_id not in ACTIVE_STATES:
            continue

        hh_updated = str(item.get("updated_at")) if item.get("updated_at") else ""
        db_updated = db_updates.get(neg_id, "")

        if hh_updated != db_updated:
            to_check.append((neg_id, hh_updated))

    return to_check


def fetch_and_save_messages(neg_id, hh_updated):
    time.sleep(random.uniform(0.2, 0.5))
    status, msg_data = call_api(f"/negotiations/{neg_id}/messages")

    if status == "error" and "404" in str(msg_data).lower():
        log.warning(f"чат {neg_id} удален (404), пропуск")
        try:
            conn = get_connection()
            cur = conn.cursor()
            cur.execute(
                "UPDATE negotiations SET hh_updated_at = %s WHERE id = %s",
                (hh_updated, neg_id),
            )
            conn.commit()
            cur.close()
            conn.close()
        except Exception:
            pass
        return 0

    if status != "ok" or not isinstance(msg_data, dict):
        log.warning(f"fetch_and_save_messages({neg_id}): API status={status}")
        return 0

    items = msg_data.get("items", [])

    try:
        conn = get_connection()
    except Exception as e:
        log.error(f"fetch_and_save_messages({neg_id}): DB connect error: {e}")
        return 0

    cur = None
    new_count = 0
    try:
        cur = conn.cursor()
        for m in items:
            msg_id = m.get("id")
            p_type = (m.get("author") or {}).get("participant_type", "")
            text = m.get("text") or ""
            created_at = _normalize_dt(m.get("created_at"))

            if not msg_id:
                continue
            cur.execute(
                """INSERT INTO messages (id, negotiation_id, author_id, text, created_at)
                   VALUES (%s, %s, %s, %s, %s) ON CONFLICT (id) DO NOTHING;""",
                (msg_id, neg_id, p_type, text, created_at),
            )
            if cur.rowcount > 0:
                new_count += 1

        cur.execute(
            "UPDATE negotiations SET hh_updated_at = %s WHERE id = %s",
            (hh_updated, neg_id),
        )
        conn.commit()
    except Exception as e:
        log.error(f"fetch_and_save_messages({neg_id}): DB error: {e}")
        try:
            conn.rollback()
        except Exception:
            pass
        return 0
    finally:
        if cur is not None:
            try:
                cur.close()
            except Exception:
                pass
        try:
            conn.close()
        except Exception:
            pass

    return new_count


def _print_fetch_error(status):
    if status == "captcha":
        print_error("hh.ru требует проверки на робота. Попробуйте позже.")
        log.error("check_messages: captcha")
    elif status == "auth_required":
        print_error("Сессия hh истекла. Авторизуйтесь: hh-applicant-tool authorize.")
        log.error("check_messages: auth_required")
    elif status == "timeout":
        print_error("hh.ru не ответил вовремя. Проверьте интернет.")
        log.error("check_messages: timeout")
    else:
        print_error(
            "Не удалось получить отклики с hh.ru. "
            "Подробности в data/app.log. Попробуйте через несколько минут."
        )
        log.error(f"check_messages: fetch failed, status={status}")


def main():
    log.info("check_messages: старт")
    if not tables_ready():
        print_error(
            "Таблицы в базе данных не созданы. "
            "Запустите синхронизацию откликов (пункт 6)."
        )
        return

    print_info("Скачиваем список откликов с hh.ru (это может занять пару минут)...")
    all_items, fetch_status = fetch_all_negotiations(per_page=100, pause=0.1)

    if fetch_status == "stopped":
        if not all_items:
            print_warning("Остановлено пользователем.")
            log.info("check_messages: остановка по '0'")
            return
        print_warning("Остановлено. Обрабатываю полученное...")
    elif fetch_status != "ok":
        _print_fetch_error(fetch_status)
        return

    if not all_items:
        print_warning("У вас нет откликов на hh.ru.")
        log.info("check_messages: у пользователя нет откликов")
        return

    print_success(f"Загружено откликов с hh: {len(all_items)}")
    log.info(f"check_messages: получено с hh {len(all_items)} откликов")

    try:
        conn = get_connection()
        cur = conn.cursor()
    except Exception as e:
        print_error(
            "Не удалось подключиться к базе данных. "
            "Проверьте, что PostgreSQL запущен."
        )
        log.error(f"check_messages: DB connect error: {e}")
        return

    cur.execute("SELECT id, hh_updated_at FROM negotiations")
    db_updates = {row[0]: str(row[1]) if row[1] else "" for row in cur.fetchall()}
    cur.close()
    conn.close()

    log.info(f"check_messages: negotiations в БД: {len(db_updates)}")

    if not db_updates:
        print_error("База данных пуста. Сначала запустите синхронизацию откликов.")
        return

    to_check = _select_chats_to_check(all_items, db_updates)
    log.info(f"check_messages: к проверке {len(to_check)} чатов")

    if not to_check:
        print_success("Нет новых сообщений (все чаты в актуальном состоянии).")
        return

    print_info(
        f"Найдено {len(to_check)} обновленных чатов. "
        f"Скачиваю содержимое (по 5 чатов одновременно)..."
    )
    print_warning("Остановить: нажми '0' (без Enter).")
    print()

    total_new = 0
    errors = 0
    completed = 0
    step = max(1, len(to_check) // 10)
    stopped = False

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {}
        for nid, hh_upd in to_check:
            if check_stop_key():
                print()
                print_warning("Получена команда остановки ('0').")
                log.info("check_messages: остановка по '0'")
                stopped = True
                break
            futures[executor.submit(fetch_and_save_messages, nid, hh_upd)] = nid

        for future in as_completed(futures):
            completed += 1
            try:
                new_count = future.result()
                if new_count > 0:
                    total_new += new_count
            except Exception as exc:
                log.error(f"Ошибка потока: {exc}")
                errors += 1

            if completed % step == 0 or completed == len(futures):
                print(f"  Проверено {completed} из {len(futures)}...")

    print_success(f"Найдено новых сообщений: {total_new}")
    if errors:
        print_warning(f"Чатов с ошибкой (попробуем при следующем запуске): {errors}")
    if stopped:
        print_warning(
            f"Остановлено: обработано {completed} из {len(to_check)}. "
            f"При следующем запуске остальные будут проверены."
        )
    log.info(
        f"check_messages: завершено, новых={total_new}, ошибок={errors}, "
        f"stopped={stopped}"
    )


if __name__ == "__main__":
    main()
