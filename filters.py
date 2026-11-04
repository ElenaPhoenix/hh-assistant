import re
from rapidfuzz.distance import Levenshtein as Lev
from utils import normalize

_SHORT_WORD_LEN = 5
_MAX_EDIT_DISTANCE = 2
_SPECIAL_CHARS = re.compile(r"[#+]")
_TOKEN_RE = re.compile(r"\w+(?:[#+]+)?")


def _extract_words(text_norm):
    """Извлекает токены из нормализованного текста.

    Токен - \\w+ с необязательным суффиксом из # или + (для c#, c++).
    Точка, запятая и прочие разделители отбрасываются.

    Примеры:
      "c# developer"     -> ["c#", "developer"]
      "c++, python"      -> ["c++", "python"]
      "офис-менеджер"    -> ["офис", "менеджер"]  (после normalize)
    """
    if not text_norm:
        return []
    return _TOKEN_RE.findall(text_norm)


def _has_special(word):
    return bool(_SPECIAL_CHARS.search(word))


def _word_match(a, b):
    """Совпадение двух слов.

    Правила:
      - есть спецсимвол (# или +) в любом из слов - только точное;
      - любое из слов короче 5 символов - только точное;
      - иначе расстояние Левенштейна <= 2
        (pre-filter по длине + score_cutoff для скорости).
    """
    if _has_special(a) or _has_special(b):
        return a == b
    if len(a) < _SHORT_WORD_LEN or len(b) < _SHORT_WORD_LEN:
        return a == b
    if abs(len(a) - len(b)) > _MAX_EDIT_DISTANCE:
        return False
    return Lev.distance(a, b, score_cutoff=_MAX_EDIT_DISTANCE) <= _MAX_EDIT_DISTANCE


def _consecutive_words_match(phrase_words, text_words):
    """Фраза как последовательность подряд идущих слов в тексте.

    Скользящее окно размером len(phrase_words): каждое слово фразы
    сравнивается с соответствующим словом текста через _word_match.
    """
    n = len(phrase_words)
    if n == 0 or n > len(text_words):
        return False
    for start in range(len(text_words) - n + 1):
        if all(_word_match(phrase_words[i], text_words[start + i]) for i in range(n)):
            return True
    return False


def _phrase_in_text(phrase_norm, text_words):
    """Проверяет, что фраза встречается в тексте как последовательность слов."""
    p_words = _extract_words(phrase_norm)
    if not p_words or not text_words:
        return False
    if len(p_words) == 1:
        return any(_word_match(p_words[0], tw) for tw in text_words)
    return _consecutive_words_match(p_words, text_words)


def check_vacancy_relevance(
    name, description, target_title, exclude_words, core_keywords
):
    name_norm = normalize(name)
    desc_norm = normalize(description or "")
    name_words = _extract_words(name_norm)
    desc_words = _extract_words(desc_norm)

    # 1. Слова-исключения (приоритет выше target и keywords).
    #    Проверяем в названии и описании; если хоть одно совпало - отказ.
    if exclude_words:
        for word in exclude_words:
            w_norm = normalize(word)
            if not w_norm:
                continue
            if _phrase_in_text(w_norm, name_words):
                return False
            if _phrase_in_text(w_norm, desc_words):
                return False

    # 2. Целевые фразы и ключевые слова (разделитель target_title - "|")
    targets = []
    if target_title:
        targets = [normalize(t) for t in target_title.split("|") if t.strip()]

    keywords = []
    if core_keywords:
        keywords = [normalize(k) for k in core_keywords if k.strip()]

    if not targets and not keywords:
        return True

    # 3. target_title в названии
    for t in targets:
        if t and _phrase_in_text(t, name_words):
            return True

    # 4. core_keywords в описании
    if desc_words:
        for k in keywords:
            if k and _phrase_in_text(k, desc_words):
                return True

    return False
