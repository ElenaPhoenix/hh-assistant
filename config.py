import json
from roles_helper import suggest_roles_by_keywords, load_professional_roles
from ui_helper import ask_yes_no, print_success, print_error, print_info
from utils import CONFIG_FILE

# Стандартные ключевые слова на основе твоего резюме
DEFAULT_DESC_KEYWORDS = [
    "sql",
    "python",
    "excel",
    "bi",
    "power bi",
    "google sheets",
    "data studio",
    "datalens",
    "clickhouse",
    "postgresql",
    "etl",
    "дашборд",
    "отчет",
    "метрики",
    "аналитика",
    "a/b тест",
    "jira",
    "confluence",
    "bpmn",
    "api",
    "pandas",
    "numpy",
]


def ask_int(prompt, default=None):
    while True:
        val = input(prompt).strip()
        if not val and default is not None:
            return default
        try:
            return int(val)
        except ValueError:
            print_error("Введи целое число.")


def ask_list(prompt):
    val = input(f"{prompt} (через запятую): ").strip()
    return [x.strip() for x in val.split(",") if x.strip()] if val else []


def edit_list(items, prompt_name):
    while True:
        print_info(f"\n--- {prompt_name} ---")
        if not items:
            print("  (список пуст)")
        else:
            for i, item in enumerate(items, 1):
                print(f"  {i}. {item}")
        print(
            "\nДействия:\n  [с] - Сохранить\n  [д] - Добавить\n  [и] - Изменить\n  [у] - Удалить"
        )
        ans = input("Твой выбор (с/д/и/у): ").strip().lower()
        if ans == "с":
            break
        elif ans == "д":
            new = input("  Введи новое значение: ").strip()
            if new:
                items.append(new)
        elif ans == "и":
            try:
                idx = int(input("  Номер для изменения: ")) - 1
                if 0 <= idx < len(items):
                    new = input("  Новое значение: ").strip()
                    if new:
                        items[idx] = new
                else:
                    print_error("Неверный номер.")
            except ValueError:
                print_error("Введи число.")
        elif ans == "у":
            try:
                idx = int(input("  Номер для удаления: ")) - 1
                if 0 <= idx < len(items):
                    items.pop(idx)
                else:
                    print_error("Неверный номер.")
            except ValueError:
                print_error("Введи число.")
        else:
            print_error("Неизвестная команда.")
    return items


def ask_title_keywords():
    print(
        "\nВведи СЛОВА ДЛЯ ПОИСКА В НАЗВАНИИ ВАКАНСИИ (по одной, 'стоп' для завершения)."
    )
    print("Пример: аналитик, analyst, data analyst.")
    phrases = []
    while True:
        w = input("  Слово в названии: ").strip()
        if w.lower() == "стоп":
            break
        if w:
            phrases.append(w)
    return edit_list(phrases, "Слова для поиска в названии")


def ask_exclude_words():
    print("\nВведи СЛОВА-ИСКЛЮЧЕНИЯ (по одному, 'стоп' для завершения).")
    print("Вакансии с этими словами будут отброшены.")
    words = []
    while True:
        w = input("  Исключение: ").strip()
        if w.lower() == "стоп":
            break
        if w:
            words.append(w)
    return edit_list(words, "Слова-исключения")


def ask_desc_keywords():
    print("\nАнализ резюме завершен.")
    print(
        "Мы предлагаем использовать следующие КЛЮЧЕВЫЕ СЛОВА ДЛЯ ПОИСКА В ОПИСАНИИ ВАКАНСИЙ:"
    )
    for kw in DEFAULT_DESC_KEYWORDS:
        print(f"  - {kw}")

    if ask_yes_no("\nИспользовать эти слова для поиска в описании?"):
        return DEFAULT_DESC_KEYWORDS

    print(
        "\nВведи свои КЛЮЧЕВЫЕ СЛОВА ДЛЯ ОПИСАНИЯ (по одному, 'стоп' для завершения)."
    )
    words = []
    while True:
        w = input("  Ключевое слово: ").strip()
        if w.lower() == "стоп":
            break
        if w:
            words.append(w)
    return edit_list(words, "Ключевые слова для описания")


def select_professional_roles(target_phrases):
    roles = load_professional_roles()
    if not roles:
        print_error("Справочник ролей не загружен. Пропускаем выбор.")
        return []

    role_map = {r["id"]: r["name"] for r in roles}

    auto_ids = suggest_roles_by_keywords(target_phrases)
    if auto_ids:
        print_info("\nАвтоматически подобраны следующие роли:")
        for rid in auto_ids:
            print(f"  - {role_map.get(rid, 'Неизвестно')} (ID: {rid})")
        if ask_yes_no("\nИспользовать эти роли?"):
            return auto_ids

    print_info("\nРучной поиск ролей:")
    selected = set()
    while True:
        print_info("\n--- Выбранные роли ---")
        if not selected:
            print("  (список пуст)")
        else:
            for i, rid in enumerate(list(selected), 1):
                print(f"  {i}. {role_map.get(rid, 'Неизвестно')} (ID: {rid})")

        print("\nДействия:\n  [с] - Сохранить\n  [д] - Добавить\n  [у] - Удалить")
        ans = input("Твой выбор (с/д/у): ").strip().lower()

        if ans == "с":
            break
        elif ans == "д":
            query = input("Поиск ролей (часть названия): ").strip().lower()
            if query:
                filtered = [r for r in roles if query in r["name"].lower()]
                if not filtered:
                    print("Ничего не найдено.")
                    continue
                unique_filtered = list({r["id"]: r for r in filtered}.values())
                print(f"\nРезультаты поиска '{query}':")
                for i, r in enumerate(unique_filtered, 1):
                    print(f"  {i}. {r['name']} (ID: {r['id']})")
                choices = input("Введи номера (через запятую): ").strip()
                if choices:
                    for c in choices.split(","):
                        try:
                            idx = int(c.strip()) - 1
                            if 0 <= idx < len(unique_filtered):
                                selected.add(unique_filtered[idx]["id"])
                        except ValueError:
                            pass
        elif ans == "у":
            if not selected:
                continue
            try:
                idx = int(input("Номер для удаления: ")) - 1
                selected_list = list(selected)
                if 0 <= idx < len(selected_list):
                    selected.remove(selected_list[idx])
            except ValueError:
                print_error("Введи число.")
        else:
            print_error("Неизвестная команда.")
    return sorted(list(selected))


def ask_experiences():
    print(
        "\nОпыт работы (можно несколько, через запятую):\n  1. Нет опыта\n  2. От 1 года до 3 лет\n  3. От 3 до 6 лет\n  4. Более 6 лет"
    )
    choices = ask_list("  Номера")
    exp_map = {
        "1": "noExperience",
        "2": "between1And3",
        "3": "between3And6",
        "4": "moreThan6",
    }
    result = [exp_map[c] for c in choices if c in exp_map]
    return result if result else ["between1And3"]


def ask_periods():
    print(
        "\nПериод публикации (можно несколько):\n  1. Сегодня\n  2. За 3 дня\n  3. За неделю\n  4. За месяц\n  5. Всё время"
    )
    choices = ask_list("  Номера")
    pmap = {"1": 1, "2": 3, "3": 7, "4": 30, "5": 0}
    result = [pmap[c] for c in choices if c in pmap]
    return result if result else [0]


def collect_queries():
    print_info("\n--- Настройка поисковых запросов ---")
    n = ask_int("Сколько запросов создать? ", default=1)
    queries = []
    for i in range(n):
        print(f"\n=== Запрос #{i+1} ===")
        name = input("Название запроса (например, 'Data Analyst'): ").strip()

        title_kws = ask_title_keywords()
        target_title = "|".join(title_kws) if title_kws else "аналитик"

        roles = select_professional_roles(title_kws)
        exclude_words = ask_exclude_words()
        core_keywords = ask_desc_keywords()
        experiences = ask_experiences()
        periods = ask_periods()

        queries.append(
            {
                "name": name or f"Запрос {i+1}",
                "professional_roles": roles,
                "target_title": target_title,
                "exclude_words": exclude_words,
                "core_keywords": core_keywords,
                "employments": ["full", "part", "project"],
                "work_formats": ["remote", "hybrid", "office"],
                "experiences": experiences,
                "periods": periods,
                "min_salary": 0,
                "only_with_salary": False,
            }
        )
    return queries


def main_menu():
    print("\n" + "=" * 70)
    print(" HH ASSISTANT: Настройка поиска")
    print("=" * 70)
    n_resumes = ask_int("Сколько резюме? ", default=1)
    resumes = []
    for i in range(n_resumes):
        print(f"\n--- Резюме #{i+1} ---")
        url = input("URL резюме: ").strip()
        queries = collect_queries()
        resumes.append({"url": url, "queries": queries})

    threshold = ask_int("\nПорог соответствия (65): ", default=65)
    config = {"resumes": resumes, "threshold": threshold, "auto_apply": False}

    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
    print_success("Конфиг сохранён.")


if __name__ == "__main__":
    main_menu()
