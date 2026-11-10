"""
Утилита для переноса сохраненных данных (JSON) в базу данных (PostgreSQL).
Используется, если нужно полностью перезалить данные в БД.
"""

import json
import os
from db import db_cursor, init_db
from shared_api import fetch_all_negotiations
from utils import load_config, resume_id_from_url, load_resume, VACANCIES_FILE
from ui_helper import (
    print_success,
    print_warning,
    print_info,
    print_error,
    check_stop_key,
)


def migrate_vacancies_and_resumes():
    print_info("Подключаемся к базе данных...")
    try:
        init_db()
    except Exception:
        print_error(
            "Не удалось подключиться к базе данных. "
            "Проверьте, что PostgreSQL запущен, и настройки в .env верны."
        )
        return False

    total_vac = 0
    done_vac = 0
    total_res = 0
    done_res = 0

    try:
        with db_cursor() as cur:
            if os.path.exists(VACANCIES_FILE):
                with open(VACANCIES_FILE, "r", encoding="utf-8") as f:
                    vacancies = json.load(f)

                total_vac = len(vacancies)
                print_info(f"Записываем {total_vac} вакансий...")
                print_warning("Остановить: нажми '0' (без Enter).")
                for v in vacancies:
                    if check_stop_key():
                        print()
                        print_warning(
                            f"Остановка по '0'. Записано {done_vac} из {total_vac} "
                            f"вакансий. При следующем запуске перенос продолжится."
                        )
                        return False
                    cur.execute(
                        """INSERT INTO vacancies (id, name, employer, salary_from, salary_to, salary_currency, link, full_description)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s) 
                           ON CONFLICT (id) DO UPDATE SET 
                           name = EXCLUDED.name, 
                           employer = EXCLUDED.employer,
                           full_description = EXCLUDED.full_description;""",
                        (
                            v.get("id"),
                            v.get("name"),
                            v.get("employer"),
                            v.get("salary_from"),
                            v.get("salary_to"),
                            v.get("salary_currency"),
                            v.get("link"),
                            v.get("full_description"),
                        ),
                    )
                    done_vac += 1

            config = load_config()
            if config.get("resumes"):
                total_res = len(config["resumes"])
                print_info(f"Записываем {total_res} резюме...")
                for r_cfg in config["resumes"]:
                    if check_stop_key():
                        print()
                        print_warning(
                            f"Остановка по '0'. Записано {done_res} из {total_res} "
                            f"резюме. При следующем запуске перенос продолжится."
                        )
                        return False
                    rid = resume_id_from_url(r_cfg["url"])
                    resume_data = load_resume(rid) or {}
                    title = resume_data.get("title", "Резюме")
                    cur.execute(
                        "INSERT INTO resumes (id, title) VALUES (%s, %s) "
                        "ON CONFLICT (id) DO UPDATE SET title = EXCLUDED.title;",
                        (rid, title),
                    )
                    done_res += 1
    except Exception:
        print_error("Ошибка при записи в базу данных. " "Подробности в data/app.log.")
        return False

    print_success("Вакансии и резюме успешно записаны в базу данных.")
    return True


def migrate_negotiations():
    print_info("\nЗапрашиваем отклики с hh.ru (это займет время)...")
    try:
        all_items, fetch_status = fetch_all_negotiations(per_page=100, pause=0.1)
    except Exception:
        print_error("Не удалось скачать отклики с hh.ru. Проверьте интернет.")
        return False

    if fetch_status != "ok":
        print_error(
            f"Не удалось получить отклики с hh.ru (статус: {fetch_status}). "
            f"Подробности в data/app.log."
        )
        return False

    if not all_items:
        print_warning("У вас нет откликов на hh.ru.")
        return False

    print_info(f"Загружено {len(all_items)} записей с hh.")

    config = load_config()
    done = 0

    try:
        with db_cursor() as cur:
            print_info("Распределяем отклики по резюме и записываем...")
            print_warning("Остановить: нажми '0' (без Enter).")
            for r_cfg in config["resumes"]:
                rid = resume_id_from_url(r_cfg["url"])
                our_items = [
                    item
                    for item in all_items
                    if ((item.get("resume") or {}).get("id") == rid)
                ]

                for item in our_items:
                    if check_stop_key():
                        print()
                        print_warning(
                            f"Остановка по '0'. Записано {done} откликов. "
                            f"При следующем запуске перенос продолжится."
                        )
                        return False
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
                    done += 1
    except Exception:
        print_error(
            "Ошибка при записи откликов в базу данных. Подробности в data/app.log."
        )
        return False

    print_success(f"Отклики успешно записаны в базу данных ({done} шт.).")
    return True


if __name__ == "__main__":
    if migrate_vacancies_and_resumes():
        if migrate_negotiations():
            print()
            print_success("Перенос данных полностью завершен.")
