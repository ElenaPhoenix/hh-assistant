import json
import os
import re
import subprocess
import time
from state_helper import load_state, save_state, add_applied_id

CONFIG_FILE = "config.json"


def call_api(endpoint):
    result = subprocess.run(
        ["hh-applicant-tool", "call-api", "--json", endpoint],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode != 0:
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return None


def main():
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        config = json.load(f)

    resume_url = config["resumes"][0]["url"]
    match = re.search(r"/resume/([a-f0-9]+)", resume_url)
    resume_id = match.group(1)

    print(f"Резюме: {resume_id}")

    # Увеличиваем per_page до 100 для ускорения (если API не поддержит, сработает fallback)
    per_page = 100
    print(f"Загружаем отклики (по {per_page} на страницу)...\n")

    all_items = []
    page = 0

    while True:
        endpoint = f"/negotiations?per_page={per_page}&page={page}"
        print(f"  Страница {page}...", end=" ", flush=True)
        data = call_api(endpoint)

        if not data:
            print("ошибка, стоп.")
            break

        items = data.get("items", [])
        found = data.get("found", 0)
        pages = data.get("pages", 0)

        if not items:
            print("пусто, стоп.")
            break

        all_items.extend(items)
        print(f"получено {len(items)} (всего {len(all_items)}/{found})")

        page += 1
        if page >= pages:
            break

        time.sleep(0.3)  # Пауза меньше, так как запросов теперь в 5 раз меньше

    print(f"\nВсего загружено записей: {len(all_items)}")

    our_vacancy_ids = set()
    skipped_no_resume = 0
    skipped_other_resume = 0
    skipped_no_vacancy = 0

    for item in all_items:
        r = item.get("resume") or {}
        if not isinstance(r, dict) or not r.get("id"):
            skipped_no_resume += 1
            continue
        if r.get("id") != resume_id:
            skipped_other_resume += 1
            continue
        vacancy = item.get("vacancy") or {}
        vid = vacancy.get("id")
        if not vid:
            skipped_no_vacancy += 1
            continue
        our_vacancy_ids.add(int(vid))

    print(f"\nЗаписей без резюме: {skipped_no_resume}")
    print(f"Записей с другими резюме: {skipped_other_resume}")
    print(f"Записей без вакансии: {skipped_no_vacancy}")
    print(f"Откликов с нашего резюме: {len(our_vacancy_ids)}")

    state = load_state()
    before = len(state["resumes"].get(resume_id, {}).get("applied_vacancy_ids", []))

    for vid in our_vacancy_ids:
        add_applied_id(state, resume_id, vid)

    save_state(state)
    after = len(state["resumes"][resume_id]["applied_vacancy_ids"])

    print(f"\nДо: {before} applied")
    print(f"После: {after} applied")
    print(f"Добавлено: {after - before}")


if __name__ == "__main__":
    main()
