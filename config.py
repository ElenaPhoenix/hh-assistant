# Интерактивное меню - config.json
import json
import os

CONFIG_FILE = "config.json"


def ask_yes_no(prompt):
    while True:
        ans = input(f"{prompt} (y/n): ").strip().lower()
        if ans in ("y", "n"):
            return ans == "y"
        print("Введи y или n.")


def ask_int(prompt, default=None):
    while True:
        val = input(prompt).strip()
        if not val and default is not None:
            return default
        try:
            return int(val)
        except ValueError:
            print("Введи целое число.")


def ask_list(prompt):
    val = input(f"{prompt} (через запятую): ").strip()
    if not val:
        return []
    return [x.strip() for x in val.split(",") if x.strip()]


def ask_target_phrases():
    """Ввод целевых фраз по одной до слова 'стоп'."""
    print("\nВведи целевые фразы для названия вакансии (по одной).")
    print("Пример: 'аналитик', 'analyst', 'операционный менеджер'.")
    print("Когда закончишь — введи 'стоп'.")
    phrases = []
    while True:
        w = input("  Фраза: ").strip()
        if w.lower() == "стоп":
            break
        if w:
            phrases.append(w)
    return phrases


def ask_exclude_words():
    """Ввод слов-исключений по одной до слова 'стоп'."""
    print("\nВведи слова-исключения для названий вакансий (по одному).")
    print("Пример: 'senior', 'руководитель', '1С'.")
    print("Когда закончишь — введи 'стоп'.")
    words = []
    while True:
        w = input("  Исключение: ").strip()
        if w.lower() == "стоп":
            break
        if w:
            words.append(w)
    return words


def ask_periods():
    print("\nЗа какой период искать вакансии? (можно несколько через запятую)")
    print("  1 - За сегодня")
    print("  2 - За 3 дня")
    print("  3 - За неделю")
    print("  4 - За месяц")
    print("  5 - За все время")
    choices = ask_list("  Выбери номера (например: 2,3)")
    period_map = {"1": 1, "2": 3, "3": 7, "4": 30, "5": 0}
    result = [period_map[c] for c in choices if c in period_map]
    return result if result else [0]


def collect_queries():
    """Создаёт один или несколько поисковых запросов для резюме."""
    print("\n--- Настройка поисковых запросов ---")
    n_queries = ask_int("Сколько запросов создать? ", default=1)
    queries = []
    for i in range(n_queries):
        print(f"\n  Запрос #{i + 1}")
        name = input("    Название запроса (например, 'Data Analyst'): ").strip()
        target_phrases = ask_target_phrases()
        exclude_words = ask_exclude_words()
        periods = ask_periods()

        # Собираем фразы в строку через '|' для совместимости с vacancy_search.py
        target_title = "|".join(target_phrases) if target_phrases else "аналитик"

        queries.append(
            {
                "name": name or f"Запрос {i + 1}",
                "target_title": target_title,
                "exclude_words": exclude_words,
                "employments": ["full", "part", "project"],
                "work_formats": ["remote", "hybrid", "office"],
                "periods": periods,
                "min_salary": 0,
                "only_with_salary": False,
            }
        )
    return queries


def main_menu():
    print("=" * 70)
    print(" HH ASSISTANT: настройка поиска (Мультирезюме)")
    print("=" * 70)

    n_resumes = ask_int("Сколько резюме будем использовать? ", default=1)
    resumes = []

    for i in range(n_resumes):
        print(f"\n--- Резюме #{i + 1} ---")
        url = input("URL резюме (https://hh.ru/resume/xxx): ").strip()
        queries = collect_queries()
        resumes.append({"url": url, "queries": queries})

    threshold = ask_int("\nПорог соответствия (рекомендуется 65): ", default=65)

    print("\nРежим отклика:")
    print("  1 - с подтверждением (безопасно, рекомендую)")
    print("  2 - полностью автоматически (риск блокировки)")
    auto_mode = input("  Выбери номер [1]: ").strip() or "1"

    config = {
        "resumes": resumes,
        "threshold": threshold,
        "auto_apply": auto_mode == "2",
    }

    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)

    print(f"\nКонфиг сохранён в {CONFIG_FILE}")
    return config


def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


if __name__ == "__main__":
    if os.path.exists(CONFIG_FILE):
        print(f"Файл {CONFIG_FILE} уже существует.")
        if not ask_yes_no("Перезаписать?"):
            print("Отменено.")
            exit()
    main_menu()
