import json
import os
import re
import urllib.parse

DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)

VACANCIES_FILE = os.path.join(DATA_DIR, "vacancies_detailed.json")
RESUMES_DIR = os.path.join(DATA_DIR, "resumes")
MATCHES_DIR = os.path.join(DATA_DIR, "matches")
LETTERS_DIR = os.path.join(DATA_DIR, "letters")
FIXED_LETTER_FILE = os.path.join(DATA_DIR, "fixed_letter.txt")

CONFIG_FILE = os.path.join(DATA_DIR, "config.json")
STATE_FILE = os.path.join(DATA_DIR, "state.json")
LEGACY_SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")
LEGACY_SETTINGS_ROOT = "settings.json"

DEFAULT_THRESHOLD = 65
DEFAULT_CONFIG = {"threshold": DEFAULT_THRESHOLD, "resumes": []}

_LEGACY_TECH_KEYS = {
    "auto_apply",
    "sigmoid_center",
    "sigmoid_temperature",
    "matcher_batch_size",
    "match_top_percent",
    "matcher",
}


def normalize(text):
    if not text:
        return ""
    return re.sub(r"[\s\-_/\\|]+", " ", text.lower()).strip()


def clean_text(text):
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()


def clear_query_hash(resume_id, qid):
    """Удаляет хэш запроса из matches.json.

    После этого matcher при следующем запуске увидит is_current == False
    и сам сделает полный пересчет: очистит старые all/passed записи
    этого qid и заново прогонит все вакансии через все фильтры
    (город, формат, слова-исключения, ключевые слова).
    """
    path = os.path.join(MATCHES_DIR, f"{resume_id}.json")
    if not os.path.exists(path):
        return
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return
    if not isinstance(data, dict):
        return
    hashes = data.get("query_hashes", {})
    if qid in hashes:
        del hashes[qid]
        atomic_write_json(path, data)


def encode_url(value):
    return urllib.parse.quote(str(value), safe="")


def query_key(q):
    if not isinstance(q, dict):
        return "default"
    return q.get("id") or q.get("name") or "default"


def atomic_write_json(path, payload):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def load_config():
    """Загружает конфиг из data/config.json."""
    config = dict(DEFAULT_CONFIG)
    if not os.path.exists(CONFIG_FILE):
        return config

    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                config.update(data)
    except Exception:
        pass
    return config


def save_config(config):
    payload = {
        "threshold": int(config.get("threshold", DEFAULT_THRESHOLD)),
        "resumes": config.get("resumes", []),
    }
    atomic_write_json(CONFIG_FILE, payload)


def load_resume(resume_id):
    path = os.path.join(RESUMES_DIR, f"{resume_id}.json")
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_matches(resume_id):
    path = os.path.join(MATCHES_DIR, f"{resume_id}.json")
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_vacancies():
    if not os.path.exists(VACANCIES_FILE):
        return {}
    try:
        with open(VACANCIES_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return {}
    if not isinstance(data, list):
        return {}
    result = {}
    for v in data:
        try:
            vid = int(v.get("id", 0))
        except (TypeError, ValueError):
            continue
        if vid:
            result[vid] = v
    return result


def save_vacancies(v_dict):
    os.makedirs(DATA_DIR, exist_ok=True)
    payload = sorted(v_dict.values(), key=lambda x: x.get("id", 0), reverse=True)
    atomic_write_json(VACANCIES_FILE, payload)
    return len(payload)


def remove_vacancies_from_cache(vids):
    if not vids:
        return 0
    vacancies = load_vacancies()
    if not vacancies:
        return 0
    vids_set = set()
    for v in vids:
        try:
            vids_set.add(int(v))
        except (TypeError, ValueError):
            continue
    if not vids_set:
        return 0
    removed = 0
    for vid in vids_set:
        if vid in vacancies:
            del vacancies[vid]
            removed += 1
    if removed == 0:
        return 0
    save_vacancies(vacancies)
    return removed


def resume_id_from_url(url):
    match = re.search(r"/resume/([a-f0-9]+)", url)
    return match.group(1) if match else None


def load_fixed_letter():
    if not os.path.exists(FIXED_LETTER_FILE):
        return None
    with open(FIXED_LETTER_FILE, "r", encoding="utf-8") as f:
        return f.read().strip()
