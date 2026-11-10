import json
import os
import re
import sys
from datetime import datetime, time, timedelta

from logger import log
from utils import (
    load_vacancies,
    save_vacancies,
    load_config,
    atomic_write_json,
    MATCHES_DIR,
    query_key,
)
from state_helper import load_state, save_state
from db import db_cursor
from ui_helper import (
    ask_yes_no,
    ask_choice,
    print_success,
    print_error,
    print_info,
    print_warning,
)

_DATE_RE = re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})")


def _safe_int(value):
    """Приводит значение к int, возвращает None если не получается."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_period_input(raw):
    """Разбирает ввод пользователя: одна или две даты.

    Возвращает (status, d1, d2):
      status="ok"     - d1 задана; d2 = None (одна дата) или datetime (две)
      status="cancel" - введено 0
      status="error"  - не удалось разобрать

    Формат дат: ГГГГ-М-Д или ГГГГ-ММ-ДД (гибко к ведущим нулям).
    Если дат две - порядок нормализуется (старая, новая).
    """
    raw = (raw or "").strip()
    if raw == "0":
        return "cancel", None, None

    matches = _DATE_RE.findall(raw)
    if not matches or len(matches) > 2:
        return "error", None, None

    dates = []
    for y, m, d in matches:
        try:
            dates.append(datetime(int(y), int(m), int(d)))
        except ValueError:
            return "error", None, None

    if len(dates) == 1:
        return "ok", dates[0], None

    dates.sort()
    return "ok", dates[0], dates[1]


def _action_clear_all():
    print_warning("\nВНИМАНИЕ: будут удалены ВСЕ вакансии.")
    print()
    print("Что удалится:")
    print("  - все собранные вакансии")
    print("  - все отклики и переписки из базы данных")
    print()
    print("Что останется:")
    print("  - история откликов, отказов и тестов")
    print("  - отправленные письма")
    print()
    if not ask_yes_no("Удалить все вакансии?", allow_cancel=True):
        return

    print_info("Удаляю из базы данных...")
    try:
        with db_cursor() as cur:
            cur.execute("DELETE FROM messages;")
            cur.execute("DELETE FROM negotiations;")
            cur.execute("DELETE FROM vacancies;")
        print_success("База данных очищена.")
    except Exception as e:
        print_error(
            "Не удалось очистить базу данных. "
            "Проверьте, что PostgreSQL запущен. Подробности в data/app.log."
        )
        log.error(f"vacancy_cleanup: DB clear error: {e}")
        print_info("Собранные вакансии не тронуты.")
        return

    print_info("Удаляю собранные вакансии...")
    save_vacancies({})
    print_success("Собранные вакансии удалены.")
    log.info("vacancy_cleanup: полная очистка выполнена")


def _collect_pub_dates(vacancies):
    """Собирает даты публикации. Возвращает (list_of_date, no_date_count)."""
    dates = []
    no_date = 0
    for v in vacancies.values():
        pub = v.get("published_at")
        if not pub:
            no_date += 1
            continue
        try:
            pub_dt = datetime.fromisoformat(pub.replace("Z", "+00:00"))
            dates.append(pub_dt.replace(tzinfo=None).date())
        except Exception:
            no_date += 1
    return dates, no_date


def _action_clear_period():
    vacancies = load_vacancies()
    if not vacancies:
        print_info("Собранных вакансий нет.")
        return

    print_info("\nУдаление вакансий за период")
    print()
    print("Будут удалены собранные вакансии, опубликованные в указанном")
    print("периоде. Обе границы включаются: вакансия, опубликованная")
    print("ровно в день начала или ровно в день окончания, тоже удалится.")
    print("В базе данных вакансия останется для истории откликов.")
    print()
    print("Как вводить даты:")
    print("  Одна дата:  2026-01-15")
    print("              программа спросит, за какой период удалять")
    print("  Две даты:   2026-01-15 2026-02-20")
    print("              удалятся вакансии за этот период (включительно)")
    print()
    print("Формат: ГГГГ-ММ-ДД. Порядок дат не важен.")
    print("(0 - отмена)")
    print()

    while True:
        raw = input("Даты (например: 2026-01-15 2026-02-20): ").strip()
        status, d1, d2 = _parse_period_input(raw)
        if status == "cancel":
            return
        if status == "error":
            print_error(
                "Не удалось разобрать даты. Введи одну или две даты "
                "в формате ГГГГ-ММ-ДД."
            )
            continue
        break

    if d2 is None:
        target = d1.date()
        target_str = target.strftime("%Y-%m-%d")
        choice = ask_choice(
            f"Что удалить за {target_str}?",
            [
                (
                    "day",
                    f"Только за {target_str}",
                    "Удалятся вакансии, опубликованные именно в этот день.",
                ),
                (
                    "until_new",
                    f"С {target_str} до самой свежей вакансии в базе",
                    "Удалятся вакансии с этой даты по дату самой новой\n"
                    "вакансии в базе (обе даты включительно).",
                ),
                (
                    "until_old",
                    f"От самой старой вакансии в базе до {target_str}",
                    "Удалятся вакансии с даты самой старой вакансии\n"
                    "в базе по эту дату (обе даты включительно).",
                ),
            ],
            allow_cancel=True,
        )
        if choice is None:
            return

        if choice == "day":
            from_d = to_d = target
        else:
            pub_dates, _ = _collect_pub_dates(vacancies)
            if not pub_dates:
                print_info("В базе нет вакансий с датами публикации.")
                return
            if choice == "until_new":
                from_d, to_d = target, max(pub_dates)
            else:  # until_old
                from_d, to_d = min(pub_dates), target

        if from_d > to_d:
            print_info(f"За указанный период ({target_str}) вакансий нет.")
            return
    else:
        from_d = d1.date()
        to_d = d2.date()

    if from_d == to_d:
        period_str = f"{from_d.strftime('%Y-%m-%d')} (один день)"
    else:
        period_str = (
            f"с {from_d.strftime('%Y-%m-%d')} "
            f"по {to_d.strftime('%Y-%m-%d')} (обе даты включительно)"
        )

    # Полуоткрытый интервал: [from_d 00:00:00, (to_d + 1 день) 00:00:00).
    # Включает все вакансии за день to_d, вплоть до 23:59:59.999999.
    from_dt_start = datetime.combine(from_d, time.min)
    to_dt_end_exclusive = datetime.combine(to_d + timedelta(days=1), time.min)

    to_remove = []
    no_date = 0
    for vid, v in vacancies.items():
        pub = v.get("published_at")
        if not pub:
            no_date += 1
            continue
        try:
            pub_dt = datetime.fromisoformat(pub.replace("Z", "+00:00"))
            pub_dt_naive = pub_dt.replace(tzinfo=None)
            if from_dt_start <= pub_dt_naive < to_dt_end_exclusive:
                to_remove.append(vid)
        except Exception:
            no_date += 1
            continue

    print()
    print(f"Период: {period_str}")
    if no_date:
        print_warning(
            f"Вакансий без даты публикации: {no_date}. Они не будут затронуты."
        )
    if not to_remove:
        print_info("В указанном периоде ничего не найдено.")
        return

    print_info(f"Будет удалено вакансий: {len(to_remove)}")
    print()
    if not ask_yes_no("Удалить их?", allow_cancel=True):
        return

    for vid in to_remove:
        vacancies.pop(vid, None)
    save_vacancies(vacancies)

    print_success(f"Удалено: {len(to_remove)}.")
    log.info(f"vacancy_cleanup: удалено за период ({period_str}): {len(to_remove)}")


def _action_clear_orphans():
    """Убирает из истории вакансии, которых нет в собранных.

    НЕ трогает:
      - отправленные письма (это исторический лог)
      - таблицы PostgreSQL (там связи от откликов и сообщений)
    """
    vacancies = load_vacancies()
    valid_ids = set(vacancies.keys())

    if not valid_ids:
        print_warning(
            "Собранных вакансий нет. Если очистить историю сейчас, "
            "все отклики, отказы, тесты и проверенные вакансии будут забыты. "
            "Это, скорее всего, не то, что нужно."
        )
        if not ask_yes_no("Продолжить?", allow_cancel=True):
            return

    print_info(f"Собрано вакансий: {len(valid_ids)}")
    print_info("Ищу устаревшие записи в истории...")
    print()

    state = load_state()
    total_state_removed = 0
    for rid, rs in state.get("resumes", {}).items():
        processed = rs.get("processed_vacancy_ids", {}) or {}
        for qid in list(processed.keys()):
            before = len(processed[qid])
            processed[qid] = [
                vid for vid in processed[qid] if _safe_int(vid) in valid_ids
            ]
            total_state_removed += before - len(processed[qid])

        for key in ("applied_vacancy_ids", "denied_vacancy_ids"):
            before = len(rs.get(key, []) or [])
            rs[key] = [
                vid for vid in (rs.get(key) or []) if _safe_int(vid) in valid_ids
            ]
            total_state_removed += before - len(rs[key])

        before_nt = len(rs.get("needs_test", []) or [])
        rs["needs_test"] = [
            item
            for item in (rs.get("needs_test") or [])
            if _safe_int(item.get("id")) in valid_ids
        ]
        total_state_removed += before_nt - len(rs["needs_test"])

    if total_state_removed:
        save_state(state)

    config = load_config()
    valid_qids = set()
    for r in config.get("resumes", []):
        for q in r.get("queries", []):
            valid_qids.add(query_key(q))

    total_matches_removed = 0
    if os.path.isdir(MATCHES_DIR):
        for fname in os.listdir(MATCHES_DIR):
            if not fname.endswith(".json"):
                continue
            path = os.path.join(MATCHES_DIR, fname)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                continue
            if not isinstance(data, dict):
                continue

            removed_here = 0
            for key in ("all", "passed"):
                items = data.get(key, [])
                if not isinstance(items, list):
                    continue
                before = len(items)
                items = [v for v in items if _safe_int(v.get("id")) in valid_ids]
                removed_here += before - len(items)
                data[key] = items

            hashes = data.get("query_hashes", {}) or {}
            orphan_hashes = [qid for qid in hashes if qid not in valid_qids]
            for qid in orphan_hashes:
                del hashes[qid]
            data["query_hashes"] = hashes

            if removed_here or orphan_hashes:
                atomic_write_json(path, data)
                total_matches_removed += removed_here

    total = total_state_removed + total_matches_removed
    if total == 0:
        print_success("Устаревших записей нет - все чисто.")
    else:
        print_success(f"Удалено устаревших записей: {total}.")
    log.info(
        f"vacancy_cleanup: очистка истории. "
        f"state={total_state_removed}, matches={total_matches_removed}, "
        f"valid_vacancies={len(valid_ids)}"
    )


def main():
    try:
        vacancies = load_vacancies()
        print_info("\n=== Очистка базы вакансий ===")
        print(f"Собрано вакансий: {len(vacancies)}")
        print()

        choice = ask_choice(
            "Выбери действие:",
            [
                (
                    "all",
                    "Удалить все вакансии",
                    "Все собранные вакансии и все отклики с переписками\n"
                    "будут удалены. История откликов, отказов и тестов\n"
                    "сохранится.",
                ),
                (
                    "period",
                    "Удалить за период",
                    "Удалить собранные вакансии, опубликованные в выбранном\n"
                    "периоде. В базе данных вакансия останется для истории\n"
                    "откликов.",
                ),
                (
                    "orphans",
                    "Удалить устаревшие записи",
                    "Убрать из списков откликов, отказов, тестов и проверенных\n"
                    "вакансии, которых больше нет среди собранных.\n"
                    "Полезно после полной очистки.",
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
        elif choice == "orphans":
            _action_clear_orphans()
    except KeyboardInterrupt:
        raise
    except Exception as e:
        log.exception(f"vacancy_cleanup: критическая ошибка: {e}")
        print_error("Критическая ошибка. Подробности в data/app.log.")
        sys.exit(1)


if __name__ == "__main__":
    main()
