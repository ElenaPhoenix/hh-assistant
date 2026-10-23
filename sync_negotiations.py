import json
import os
from state_helper import load_state, save_state, add_applied_id
from shared_api import fetch_all_negotiations
from utils import load_config, resume_id_from_url


def main():
    config = load_config()
    resume_url = config["resumes"][0]["url"]
    resume_id = resume_id_from_url(resume_url)

    print(f"Резюме: {resume_id}")
    print("Загружаем все отклики...")
    all_items = fetch_all_negotiations(per_page=100, pause=0.3)
    print(f"\nВсего загружено записей: {len(all_items)}")

    our_vacancy_ids = set()
    for item in all_items:
        r = item.get("resume") or {}
        if not isinstance(r, dict) or not r.get("id") or r.get("id") != resume_id:
            continue
        vid = (item.get("vacancy") or {}).get("id")
        if vid:
            our_vacancy_ids.add(int(vid))

    print(f"Откликов с нашего резюме: {len(our_vacancy_ids)}")

    state = load_state()
    before = len(state["resumes"].get(resume_id, {}).get("applied_vacancy_ids", []))
    for vid in our_vacancy_ids:
        add_applied_id(state, resume_id, vid)
    save_state(state)
    after = len(state["resumes"][resume_id]["applied_vacancy_ids"])

    print(
        f"\nДо: {before} applied\nПосле: {after} applied\nДобавлено: {after - before}"
    )


if __name__ == "__main__":
    main()
