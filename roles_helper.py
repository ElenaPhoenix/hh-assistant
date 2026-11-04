import json
import os
import requests
from utils import DATA_DIR

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


def suggest_roles_by_keywords(keywords):
    """Автоматически подбирает ID ролей по ключевым словам (простое вхождение)."""
    roles = load_professional_roles()
    if not roles:
        return []
    found_ids = set()
    for kw in keywords:
        kw_norm = kw.strip().lower()
        if not kw_norm:
            continue
        for role in roles:
            if kw_norm in role["name"].lower():
                found_ids.add(role["id"])
    return sorted(found_ids)
