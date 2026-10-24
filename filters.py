from utils import normalize


def check_name_filters(name, target_title, exclude_words):
    """
    Легкая локальная проверка названия вакансии.
    Если target_title пустой (поиск только по ролям), проверяет только слова-исключения.
    """
    name_norm = normalize(name)

    # 1. Слова-исключения
    if exclude_words:
        for word in exclude_words:
            w_norm = normalize(word)
            # Защита: игнорируем пустые строки и None, чтобы не забраковать всё
            if w_norm and w_norm in name_norm:
                return False

    # 2. Целевые фразы
    if target_title:
        targets = [normalize(t) for t in target_title.split("|") if normalize(t)]
        if targets:
            if not any(t in name_norm for t in targets):
                return False

    return True
