import json
import os
import re
import requests
from rapidfuzz import fuzz
from utils import DATA_DIR  # <-- ИСПРАВЛЕНО: теперь берем из utils

ROLES_FILE = os.path.join(DATA_DIR, "professional_roles.json")
ROLES_URL = "https://api.hh.ru/professional_roles"


def load_professional_roles(force_refresh=False):
    if os.path.exists(ROLES_FILE) and not force_refresh:
        with open(ROLES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    print("Загружаем справочник профессий с hh.ru...")
    try:
        resp = requests.get(ROLES_URL, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        roles = []
        for cat in data.get("categories", []):
            for role in cat.get("roles", []):
                roles.append({"id": role["id"], "name": role["name"]})
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(ROLES_FILE, "w", encoding="utf-8") as f:
            json.dump(roles, f, ensure_ascii=False, indent=2)
        return roles
    except Exception as e:
        print(f"Ошибка загрузки справочника: {e}")
        return []


def suggest_roles_by_keywords(keywords, threshold=80):
    roles = load_professional_roles()
    if not roles:
        return []
    found_ids = set()
    for kw in keywords:
        kw_norm = kw.strip().lower()
        if not kw_norm:
            continue
        for role in roles:
            if fuzz.partial_ratio(kw_norm, role["name"].lower()) >= threshold:
                found_ids.add(role["id"])
    return sorted(found_ids)


def validate_search_query(query):
    if not query:
        return True, ""
    if query.count("(") != query.count(")"):
        return False, "Непарные скобки"
    if query.count('"') % 2 != 0:
        return False, "Непарные двойные кавычки"
    if re.search(r"[<>]", query):
        return False, "Недопустимые символы (< или >)"
    return True, ""
