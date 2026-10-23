import json
import os
from db import get_connection, init_db
from shared_api import fetch_all_negotiations
from utils import load_config, resume_id_from_url, DATA_DIR, RESUMES_DIR, LETTERS_DIR

VACANCIES_FILE = os.path.join(DATA_DIR, "vacancies_detailed.json")


def save_vacancies_and_resumes():
    conn = get_connection()
    cur = conn.cursor()
    config = load_config()
    for res in config.get("resumes", []):
        res_id = resume_id_from_url(res["url"])
        if res_id:
            cur.execute(
                "INSERT INTO resumes (id, title) VALUES (%s, %s) ON CONFLICT DO NOTHING;",
                (res_id, "Основное резюме"),
            )

    if os.path.exists(VACANCIES_FILE):
        with open(VACANCIES_FILE, "r", encoding="utf-8") as f:
            vacancies = json.load(f)
        print(f"Заливаем {len(vacancies)} вакансий...")
        for v in vacancies:
            cur.execute(
                """
                INSERT INTO vacancies (id, name, employer, salary_from, salary_to, salary_currency, link, full_description)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name, employer = EXCLUDED.employer, full_description = EXCLUDED.full_description;
            """,
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
    conn.commit()
    cur.close()
    conn.close()
    print("Вакансии и резюме загружены.")


def sync_negotiations_to_db():
    print("Запрашиваем актуальные отклики...")
    items = fetch_all_negotiations(per_page=100, pause=0.3)
    if not items:
        return
    conn = get_connection()
    cur = conn.cursor()
    print(f"Заливаем {len(items)} откликов...")
    for item in items:
        neg_id = item.get("id")
        vacancy_data = item.get("vacancy") or {}
        vac_id = vacancy_data.get("id")
        resume_data = item.get("resume") or {}
        res_id = resume_data.get("id")
        state = (item.get("state") or {}).get("id", "unknown")
        if not neg_id or not vac_id or not res_id:
            continue

        cur.execute(
            "INSERT INTO vacancies (id, name, employer) VALUES (%s, %s, %s) ON CONFLICT (id) DO NOTHING;",
            (
                vac_id,
                vacancy_data.get("name", "Неизвестная вакансия"),
                (vacancy_data.get("employer") or {}).get(
                    "name", "Неизвестный работодатель"
                ),
            ),
        )
        cur.execute(
            "INSERT INTO resumes (id, title) VALUES (%s, %s) ON CONFLICT (id) DO NOTHING;",
            (res_id, resume_data.get("title", "Резюме без названия")),
        )
        cur.execute(
            """
            INSERT INTO negotiations (id, vacancy_id, resume_id, status) VALUES (%s, %s, %s, %s) ON CONFLICT (id) DO UPDATE SET status = EXCLUDED.status, updated_at = CURRENT_TIMESTAMP;
        """,
            (neg_id, vac_id, res_id, state),
        )
    conn.commit()
    cur.close()
    conn.close()
    print("Отклики загружены.")


if __name__ == "__main__":
    init_db()
    save_vacancies_and_resumes()
    sync_negotiations_to_db()
