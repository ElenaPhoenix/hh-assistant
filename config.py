import uuid
from datetime import datetime

from roles_helper import suggest_roles_by_keywords, load_professional_roles
from ui_helper import (
    ask_yes_no,
    ask_choice,
    ask_int,
    print_success,
    print_error,
    print_info,
    print_warning,
    clear_screen,
)
from utils import load_config, save_config, DEFAULT_THRESHOLD

WF_RU = {"remote": "Удаленно", "hybrid": "Гибрид", "office": "Офис"}
EMP_RU = {"full": "Полная", "part": "Частичная", "project": "Проектная"}
EXP_RU = {
    "noExperience": "Нет опыта",
    "between1And3": "1-3 года",
    "between3And6": "3-6 лет",
    "moreThan6": "6+ лет",
}
PERIOD_RU = {
    0: "Все время",
    1: "Сегодня",
    3: "За 3 дня",
    7: "За неделю",
    30: "За месяц",
}


def _generate_query_id():
    ts = int(datetime.now().timestamp())
    suffix = uuid.uuid4().hex[:6]
    return f"q_{ts}_{suffix}"


def _is_name_unique(new_name, existing_names):
    return new_name.strip().lower() not in [n.strip().lower() for n in existing_names]


def _edit_selection(items, label, options=None, allow_empty=False):
    items = list(items or [])
    key_to_label = {k: l for k, l in (options or [])}

    while True:
        print_info(f"\n--- {label} ---")
        if items:
            for i, v in enumerate(items, 1):
                display = key_to_label.get(v, str(v)) if options else str(v)
                print(f"  {i}. {display}")
        else:
            print("  (пусто)")

        print("\nДействия:")
        print("  1. Добавить")
        print("  2. Изменить")
        print("  3. Удалить")
        print("  4. Продолжить (сохранить текущий список)")
        print("  0. Отменить редактирование запроса")

        ans = input("\nТвой выбор: ").strip()

        if ans == "0":
            return None

        elif ans == "1":
            if options:
                available = [(k, l) for k, l in options if k not in items]
                if not available:
                    print_info("Все доступные варианты уже выбраны.")
                    continue
                print("\nДоступные варианты:")
                for i, (k, l) in enumerate(available, 1):
                    print(f"  {i}. {l}")
                raw = input("Номера через запятую: ").strip()
                if not raw:
                    print_info("Ничего не добавлено.")
                    continue
                for c in raw.split(","):
                    c = c.strip()
                    if not c:
                        continue
                    try:
                        num = int(c) - 1
                    except ValueError:
                        print_error(f"Не число: {c}")
                        continue
                    if 0 <= num < len(available):
                        k, l = available[num]
                        if k not in items:
                            items.append(k)
                            print_success(f"Добавлено: {l}")
                    else:
                        print_error(f"Неверный номер: {c}")
            else:
                print("\nВводи по одному, после каждого - Enter.")
                print("'стоп' - закончить добавление.")
                while True:
                    w = input("  Значение: ").strip()
                    if w.lower() == "стоп":
                        break
                    if w:
                        items.append(w)
                        print_success(f"Добавлено: {w}")
                    else:
                        print_error("Пустое значение не добавлено.")

        elif ans == "2":
            if not items:
                print_error("Список пуст, изменять нечего.")
                continue
            try:
                idx = int(input(f"Номер для изменения (1-{len(items)}): ")) - 1
                if not (0 <= idx < len(items)):
                    print_error("Неверный номер.")
                    continue
                if options:
                    available = [
                        (k, l) for k, l in options if k == items[idx] or k not in items
                    ]
                    print("\nДоступные варианты:")
                    for i, (k, l) in enumerate(available, 1):
                        print(f"  {i}. {l}")
                    raw = input("Новый вариант (один номер): ").strip()
                    try:
                        num = int(raw) - 1
                        if 0 <= num < len(available):
                            items[idx] = available[num][0]
                            print_success(f"Изменено на: {available[num][1]}")
                        else:
                            print_error("Неверный номер.")
                    except ValueError:
                        print_error("Введи число.")
                else:
                    old = items[idx]
                    new = input(
                        f"Новое значение (было '{old}', пусто - оставить): "
                    ).strip()
                    if not new:
                        print_info("Изменение отменено.")
                    else:
                        items[idx] = new
                        print_success(f"Изменено на: {new}")
            except ValueError:
                print_error("Введи число.")

        elif ans == "3":
            if not items:
                print_error("Список пуст, удалять нечего.")
                continue
            try:
                idx = int(input(f"Номер для удаления (1-{len(items)}): ")) - 1
                if 0 <= idx < len(items):
                    removed = items.pop(idx)
                    display = (
                        key_to_label.get(removed, str(removed))
                        if options
                        else str(removed)
                    )
                    print_success(f"Удалено: {display}")
                else:
                    print_error("Неверный номер.")
            except ValueError:
                print_error("Введи число.")

        elif ans == "4":
            if not items and not allow_empty:
                print_error("Нужен хотя бы один вариант.")
                continue
            return items

        else:
            print_error("Введи 0, 1, 2, 3 или 4.")


def _ask_name(existing_names, existing_query):
    if existing_query and existing_query.get("name"):
        current_name = existing_query["name"]
        print(f"\nТекущее имя запроса: '{current_name}'")
        if not ask_yes_no("Изменить имя запроса?"):
            return current_name
        while True:
            new_name = input("Новое имя запроса (0 - оставить текущее): ").strip()
            if new_name == "0":
                print_info("Оставляю текущее имя.")
                return current_name
            if not new_name:
                print_error("Имя обязательно.")
                continue
            if not _is_name_unique(new_name, existing_names):
                print_error(f"Имя '{new_name}' уже используется.")
                continue
            return new_name
    while True:
        name = input("Название запроса (0 - отменить создание): ").strip()
        if name == "0":
            return None
        if not name:
            print_error("Название обязательно.")
            continue
        if not _is_name_unique(name, existing_names):
            print_error(f"Имя '{name}' уже используется.")
            continue
        return name


def _ask_title_keywords(existing_query):
    current = []
    if existing_query and existing_query.get("target_title"):
        current = [p for p in existing_query["target_title"].split("|") if p]
    result = _edit_selection(
        current, "Слова для поиска в названии вакансии", allow_empty=False
    )
    if result is None:
        return None
    return "|".join(result)


def _ask_exclude_words(existing_query):
    current = []
    if existing_query and existing_query.get("exclude_words"):
        current = list(existing_query["exclude_words"])
    return _edit_selection(
        current,
        "Слова-исключения (если в тексте - вакансия отсеивается)",
        allow_empty=True,
    )


def _ask_desc_keywords(existing_query):
    current = []
    if existing_query and existing_query.get("core_keywords"):
        current = list(existing_query["core_keywords"])
    return _edit_selection(
        current,
        "Ключевые слова для поиска в описании вакансии",
        allow_empty=False,
    )


def _ask_employments(existing_query):
    current = []
    if existing_query and existing_query.get("employments"):
        current = list(existing_query["employments"])
    options = [("full", "Полная"), ("part", "Частичная"), ("project", "Проектная")]
    return _edit_selection(current, "Вид занятости", options=options, allow_empty=False)


def _ask_work_formats(existing_query):
    current = []
    if existing_query and existing_query.get("work_formats"):
        current = list(existing_query["work_formats"])
    options = [("remote", "Удаленно"), ("hybrid", "Гибрид"), ("office", "Офис")]
    return _edit_selection(current, "Формат работы", options=options, allow_empty=False)


def _ask_experiences(existing_query):
    current = []
    if existing_query and existing_query.get("experiences"):
        current = list(existing_query["experiences"])
    options = [
        ("noExperience", "Нет опыта"),
        ("between1And3", "1-3 года"),
        ("between3And6", "3-6 лет"),
        ("moreThan6", "6+ лет"),
    ]
    return _edit_selection(
        current, "Требуемый опыт работы", options=options, allow_empty=False
    )


def _ask_periods(existing_query):
    current = []
    if existing_query and existing_query.get("periods"):
        current = list(existing_query["periods"])
    options = [
        (1, "Сегодня"),
        (3, "За 3 дня"),
        (7, "За неделю"),
        (30, "За месяц"),
        (0, "Все время"),
    ]
    return _edit_selection(
        current, "Период публикации", options=options, allow_empty=False
    )


def _ask_roles(target_title, existing_query):
    current = None
    if existing_query and existing_query.get("professional_roles"):
        current = list(existing_query["professional_roles"])
    result = _select_professional_roles(target_title.split("|"), current=current)
    if result is None:
        if current:
            print_info("Отмена: оставляю текущие роли.")
            return current
        return None
    return result


def _ask_salary(existing_query):
    current_min = 0
    if existing_query and "min_salary" in existing_query:
        current_min = existing_query.get("min_salary", 0)

    print()
    print("НАСТРОЙКА ФИЛЬТРА ПО ЗАРПЛАТЕ:")
    cur_label = "не задана" if current_min <= 0 else str(current_min)
    print(f"  Текущий минимум: {cur_label}")

    mode = ask_choice(
        "Выбери режим фильтра по зарплате:",
        [
            (
                "none",
                "Не фильтровать по зарплате",
                "Попадут вакансии с любым размером зарплаты и без указания зарплаты",
            ),
            (
                "amount",
                "Указать минимальную зарплату",
                "Попадут вакансии с зарплатой от указанной суммы и без указания зарплаты",
            ),
        ],
        allow_cancel=True,
    )
    if mode is None:
        if existing_query and "min_salary" in existing_query:
            print_info("Отмена: оставляю текущие настройки зарплаты.")
            return current_min, False
        return None
    if mode == "none":
        print_info("Фильтр по зарплате отключен.")
        return 0, False

    min_salary = ask_int(
        "Минимальная зарплата (только цифры > 0, 0 - отмена): ",
        allow_cancel=True,
        min_value=1,
    )
    if min_salary is None:
        if existing_query and "min_salary" in existing_query:
            print_info("Отмена: оставляю текущие настройки зарплаты.")
            return current_min, False
        return None

    print_success(f"Минимальная зарплата: {min_salary}")
    print_info(f"Попадут вакансии без зарплаты И с зарплатой от {min_salary} и выше.")
    return min_salary, False


def _select_professional_roles(target_phrases, current=None):
    roles = load_professional_roles()
    if not roles:
        print_error("Справочник ролей не загружен.")
        return current or []
    role_map = {r["id"]: r["name"] for r in roles}

    if current:
        print(f"\nТекущие роли ({len(current)}):")
        for i, rid in enumerate(current, 1):
            print(f"  {i}. {role_map.get(rid, f'код {rid}')}")
        print()
        if ask_yes_no("Оставить текущие роли?"):
            return list(current)

    auto_ids = suggest_roles_by_keywords(target_phrases)
    if auto_ids:
        print_info("\nАвтоматически подобраны роли:")
        for rid in auto_ids:
            print(f"  - {role_map.get(rid, f'код {rid}')}")
        print()
        if ask_yes_no("Использовать?"):
            return auto_ids

    print_info("\nРучной поиск ролей:")
    selected = set()
    while True:
        print_info(f"\nВыбрано: {len(selected)} ролей")
        print("Действия: 1 - добавить, 2 - удалить, 3 - сохранить, 0 - отмена")
        ans = input("Твой выбор: ").strip()
        if ans == "0":
            return None
        if ans == "3":
            break
        if ans == "1":
            query = input("Поиск: ").strip().lower()
            if query:
                filtered = [r for r in roles if query in r["name"].lower()]
                if not filtered:
                    print("Ничего не найдено.")
                    continue
                uniq = list({r["id"]: r for r in filtered}.values())
                print(f"\nРезультаты '{query}':")
                for i, r in enumerate(uniq, 1):
                    print(f"  {i}. {r['name']}")
                nums = input("Номера через запятую: ").strip()
                for c in nums.split(","):
                    try:
                        idx = int(c.strip()) - 1
                        if 0 <= idx < len(uniq):
                            selected.add(uniq[idx]["id"])
                    except ValueError:
                        pass
        elif ans == "2":
            if not selected:
                continue
            sl = list(selected)
            for i, rid in enumerate(sl, 1):
                print(f"  {i}. {role_map.get(rid, f'код {rid}')}")
            try:
                idx = int(input("Номер для удаления: ")) - 1
                if 0 <= idx < len(sl):
                    selected.remove(sl[idx])
            except ValueError:
                print_error("Введи число.")
        else:
            print_error("Введи 0, 1, 2 или 3.")
    return sorted(selected)


def _show_progress(collected):
    print_info("\n--- Промежуточный итог запроса ---")
    if "name" in collected:
        print(f"  Название: {collected['name']}")
    if "target_title" in collected:
        print(f"  Слова в названии: {collected['target_title']}")
    if "professional_roles" in collected:
        print(f"  Профессиональные роли: {len(collected['professional_roles'])} шт.")
    if "exclude_words" in collected:
        print(f"  Слова-исключения: {len(collected['exclude_words'])} шт.")
    if "core_keywords" in collected:
        print(f"  Ключевые слова: {len(collected['core_keywords'])} шт.")
    if "employments" in collected:
        print(
            f"  Занятость: "
            f"{', '.join(EMP_RU.get(c, c) for c in collected['employments'])}"
        )
    if "work_formats" in collected:
        print(
            f"  Форматы: "
            f"{', '.join(WF_RU.get(c, c) for c in collected['work_formats'])}"
        )
    if "experiences" in collected:
        print(
            f"  Опыт: "
            f"{', '.join(EXP_RU.get(c, c) for c in collected['experiences'])}"
        )
    if "periods" in collected:
        periods_ru = ", ".join(PERIOD_RU.get(p, str(p)) for p in collected["periods"])
        print(f"  Периоды: {periods_ru}")
    if "min_salary" in collected:
        ms = collected["min_salary"]
        if ms <= 0:
            print(f"  Зарплата: не задана")
        else:
            print(f"  Зарплата: от {ms} и выше")
    print()


def _collect_query_answers(existing_names, existing_query=None):
    is_edit = existing_query is not None
    collected = {}

    if is_edit:
        print_warning(
            "\nВНИМАНИЕ: изменения конфига запроса приведут к полному\n"
            "пересчету всех вакансий для этого запроса при следующем\n"
            "запуске оценки (пункт 3, ~3-5 сек)."
        )

    collected["name"] = _ask_name(existing_names, existing_query)
    if collected["name"] is None:
        return None

    if is_edit and existing_query.get("id"):
        collected["id"] = existing_query["id"]
    else:
        collected["id"] = _generate_query_id()
    print_info(f"Код запроса: {collected['id']}")
    _show_progress(collected)

    collected["target_title"] = _ask_title_keywords(existing_query)
    if collected["target_title"] is None:
        return None
    _show_progress(collected)

    collected["professional_roles"] = _ask_roles(
        collected["target_title"], existing_query
    )
    if collected["professional_roles"] is None:
        return None
    _show_progress(collected)

    collected["exclude_words"] = _ask_exclude_words(existing_query)
    if collected["exclude_words"] is None:
        return None
    _show_progress(collected)

    collected["core_keywords"] = _ask_desc_keywords(existing_query)
    if collected["core_keywords"] is None:
        return None
    _show_progress(collected)

    collected["employments"] = _ask_employments(existing_query)
    if collected["employments"] is None:
        return None
    _show_progress(collected)

    collected["work_formats"] = _ask_work_formats(existing_query)
    if collected["work_formats"] is None:
        return None
    _show_progress(collected)

    collected["experiences"] = _ask_experiences(existing_query)
    if collected["experiences"] is None:
        return None
    _show_progress(collected)

    collected["periods"] = _ask_periods(existing_query)
    if collected["periods"] is None:
        return None
    _show_progress(collected)

    salary_result = _ask_salary(existing_query)
    if salary_result is None:
        return None
    collected["min_salary"], collected["only_with_salary"] = salary_result
    _show_progress(collected)

    print("\n" + "=" * 60)
    print("ИТОГОВЫЙ ЗАПРОС:")
    print(f"  Название: {collected['name']}")
    print(f"  Код запроса: {collected['id']}")
    print(f"  Слова в названии: {collected['target_title']}")
    print(f"  Профессиональные роли: {len(collected['professional_roles'])} шт.")
    print(f"  Слова-исключения: {len(collected['exclude_words'])} шт.")
    print(f"  Ключевые слова: {len(collected['core_keywords'])} шт.")
    print(
        f"  Занятость: "
        f"{', '.join(EMP_RU.get(c, c) for c in collected['employments'])}"
    )
    print(
        f"  Форматы: "
        f"{', '.join(WF_RU.get(c, c) for c in collected['work_formats'])}"
    )
    print(
        f"  Опыт: " f"{', '.join(EXP_RU.get(c, c) for c in collected['experiences'])}"
    )
    periods_ru = ", ".join(PERIOD_RU.get(p, str(p)) for p in collected["periods"])
    print(f"  Периоды: {periods_ru}")
    ms = collected["min_salary"]
    if ms <= 0:
        print(f"  Зарплата: не задана")
    else:
        print(f"  Зарплата: от {ms} и выше")
    print("=" * 60)
    print()
    if not ask_yes_no("Сохранить этот запрос?"):
        return None

    return collected


def _find_resume_by_url(config, url):
    for r_idx, r in enumerate(config["resumes"]):
        if r.get("url", "").strip() == url.strip():
            return r_idx
    return None


def _select_existing_query(config):
    options = []
    for r_idx, resume in enumerate(config["resumes"]):
        url = resume.get("url", "")
        tail = url[-30:] if len(url) > 30 else url
        for q_idx, q in enumerate(resume.get("queries", [])):
            label = f"Резюме ...{tail} | {q.get('name', '')}"
            options.append((f"{r_idx}:{q_idx}", label, ""))
    if not options:
        print_error("В конфиге нет запросов.")
        return None
    choice = ask_choice("Выбери запрос:", options, allow_cancel=True)
    if choice is None:
        return None
    r_str, q_str = choice.split(":")
    return int(r_str), int(q_str)


def _action_add_query(config):
    print_info("\n--- Добавление нового запроса ---")
    print("Сначала укажи URL резюме. Если такое резюме уже есть в конфиге -")
    print("новый запрос добавится к нему. Если нет - резюме создастся.")
    print("(0 - отмена)")

    while True:
        url = input("URL резюме: ").strip()
        if url == "0":
            return False
        if not url:
            print_error("URL не может быть пустым.")
            continue
        if "/resume/" not in url:
            print_error("URL должен содержать /resume/")
            continue
        break

    existing_r_idx = _find_resume_by_url(config, url)
    if existing_r_idx is not None:
        resume = config["resumes"][existing_r_idx]
        print_info(
            f"Найдено существующее резюме. Запросов: "
            f"{len(resume.get('queries', []))}"
        )
    else:
        resume = {"url": url, "queries": []}
        config["resumes"].append(resume)
        existing_r_idx = len(config["resumes"]) - 1
        print_info("Резюме добавлено (пока без запросов).")

    existing_names = [q.get("name", "") for q in resume.get("queries", [])]
    new_q = _collect_query_answers(existing_names, existing_query=None)

    if new_q is None:
        print_error("Добавление запроса отменено.")
        if not resume["queries"] and existing_r_idx == len(config["resumes"]) - 1:
            config["resumes"].pop(existing_r_idx)
            print_info("Пустое резюме удалено из конфига.")
        return False

    resume["queries"].append(new_q)
    print_success(f"Запрос '{new_q['name']}' добавлен.")
    return True


def _action_edit_query(config):
    if not config["resumes"]:
        print_error("Нет запросов для изменения.")
        return False
    target = _select_existing_query(config)
    if target is None:
        return False
    r_idx, q_idx = target
    resume = config["resumes"][r_idx]
    old_query = resume["queries"][q_idx]

    other_names = [
        q.get("name", "") for i, q in enumerate(resume["queries"]) if i != q_idx
    ]
    new_query = _collect_query_answers(other_names, existing_query=old_query)
    if new_query is None:
        print_error("Изменение отменено.")
        return False
    resume["queries"][q_idx] = new_query
    print_success(f"Запрос '{new_query['name']}' сохранен.")
    return True


def _action_delete_query(config):
    if not config["resumes"]:
        print_error("Нет запросов для удаления.")
        return False
    target = _select_existing_query(config)
    if target is None:
        return False
    r_idx, q_idx = target
    resume = config["resumes"][r_idx]
    qname = resume["queries"][q_idx].get("name", "")
    if not ask_yes_no(f"Удалить запрос '{qname}'?"):
        return False

    resume["queries"].pop(q_idx)
    print_success("Запрос удален из конфига.")
    print_info(
        "Связанные данные будут очищены при следующем запуске оценки " "(пункт 3)."
    )

    if not resume["queries"]:
        if ask_yes_no("У резюме не осталось запросов. Удалить резюме?"):
            config["resumes"].pop(r_idx)
            print_success("Резюме удалено из конфига.")

    total_q = sum(len(r.get("queries", [])) for r in config["resumes"])
    if total_q == 0:
        print_warning(
            "\nВНИМАНИЕ: в конфиге больше нет запросов.\n"
            "Пункты 2-5 (сбор, оценка, отклики, тесты) не смогут работать.\n"
            "Добавьте хотя бы один запрос."
        )
    return True


def _action_change_threshold(config):
    current = config.get("threshold", DEFAULT_THRESHOLD)
    print(f"\nПорог соответствия: {current}%")
    print("Вакансии с оценкой ниже порога не попадут в подходящие.")
    print("ВАЖНО: изменение порога приведет к пересчету ВСЕХ запросов")
    print("при следующем запуске оценки (пункт 3).")
    val = ask_int(
        "Новый порог (1-100, 0 - отмена): ",
        allow_cancel=True,
        min_value=1,
        max_value=100,
    )
    if val is None or val == current:
        return False
    config["threshold"] = val
    print_success(f"Порог изменен на {val}%.")
    return True


def _list_queries_for_display(config):
    idx = 1
    for r_idx, r in enumerate(config["resumes"]):
        url = r.get("url", "")
        tail = url[-30:] if len(url) > 30 else url
        for q_idx, q in enumerate(r.get("queries", [])):
            qname = q.get("name", "Без имени")
            print(f"  [{idx}] Резюме ...{tail}")
            print(f"      Запрос: {qname}")
            idx += 1


def main_menu():
    config = load_config()
    dirty = False

    total_q = sum(len(r.get("queries", [])) for r in config["resumes"])
    print_info(
        f"Загружено: резюме {len(config['resumes'])}, запросов {total_q}, "
        f"порог соответствия {config.get('threshold', DEFAULT_THRESHOLD)}%."
    )

    while True:
        clear_screen()
        print("=" * 70)
        print(" НАСТРОЙКА ПОИСКА ВАКАНСИЙ")
        print("=" * 70)

        if config["resumes"]:
            print("\nСохраненные запросы:")
            _list_queries_for_display(config)
        else:
            print("\n(нет сохраненных запросов)")

        print(f"\nПорог соответствия: {config.get('threshold', DEFAULT_THRESHOLD)}%")
        if dirty:
            print_warning("\n  * Есть несохраненные изменения")

        options = []
        if config["resumes"]:
            options.append(
                (
                    "edit",
                    "Изменить существующий запрос",
                    "Редактировать параметры одного из сохраненных запросов",
                )
            )
        options.append(
            (
                "add",
                "Добавить новый запрос",
                "Создать запрос для существующего или нового резюме",
            )
        )
        if config["resumes"]:
            options.append(
                ("delete", "Удалить запрос", "Удалить сохраненный запрос из конфига")
            )
        options.append(
            (
                "threshold",
                "Изменить порог соответствия",
                "Вакансии с оценкой ниже порога не попадут в подходящие",
            )
        )
        options.append(
            ("save", "Сохранить и выйти", "Записать изменения в конфиг и настройки")
        )

        choice = ask_choice(
            "Выбери действие:",
            options,
            allow_cancel=True,
            cancel_label="Выйти без сохранения",
        )

        if choice is None:
            if dirty and not ask_yes_no(
                "Есть несохраненные изменения. Выйти без сохранения?"
            ):
                continue
            print("Выход без сохранения.")
            return
        elif choice == "save":
            try:
                save_config(config)
                print_success("Конфиг и настройки сохранены.")
                return
            except Exception as e:
                print_error(f"Ошибка сохранения: {e}")
                continue
        elif choice == "add":
            if _action_add_query(config):
                dirty = True
        elif choice == "edit":
            if _action_edit_query(config):
                dirty = True
        elif choice == "delete":
            if _action_delete_query(config):
                dirty = True
        elif choice == "threshold":
            if _action_change_threshold(config):
                dirty = True


if __name__ == "__main__":
    main_menu()
