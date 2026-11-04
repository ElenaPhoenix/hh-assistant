"""
Утилита для ручной миграции JSON-файлов в PostgreSQL.
Используется, если нужно полностью перезалить данные в БД.
"""

import json
import os
from db import db_cursor, init_db
from shared_api import fetch_all_negotiations
from utils import load_config, resume_id_from_url, load_resume, VACANCIES_FILE


def migrate_vacancies_and_resumes():
    print("Подключаемся к БД...")
    init_db()

    with db_cursor() as cur:
        if os.path.exists(VACANCIES_FILE):
            with open(VACANCIES_FILE, "r", encoding="utf-8") as f:
                vacancies = json.load(f)

            print(f"Заливаем {len(vacancies)} вакансий...")
            for v in vacancies:
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

        config = load_config()
        if config.get("resumes"):
            print(f"Заливаем {len(config['resumes'])} резюме...")
            for r_cfg in config["resumes"]:
                rid = resume_id_from_url(r_cfg["url"])
                resume_data = load_resume(rid) or {}
                title = resume_data.get("title", "Резюме")
                cur.execute(
                    "INSERT INTO resumes (id, title) VALUES (%s, %s) ON CONFLICT (id) DO UPDATE SET title = EXCLUDED.title;",
                    (rid, title),
                )

    print("✅ Вакансии и резюме успешно залиты в БД.")


def migrate_negotiations():
    print("\nЗапрашиваем отклики с hh.ru (это займет время)...")
    all_items = fetch_all_negotiations(per_page=100, pause=0.1)
    print(f"Загружено {len(all_items)} записей с hh.")

    config = load_config()

    with db_cursor() as cur:
        print("Распределяем отклики по резюме и заливаем...")
        for r_cfg in config["resumes"]:
            rid = resume_id_from_url(r_cfg["url"])
            our_items = [
                item
                for item in all_items
                if ((item.get("resume") or {}).get("id") == rid)
            ]

            for item in our_items:
                neg_id = item.get("id")
                vacancy_data = item.get("vacancy") or {}
                vac_id_str = vacancy_data.get("id")

                if not neg_id or not vac_id_str:
                    continue

                vac_id = int(vac_id_str)
                status = (item.get("state") or {}).get("id", "")

                cur.execute(
                    "INSERT INTO vacancies (id, name, employer) VALUES (%s, %s, %s) ON CONFLICT (id) DO NOTHING;",
                    (
                        vac_id,
                        vacancy_data.get("name", ""),
                        (vacancy_data.get("employer") or {}).get("name", ""),
                    ),
                )

                # Также оставляем hh_updated_at пустым для правильной работы check_messages
                cur.execute(
                    """INSERT INTO negotiations (id, vacancy_id, resume_id, status, hh_updated_at)
                       VALUES (%s, %s, %s, %s, %s) 
                       ON CONFLICT (id) DO UPDATE SET
                       status = EXCLUDED.status, 
                       updated_at = CURRENT_TIMESTAMP;""",
                    (neg_id, vac_id, rid, status, ""),
                )

    print("✅ Отклики успешно залиты в БД.")


if __name__ == "__main__":
    migrate_vacancies_and_resumes()
    migrate_negotiations()
    print("\n🎉 Миграция полностью завершена.")
