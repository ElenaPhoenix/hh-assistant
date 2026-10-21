import re
from rapidfuzz import fuzz

LOOKALIKE_MAP = str.maketrans(
    {"a": "а", "c": "с", "e": "е", "o": "о", "p": "р", "x": "х", "y": "у"}
)
STRONG_ANALYTICS = ["аналитик", "analyst", "data", "bi", "sql", "python"]


def normalize_for_match(text):
    if not text:
        return ""
    t = text.lower().translate(LOOKALIKE_MAP)
    t = re.sub(r"[\s\-_/\\|]+", " ", t)
    return t.strip()


def check_filters(
    name, desc, target_title, exclude_words, core_keywords, resume_skills=None
):
    """
    Универсальная функция фильтрации.
    1. Проверяет стоп-слова (Fuzzy 95% в названии).
    2. Если в названии есть явная аналитика (из STRONG_ANALYTICS) - пропускает.
    3. Иначе требует наличие core_keywords в описании.
    4. Проверяет совпадение с target_title (Fuzzy 90% в названии или вхождение в описание).
    5. Проверяет наличие навыков из резюме в описании.
    """
    name_norm = normalize_for_match(name)
    desc_norm = normalize_for_match(desc)

    # 1. Стоп-слова
    for word in exclude_words:
        w_norm = normalize_for_match(word)
        if w_norm and fuzz.partial_ratio(w_norm, name_norm) >= 95:
            return False

    # 2. Явные аналитические названия
    if any(sw in name_norm for sw in STRONG_ANALYTICS):
        return True

    # 3. CORE_KEYWORDS
    has_core_kw = any(kw in desc_norm for kw in core_keywords)
    if not has_core_kw:
        return False

    # 4. Совпадение с target
    targets = [normalize_for_match(t) for t in target_title.split("|") if t.strip()]
    if targets:
        for t in targets:
            if fuzz.partial_ratio(t, name_norm) >= 90 or t in desc_norm:
                return True

    # 5. Навыки из резюме
    if resume_skills:
        for skill in resume_skills:
            s_norm = normalize_for_match(skill)
            if s_norm and fuzz.partial_ratio(s_norm, desc_norm) >= 95:
                return True

    return False
