from datetime import datetime

from logger import log
from utils import load_vacancies, save_vacancies
from db import db_cursor
from ui_helper import (
    ask_yes_no,
    ask_choice,
    print_success,
    print_error,
    print_info,
    print_warning,
)


def _action_clear_all():
    print_warning("\nВНИМАНИЕ: удалит ВСЕ вакансии из локальной базы и БД.")
    print()
    print("Что БУДЕТ очищено:")
    print("  - локальный кэш вакансий")
    print("  - таблицы базы данных: вакансии, отклики, сообщения")
    print("  - прогресс проверки вакансий")
    print()
    print("Что НЕ БУДЕТ очищено:")
    print("  - результаты оценки вакансий")
    print("  - прогресс: отклики, отказы, тесты")
    print()
    if not ask_yes_no("Продолжить очистку вакансий?", allow_cancel=True):
        return
    print_info("Удаление локального кэша...")
    save_vacancies({})
    print_success("Локальный кэш вакансий очищен.")
    print_info("Удаление из базы данных...")
    try:
        with db_cursor() as cur:
            cur.execute("DELETE FROM messages;")
            cur.execute("DELETE FROM negotiations;")
            cur.execute("DELETE FROM vacancies;")
        print_success("Таблицы базы данных очищены.")
    except Exception as e:
        print_error(f"Ошибка БД: {e}")
        print_info("Локальный кэш уже пуст. Базу данных можно очистить отдельно.")
    log.info("vacancy_cleanup: полная очистка выполнена")


def _action_clear_period():
    vacancies = load_vacancies()
    if not vacancies:
        print_info("База пуста.")
        return

    print("\nВведи даты в формате ГГГГ-ММ-ДД (например 2026-10-01).")
    print("Будут удалены вакансии, опубликованные в этом диапазоне.")
    print("(0 - отмена)")
    while True:
        from_str = input("Дата начала: ").strip()
        if from_str == "0":
            return
        try:
            from_dt = datetime.strptime(from_str, "%Y-%m-%d")
            break
        except ValueError:
            print_error("Формат ГГГГ-ММ-ДД.")
    while True:
        to_str = input("Дата конца: ").strip()
        if to_str == "0":
            return
        try:
            to_dt = datetime.strptime(to_str, "%Y-%m-%d")
            break
        except ValueError:
            print_error("Формат ГГГГ-ММ-ДД.")
    if to_dt < from_dt:
        print_error("Дата конца раньше даты начала.")
        return

    to_remove = []
    no_date = 0
    for vid, v in vacancies.items():
        pub = v.get("published_at")
        if not pub:
            no_date += 1
            continue
        try:
            pub_dt = datetime.fromisoformat(pub.replace("Z", "+00:00"))
            if from_dt <= pub_dt.replace(tzinfo=None) <= to_dt:
                to_remove.append(vid)
        except Exception:
            no_date += 1
            continue

    if no_date:
        print_warning(
            f"Вакансий без даты публикации: {no_date} "
            "(собраны до обновления). Они не будут затронуты."
        )
    if not to_remove:
        print_info("В указанном периоде ничего не найдено.")
        return
    print_info(f"Найдено вакансий в периоде: {len(to_remove)}")
    print()
    if not ask_yes_no("Удалить их из локальной базы?", allow_cancel=True):
        return
    for vid in to_remove:
        vacancies.pop(vid, None)
    save_vacancies(vacancies)
    print_success(f"Удалено: {len(to_remove)}")
    log.info(
        f"vacancy_cleanup: удалено за период {from_str}..{to_str}: {len(to_remove)}"
    )


def main():
    vacancies = load_vacancies()
    print_info(f"\n=== Очистка базы вакансий ===")
    print(f"Текущий размер: {len(vacancies)} вакансий")
    print()
    print_info(
        "Примечание: архивные и удаленные вакансии автоматически\n"
        "чистятся из базы во время отправки откликов и других действий."
    )

    choice = ask_choice(
        "Выбери действие:",
        [
            (
                "all",
                "Очистить полностью",
                "Удалить все вакансии из локальной базы и БД\n"
                "Прогресс проверки тоже сбрасывается",
            ),
            (
                "period",
                "Удалить за период",
                "Удалить вакансии по дате публикации\n" "Спросит даты начала и конца",
            ),
        ],
        allow_cancel=True,
    )
    if choice is None:
        return

    if choice == "all":
        _action_clear_all()
    elif choice == "period":
        _action_clear_period()


if __name__ == "__main__":
    main()
