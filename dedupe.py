"""
Утилита дедупликации вакансий.

Используется в apply_via_api.py и main.py, чтобы не отправлять
отклики на несколько одинаковых публикаций одного работодателя
и не показывать в статистике завышенные числа.
"""


def dedupe_passed(passed):
    """
    Убирает дубли среди passed-вакансий.

    Ключ дубля: (employer, name, match_score) - все три поля совпадают.
    Если что-то не совпало - обе вакансии остаются.

    Оставляет первый встреченный вариант (в passed они уже
    отсортированы по убыванию match_score, поэтому "первый" - лучший).
    """
    seen = set()
    result = []
    for v in passed:
        key = (
            (v.get("employer") or "").strip().lower(),
            (v.get("name") or "").strip().lower(),
            v.get("match_score"),
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(v)
    return result
