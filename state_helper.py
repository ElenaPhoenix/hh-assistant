# Прогресс
import json
import os
from datetime import datetime

STATE_FILE = "state.json"


def load_state():
    if not os.path.exists(STATE_FILE):
        return {"current_resume_index": 0, "resumes": {}}
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {"current_resume_index": 0, "resumes": {}}

    if "resumes" not in data:
        data = {"current_resume_index": 0, "resumes": {}}

    return data


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def get_resume_state(state, resume_id):
    if resume_id not in state["resumes"]:
        state["resumes"][resume_id] = {
            "url": "",
            "title": "",
            "phase": "not_started",
            "processed_vacancy_ids": [],
            "applied_vacancy_ids": [],
            "denied_vacancy_ids": [],
            "needs_test": [],
            "last_run": None,
        }
    rs = state["resumes"][resume_id]
    if "denied_vacancy_ids" not in rs:
        rs["denied_vacancy_ids"] = []
    if "needs_test" not in rs:
        rs["needs_test"] = []
    return rs


# --- Phase ---


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


def set_current_resume_index(state, index):
    state["current_resume_index"] = index


# --- Processed ---


def add_processed_ids(state, resume_id, ids):
    rs = get_resume_state(state, resume_id)
    existing = set(rs["processed_vacancy_ids"])
    for vid in ids:
        if vid is not None and vid not in existing:
            rs["processed_vacancy_ids"].append(vid)
            existing.add(vid)


def get_processed_ids(state, resume_id):
    return set(get_resume_state(state, resume_id)["processed_vacancy_ids"])


# --- Applied ---


def add_applied_id(state, resume_id, vid):
    rs = get_resume_state(state, resume_id)
    if vid is not None and vid not in rs["applied_vacancy_ids"]:
        rs["applied_vacancy_ids"].append(vid)


def get_applied_ids(state, resume_id):
    return set(get_resume_state(state, resume_id)["applied_vacancy_ids"])


# --- Denied ---


def add_denied_id(state, resume_id, vid):
    rs = get_resume_state(state, resume_id)
    if vid is not None and vid not in rs["denied_vacancy_ids"]:
        rs["denied_vacancy_ids"].append(vid)


def get_denied_ids(state, resume_id):
    return set(get_resume_state(state, resume_id)["denied_vacancy_ids"])


# --- Needs test ---


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


# --- Reset ---


def reset_processed(state, resume_id):
    rs = get_resume_state(state, resume_id)
    rs["processed_vacancy_ids"] = []


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
    rs["processed_vacancy_ids"] = []
    rs["applied_vacancy_ids"] = []
    rs["denied_vacancy_ids"] = []
    rs["needs_test"] = []
    rs["phase"] = "parsed"


if __name__ == "__main__":
    s = load_state()
    print(json.dumps(s, ensure_ascii=False, indent=2))
