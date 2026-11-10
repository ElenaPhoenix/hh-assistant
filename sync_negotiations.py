import os
import json
from logger import log
from state_helper import load_state, save_state, add_applied_id
from shared_api import fetch_all_negotiations
from utils import load_config, resume_id_from_url, load_resume, VACANCIES_FILE
from db import db_cursor, init_db
from ui_helper import (
    print_success,
    print_info,
    print_warning,
    print_error,
    check_stop_key,
)


def _print_progress(loaded_count, page_num):
    print(
        f"\r  Скачано: {loaded_count} откликов (страниц: {page_num})...",
        end="",
        flush=True,
    )


def _print_fetch_error(status):
    """Печатает понятное сообщение для не-ok статуса от fetch_all_negotiations."""
    if status == "captcha":
        print_error("hh.ru требует проверки на робота. Попробуйте позже.")
        log.error("sync_negotiations: captcha")
    elif status == "auth_required":
        print_error("Сессия hh истекла. Авторизуйтесь: hh-applicant-tool authorize.")
        log.error("sync_negotiations: auth_required")
    elif status == "timeout":
        print_error("hh.ru не ответил вовремя. Проверьте интернет и попробуйте позже.")
        log.error("sync_negotiations: timeout")
    else:
        print_error(
            "Не удалось получить отклики с hh.ru. "
            "Возможно, hh временно ограничил запросы. "
            "Подробности в data/app.log. Попробуйте через 5-10 минут."
        )
        log.error(f"sync_negotiations: fetch failed, status={status}")


def _try_db_sync(all_items, config):
    """Возвращает: "ok", "stopped" или "error"."""
    try:
        init_db()
    except Exception as e:
        log.error(f"DB init failed: {e}")
        return "error"

    try:
        with db_cursor() as cur:
            if os.path.exists(VACANCIES_FILE):
                with open(VACANCIES_FILE, "r", encoding="utf-8") as f:
                    vacancies = json.load(f)
                for v in vacancies:
                    if check_stop_key():
                        print_warning(
                            "\nОстановка по '0'. Обновление базы данных прервано."
                        )
                        log.info("sync_negotiations: остановка БД по '0'")
                        return "stopped"
                    wf_str = ", ".join(v.get("work_formats") or [])
                    cur.execute(
                        """INSERT INTO vacancies (id, name, employer, link, full_description, area_id, work_formats)
                           VALUES (%s, %s, %s, %s, %s, %s, %s) 
                           ON CONFLICT (id) DO UPDATE SET 
                           name = EXCLUDED.name, employer = EXCLUDED.employer,
                           full_description = EXCLUDED.full_description,
                           area_id = EXCLUDED.area_id, work_formats = EXCLUDED.work_formats;""",
                        (
                            v.get("id"),
                            v.get("name"),
                            v.get("employer"),
                            v.get("link"),
                            v.get("full_description"),
                            v.get("area_id"),
                            wf_str,
                        ),
                    )
            for resume_cfg in config["resumes"]:
                rid = resume_id_from_url(resume_cfg["url"])
                resume_data = load_resume(rid) or {}
                cur.execute(
                    "INSERT INTO resumes (id, title) VALUES (%s, %s) "
                    "ON CONFLICT (id) DO UPDATE SET title = EXCLUDED.title;",
                    (rid, resume_data.get("title", "Резюме")),
                )
                our_items = [
                    item
                    for item in all_items
                    if ((item.get("resume") or {}).get("id") == rid)
                ]
                for item in our_items:
                    if check_stop_key():
                        print_warning(
                            "\nОстановка по '0'. Обновление базы данных прервано."
                        )
                        log.info("sync_negotiations: остановка БД по '0'")
                        return "stopped"
                    neg_id = item.get("id")
                    vacancy_data = item.get("vacancy") or {}
                    vac_id_str = vacancy_data.get("id")
                    if not neg_id or not vac_id_str:
                        continue
                    vac_id = int(vac_id_str)
                    status = (item.get("state") or {}).get("id", "")
                    cur.execute(
                        "INSERT INTO vacancies (id, name, employer) VALUES (%s, %s, %s) "
                        "ON CONFLICT (id) DO NOTHING;",
                        (
                            vac_id,
                            vacancy_data.get("name", ""),
                            (vacancy_data.get("employer") or {}).get("name", ""),
                        ),
                    )
                    cur.execute(
                        """INSERT INTO negotiations (id, vacancy_id, resume_id, status, hh_updated_at)
                           VALUES (%s, %s, %s, %s, %s) 
                           ON CONFLICT (id) DO UPDATE SET
                           status = EXCLUDED.status, updated_at = CURRENT_TIMESTAMP;""",
                        (neg_id, vac_id, rid, status, ""),
                    )
        log.info("БД успешно обновлена.")
        return "ok"
    except Exception as e:
        log.error(f"DB sync error: {e}")
        return "error"


def main():
    config = load_config()
    if not config.get("resumes"):
        print("В настройках нет резюме.")
        return
    print("Синхронизация с hh.ru...")
    print_info("Скачиваем историю откликов...")
    print_warning("Остановить: нажми '0' (без Enter).")
    print()
    all_items, fetch_status = fetch_all_negotiations(
        per_page=100, pause=0.3, callback=_print_progress
    )
    print()

    if fetch_status == "stopped":
        if not all_items:
            print_warning("Синхронизация остановлена пользователем.")
            return
        print_warning("Синхронизация остановлена. Обрабатываю полученное...")
    elif fetch_status != "ok":
        _print_fetch_error(fetch_status)
        return

    if not all_items:
        print_warning("У вас нет откликов на hh.ru.")
        return

    print_success(f"Загружено записей: {len(all_items)}")
    log.info(f"Загружено откликов: {len(all_items)}")
    state = load_state()
    total_added = 0
    for resume_cfg in config["resumes"]:
        if check_stop_key():
            print()
            print_warning("Остановка по '0'. Обновление прогресса прервано.")
            log.info("sync_negotiations: остановка обновления прогресса по '0'")
            save_state(state)
            return
        rid = resume_id_from_url(resume_cfg["url"])
        our_ids = set()
        for item in all_items:
            r = item.get("resume") or {}
            if not isinstance(r, dict) or r.get("id") != rid:
                continue
            vid = (item.get("vacancy") or {}).get("id")
            if vid:
                our_ids.add(int(vid))
        before = len(state["resumes"].get(rid, {}).get("applied_vacancy_ids", []))
        for vid in our_ids:
            add_applied_id(state, rid, vid)
        after = len(state["resumes"][rid]["applied_vacancy_ids"])
        total_added += after - before
        log.info(
            f"Резюме {rid[:8]}: state applied {before} -> {after} (+{after - before})"
        )
    save_state(state)
    print_success(f"Новых откликов добавлено: {total_added}")
    print_info("Обновляем базу данных...")
    result = _try_db_sync(all_items, config)
    if result == "ok":
        print_success("Синхронизация завершена.")
        log.info("Синхронизация завершена.")
    elif result == "stopped":
        print_warning("Синхронизация остановлена пользователем. Прогресс сохранен.")
    else:
        print_warning("Не удалось обновить базу данных. Подробности в data/app.log.")


if __name__ == "__main__":
    main()
