import json
import os
from datetime import datetime

from utils import STATE_FILE, atomic_write_json


def load_state():
    if not os.path.exists(STATE_FILE):
        return {"current_resume_index": 0, "current_query_id": None, "resumes": {}}
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {"current_resume_index": 0, "current_query_id": None, "resumes": {}}

    if "current_query_id" not in data:
        data["current_query_id"] = None
    if "current_resume_index" not in data:
        data["current_resume_index"] = 0
    if "resumes" not in data:
        data["resumes"] = {}
    return data


def save_state(state):
    try:
        atomic_write_json(STATE_FILE, state)
    except Exception as e:
        print(f"Критическая ошибка сохранения прогресса: {e}")


def get_resume_state(state, resume_id):
    if resume_id not in state["resumes"]:
        state["resumes"][resume_id] = {
            "url": "",
            "title": "",
            "phase": "not_started",
            "processed_vacancy_ids": {},
            "applied_vacancy_ids": [],
            "denied_vacancy_ids": [],
            "needs_test": [],
            "last_run": None,
        }
    rs = state["resumes"][resume_id]
    if "applied_vacancy_ids" not in rs:
        rs["applied_vacancy_ids"] = []
    if "denied_vacancy_ids" not in rs:
        rs["denied_vacancy_ids"] = []
    if "needs_test" not in rs:
        rs["needs_test"] = []
    return rs


def set_phase(state, resume_id, phase):
    rs = get_resume_state(state, resume_id)
    rs["phase"] = phase
    rs["last_run"] = datetime.now().isoformat(timespec="seconds")


def get_phase(state, resume_id):
    return get_resume_state(state, resume_id)["phase"]


def set_resume_meta(state, resume_id, url=None, title=None):
    rs = get_resume_state(state, resume_id)
    if url:
        rs["url"] = url
    if title:
        rs["title"] = title


def add_processed_ids(state, resume_id, query_id, ids):
    rs = get_resume_state(state, resume_id)
    if query_id not in rs["processed_vacancy_ids"]:
        rs["processed_vacancy_ids"][query_id] = []
    existing = set(rs["processed_vacancy_ids"][query_id])
    for vid in ids:
        if vid is not None and vid not in existing:
            rs["processed_vacancy_ids"][query_id].append(vid)
            existing.add(vid)


def get_processed_ids(state, resume_id, query_id):
    return set(
        get_resume_state(state, resume_id)["processed_vacancy_ids"].get(query_id, [])
    )


def add_applied_id(state, resume_id, vid):
    rs = get_resume_state(state, resume_id)
    if vid is not None and vid not in rs["applied_vacancy_ids"]:
        rs["applied_vacancy_ids"].append(vid)


def get_applied_ids(state, resume_id):
    return set(get_resume_state(state, resume_id)["applied_vacancy_ids"])


def add_denied_id(state, resume_id, vid):
    rs = get_resume_state(state, resume_id)
    if vid is not None and vid not in rs["denied_vacancy_ids"]:
        rs["denied_vacancy_ids"].append(vid)


def get_denied_ids(state, resume_id):
    return set(get_resume_state(state, resume_id)["denied_vacancy_ids"])


def add_needs_test(state, resume_id, entry):
    rs = get_resume_state(state, resume_id)
    for item in rs["needs_test"]:
        if item.get("id") == entry["id"]:
            item.update(entry)
            return
    rs["needs_test"].append(entry)


def remove_needs_test(state, resume_id, vid):
    rs = get_resume_state(state, resume_id)
    rs["needs_test"] = [i for i in rs["needs_test"] if i.get("id") != vid]


def get_needs_test(state, resume_id):
    return get_resume_state(state, resume_id)["needs_test"]


def mark_denied(state, resume_id, vid):
    """Помечает вакансию как отказ во всех наших хранилищах.

    Действия:
      - добавляет в denied_vacancy_ids (чтобы не вернулась в очередь);
      - убирает из needs_test (чтобы не показывалась в пункте 5);
      - сохраняет state.json.

    Удаление из vacancies_detailed.json - отдельный шаг
    (remove_vacancies_from_cache), т.к. требует файловой операции.
    """
    add_denied_id(state, resume_id, vid)
    remove_needs_test(state, resume_id, vid)
    save_state(state)


def reset_processed(state, resume_id, query_id):
    rs = get_resume_state(state, resume_id)
    if query_id in rs["processed_vacancy_ids"]:
        rs["processed_vacancy_ids"][query_id] = []


def reset_applied(state, resume_id):
    rs = get_resume_state(state, resume_id)
    rs["applied_vacancy_ids"] = []


def reset_denied(state, resume_id):
    rs = get_resume_state(state, resume_id)
    rs["denied_vacancy_ids"] = []


def reset_needs_test(state, resume_id):
    rs = get_resume_state(state, resume_id)
    rs["needs_test"] = []


def reset_all(state, resume_id):
    rs = get_resume_state(state, resume_id)
    rs["processed_vacancy_ids"] = {}
    rs["applied_vacancy_ids"] = []
    rs["denied_vacancy_ids"] = []
    rs["needs_test"] = []
    rs["phase"] = "parsed"
