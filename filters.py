from utils import normalize


def check_name_filters(name, target_title, exclude_words):
    """
    Легкая локальная проверка названия вакансии.
    Если target_title пустой (поиск только по ролям), проверяет только стоп-слова.
    """
    name_norm = normalize(name)

    # 1. Стоп-слова
    for word in exclude_words:
        if normalize(word) in name_norm:
            return False

    # 2. Целевые фразы
    if target_title:
        targets = [normalize(t) for t in target_title.split("|") if t.strip()]
        if targets:
            if not any(t in name_norm for t in targets):
                return False

    return True
