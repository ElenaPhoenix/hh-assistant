import time
import random
from concurrent.futures import ThreadPoolExecutor, as_completed
from logger import log
from shared_api import call_api, fetch_all_negotiations
from db import get_connection, tables_ready
from ui_helper import print_success, print_error, print_info, print_warning


def _normalize_dt(dt_str):
    """Приводит '2026-11-03T21:15:00+0300' к ISO '2026-11-03T21:15:00+03:00'."""
    if not dt_str:
        return None
    try:
        if len(dt_str) > 5 and dt_str[-5] in "+-" and dt_str[-3] != ":":
            return dt_str[:-2] + ":" + dt_str[-2:]
        return dt_str
    except Exception:
        return dt_str


def fetch_and_save_messages(neg_id, hh_updated):
    time.sleep(random.uniform(0.2, 0.5))
    status, msg_data = call_api(f"/negotiations/{neg_id}/messages")

    # Если чат удален на hh (404), чтобы не зациклиться, просто обновляем дату
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

        # Обновляем дату ТОЛЬКО если успешно скачали и сохранили сообщения
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


def main():
    log.info("check_messages: старт")
    if not tables_ready():
        print_error("Таблицы в БД не созданы. Запустите пункт 6.")
        return

    print_info("Скачиваем список откликов с hh.ru (это может занять пару минут)...")
    all_items = fetch_all_negotiations(per_page=100, pause=0.1)

    if not all_items:
        print_error("Не удалось загрузить список откликов с hh.ru (0 элементов).")
        log.error("check_messages: fetch_all_negotiations вернул пустой список")
        return

    print_success(f"Загружено откликов с hh: {len(all_items)}")
    log.info(f"check_messages: получено с hh {len(all_items)} откликов")

    try:
        conn = get_connection()
        cur = conn.cursor()
    except Exception as e:
        print_error(f"Нет подключения к БД: {e}")
        return

    # Ключи в этом словаре - числа (int), так как колонка id в БД имеет тип BIGINT
    cur.execute("SELECT id, hh_updated_at FROM negotiations")
    db_updates = {row[0]: str(row[1]) if row[1] else "" for row in cur.fetchall()}
    log.info(f"check_messages: negotiations в БД: {len(db_updates)}")

    if not db_updates:
        print_error("База данных пуста. Сначала запустите пункт 6 (синхронизация).")
        cur.close()
        conn.close()
        return

    to_check = []
    for item in all_items:
        # КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: API возвращает id как строку, а в БД это BIGINT (int)
        neg_id_str = item.get("id")
        if not neg_id_str:
            continue
        neg_id = int(neg_id_str)

        if neg_id not in db_updates:
            continue

        status_id = (item.get("state") or {}).get("id", "")
        if status_id not in ("active", "invited", "response", "discard"):
            continue

        hh_updated = str(item.get("updated_at")) if item.get("updated_at") else ""
        db_updated = db_updates.get(neg_id, "")

        if hh_updated != db_updated:
            to_check.append((neg_id, hh_updated))

    cur.close()
    conn.close()

    log.info(f"check_messages: к проверке {len(to_check)} чатов")

    if not to_check:
        print_success("Нет новых сообщений (все чаты в актуальном состоянии).")
        return

    print_info(f"Найдено {len(to_check)} обновленных чатов, скачиваем (5 потоков)...")

    total_new = 0
    errors = 0
    completed = 0
    step = max(1, len(to_check) // 10)

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {
            executor.submit(fetch_and_save_messages, nid, hh_upd): nid
            for nid, hh_upd in to_check
        }
        for future in as_completed(futures):
            completed += 1
            try:
                new_count = future.result()
                if new_count > 0:
                    total_new += new_count
            except Exception as exc:
                log.error(f"Ошибка потока: {exc}")
                errors += 1

            if completed % step == 0 or completed == len(to_check):
                print(f"  Проверено {completed} из {len(to_check)}...")

    print_success(f"Найдено новых сообщений: {total_new}")
    if errors:
        print_warning(f"Чатов с ошибкой (попробуем при следующем запуске): {errors}")
    log.info(f"check_messages: завершено, новых={total_new}, ошибок={errors}")


if __name__ == "__main__":
    main()
