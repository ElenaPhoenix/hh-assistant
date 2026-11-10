import os
import re
import sys
import json
import base64
import subprocess
import webbrowser

from logger import log
from state_helper import (
    load_state,
    save_state,
    get_applied_ids,
    get_denied_ids,
    get_needs_test,
    add_applied_id,
    remove_needs_test,
    mark_denied,
    get_resume_state,
    reset_processed,
    reset_applied,
    reset_denied,
    reset_needs_test,
    reset_all,
)
from shared_api import TokenManager, generate_letter, hh_api, prompt_reauth
from utils import (
    load_config,
    load_resume,
    load_matches,
    load_vacancies,
    resume_id_from_url,
    query_key,
    remove_vacancies_from_cache,
    clear_query_hash,
    DATA_DIR,
    CONFIG_FILE,
    DEFAULT_THRESHOLD,
)
from dedupe import dedupe_passed
from ui_helper import (
    ask_yes_no,
    ask_choice,
    ask_int,
    pause,
    plural,
    print_success,
    print_error,
    print_warning,
    print_info,
    clear_screen,
)

MENU = """
╔══════════════════════════════════════════════════════════════════╗
║                    HH ASSISTANT - ГЛАВНОЕ МЕНЮ                   ║
╠══════════════════════════════════════════════════════════════════╣
║  1. Настроить поиск вакансий (редактировать запросы)             ║
║  2. Собрать новые вакансии с hh.ru                               ║
║  3. Оценить вакансии (загрузить резюме и оценить)                ║
║  4. Отправить отклики на подходящие вакансии                     ║
║  5. Пройти тесты (вакансии с обязательным тестом)                ║
║  6. Синхронизация с hh.ru (отклики и переписка)                  ║
║  7. Статистика (прогресс по текущему запросу)                    ║
║  8. Управление базой (сброс и очистка)                           ║
║  9. Сменить активный запрос                                      ║
║  0. Выход                                                        ║
╚══════════════════════════════════════════════════════════════════╝
"""

PHASE_RU = {
    "not_started": "не запускалось",
    "parsed": "резюме загружено",
    "matched": "вакансии оценены",
    "applying": "отправка откликов",
    "applied": "отклики отправлены",
}

_API_STATUS_RU = {
    "captcha": "требуется проверка на робота",
    "error": "ошибка на стороне hh.ru",
    "timeout": "hh.ru не ответил вовремя",
}


def run_script(script_name, *args):
    cmd = [sys.executable, script_name] + list(args)
    log.info(f"Запуск дочернего процесса: {' '.join(cmd)}")
    result = subprocess.run(cmd)
    if result.returncode != 0:
        log.error(f"Скрипт {script_name} завершился с кодом {result.returncode}")
    return result.returncode == 0


def _log_tool_version():
    try:
        from importlib.metadata import version, PackageNotFoundError

        try:
            v = version("hh-applicant-tool")
            log.info(f"hh-applicant-tool version: {v}")
        except PackageNotFoundError:
            log.warning("hh-applicant-tool не установлен")
    except Exception as e:
        log.warning(f"Не удалось определить версию hh-applicant-tool: {e}")


def _match_query_key(m):
    return m.get("query_id") or "default"


def _needs_test_query_key(t):
    return t.get("query_id") or "default"


def get_current_context(state, config):
    if not config.get("resumes"):
        return None, None, None
    r_idx = state.get("current_resume_index", 0)
    if r_idx >= len(config["resumes"]):
        r_idx = 0
    resume_url = config["resumes"][r_idx]["url"]
    resume_id = resume_id_from_url(resume_url)
    queries = config["resumes"][r_idx].get("queries", [])
    if not queries:
        return None, None, None
    current_qid = state.get("current_query_id")
    query = next((q for q in queries if query_key(q) == current_qid), queries[0])
    return r_idx, resume_id, query


def ensure_valid_context(state, config):
    r_idx, _, query = get_current_context(state, config)
    if r_idx is None:
        return
    state["current_resume_index"] = r_idx
    state["current_query_id"] = query_key(query)
    save_state(state)


def copy_to_clipboard(text):
    try:
        b64 = base64.b64encode(text.encode("utf-8")).decode("ascii")
        ps_command = (
            f"$bytes = [Convert]::FromBase64String('{b64}'); "
            f"$text = [Text.Encoding]::UTF8.GetString($bytes); "
            f"Set-Clipboard -Value $text"
        )
        return (
            subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_command],
                capture_output=True,
                timeout=15,
            ).returncode
            == 0
        )
    except Exception:
        return False


def _remove_dead_vacancy(state, resume_id, vid, reason):
    mark_denied(state, resume_id, vid)
    removed = remove_vacancies_from_cache([vid])
    log.info(f"Тест: вакансия {vid} удалена ({reason}); из кэша: {removed}")


def _fetch_vacancy_for_test(vid, state, resume_id):
    while True:
        status, data = hh_api(f"/vacancies/{vid}", max_captcha_retries=1)

        if status == "auth_required":
            print_warning("Сессия hh истекла.")
            if not prompt_reauth():
                return "exit", None
            continue

        if status == "ok" and isinstance(data, dict):
            if data.get("archived") or data.get("closed_for_applicants"):
                print_warning("Вакансия в архиве или закрыта. Убираю из базы.")
                _remove_dead_vacancy(state, resume_id, vid, "archived_or_closed")
                return "deleted", None
            return "ok", data

        err_raw = str(data or "")
        err_low = err_raw.lower()
        log.warning(
            f"Тест: GET /vacancies/{vid} -> status={status}, data={err_raw[:500]}"
        )

        is_dead = (
            re.search(r"\b404\b", err_low)
            or "not_found" in err_low
            or "not found" in err_low
            or "vacancy_not_found" in err_low
            or "vacancy not found" in err_low
            or "vacancy is archived" in err_low
            or "vacancy is closed" in err_low
            or "does not exist" in err_low
        )
        if status == "error" and is_dead:
            print_warning("Вакансия недоступна на hh. Убираю из базы.")
            _remove_dead_vacancy(state, resume_id, vid, "not_found")
            return "deleted", None

        reason = _API_STATUS_RU.get(status, "неизвестная ошибка")
        print_error(f"Не удалось загрузить вакансию: {reason}.")
        choice = ask_choice(
            "Что делать?",
            [("retry", "Повторить загрузку", "Запросить вакансию с hh еще раз")],
            allow_cancel=True,
            cancel_label="Выйти из обработки",
        )
        if choice is None:
            return "exit", None


def _parse_test_numbers(raw_input, max_val):
    parts = re.split(r"[,;\s]+", raw_input.strip())
    valid, invalid = [], []
    for part in parts:
        if not part:
            continue
        try:
            num = int(part)
            if 1 <= num <= max_val:
                valid.append(num)
            else:
                invalid.append(part)
        except ValueError:
            invalid.append(part)
    return valid, invalid


def menu_configure():
    print_info("\n=== Настройка поиска ===")
    run_script("config.py")
    pause()


def menu_collect_vacancies():
    print_info("\n=== Сбор вакансий с hh.ru ===")
    run_script("vacancy_search.py")
    pause()


def menu_process_resume():
    print_info("\n=== Оценка вакансий ===")
    state, config = load_state(), load_config()
    r_idx, resume_id, query = get_current_context(state, config)
    if r_idx is None:
        return
    print_info(f"Текущий запрос: {query['name']}")
    resume_data = load_resume(resume_id)
    need_parse = (
        not resume_data
        or not resume_data.get("city_id")
        or not resume_data.get("full_text")
        or not (resume_data.get("candidate_name") or "").strip()
    )
    if need_parse:
        print_info("Загружаем резюме...")
        if not run_script("resume_parser.py", "--index", str(r_idx)):
            print_error("Ошибка загрузки резюме. Смотрите data/app.log.")
            pause()
            return

    if not run_script("matcher.py", "--index", str(r_idx)):
        print_error("Ошибка оценки вакансий. Смотрите data/app.log.")
        pause()
        return
    pause()


def menu_send_applications():
    print_info("\n=== Отправка откликов ===")
    state, config = load_state(), load_config()
    r_idx, _, query = get_current_context(state, config)
    if r_idx is None:
        return
    print_info(f"Текущий запрос: {query['name']}")
    run_script("apply_via_api.py")
    pause()


def _show_test_vacancies(vacancies):
    for i, v in enumerate(vacancies, 1):
        employer = v.get("employer") or "Не указан"
        print(f"  {i}. {v['name']}")
        print(f"     {employer} | {v['match_score']}%")
        if v.get("link"):
            print(f"     {v['link']}")
        print()


def _process_single_test(
    state,
    resume_id,
    vacancy,
    resume_data,
    candidate_name,
    portfolio_url=None,
):
    vid = vacancy["id"]

    print()
    print(f"Вакансия: {vacancy['name']}")
    print(f"Работодатель: {vacancy.get('employer', 'Не указан')}")
    print(f"Соответствие: {vacancy['match_score']}%")
    print()

    print("Загружаю описание вакансии...")
    fetch_status, full_vacancy = _fetch_vacancy_for_test(vid, state, resume_id)
    if fetch_status == "exit":
        return "exit"
    if fetch_status == "deleted":
        print_info("Вакансия убрана из списка.")
        return "failed"

    print("Создаю письмо...")
    try:
        token_mgr = TokenManager()
    except Exception as e:
        print_error("Не удалось подключиться к GigaChat. Подробности в data/app.log.")
        log.error(f"GigaChat error: {e}")
        print_info("Вакансия останется в списке. Попробуйте позже.")
        return "failed"

    vacancy_for_generation = {
        "name": full_vacancy.get("name", vacancy["name"]),
        "employer": (full_vacancy.get("employer") or {}).get(
            "name", vacancy.get("employer")
        ),
        "full_description": full_vacancy.get("description", ""),
        "key_skills": ", ".join(
            s.get("name", "") for s in full_vacancy.get("key_skills", [])
        ),
    }

    letter = None
    for attempt in range(2):
        letter = generate_letter(
            token_mgr,
            resume_data.get("full_text", ""),
            vacancy_for_generation,
            vacancy["match_score"],
            candidate_name,
            gender=resume_data.get("gender"),
            key_skills=resume_data.get("key_skills"),
            portfolio_url=portfolio_url,
        )
        if letter:
            break
        if attempt == 0:
            print_warning("С первого раза письмо не получилось.")
            if not ask_yes_no("Попробовать еще раз?", allow_cancel=True):
                break

    if not letter:
        print_error("Не удалось создать письмо.")
        print_info("Вакансия останется в списке. Попробуйте позже.")
        return "failed"

    if copy_to_clipboard(letter):
        print_success("Письмо скопировано в буфер обмена.")
    else:
        print_warning(
            "Не удалось скопировать в буфер. Скопируйте вручную из текста ниже."
        )

    print()
    print("=" * 60)
    print("Текст письма:")
    print("=" * 60)
    print(letter)
    print("=" * 60)
    print()

    if vacancy.get("link"):
        print(f"Открываю страницу вакансии: {vacancy['link']}")
        webbrowser.open(vacancy["link"])

    print()
    print_info(
        "1. Пройди тест на сайте hh.ru\n"
        "2. Вставь письмо в поле сопроводительного (Ctrl+V)\n"
        "3. Отправь отклик"
    )
    print()

    answer = ask_yes_no("Отклик отправлен?", allow_cancel=True)
    if answer is None:
        print_info("Вакансия останется в списке. Выход из обработки.")
        return "exit"
    if answer:
        add_applied_id(state, resume_id, vid)
        remove_needs_test(state, resume_id, vid)
        save_state(state)
        print_success("Вакансия отмечена как откликнутая.")
        log.info(f"Тест пройден, отклик отправлен: {vid}")
        return "sent"
    print_info("Вакансия останется в списке для следующего раза.")
    return "skipped"


def menu_pass_tests():
    print_info("\n=== Прохождение тестов ===")
    while True:
        state, config = load_state(), load_config()
        r_idx, resume_id, query = get_current_context(state, config)
        if r_idx is None:
            return

        resume_data = load_resume(resume_id)
        if not resume_data:
            print_error("Резюме не найдено. Запустите пункт 3.")
            pause()
            return
        candidate_name = (resume_data.get("candidate_name") or "").strip()
        if not candidate_name:
            print_error(
                "В резюме нет имени кандидата. " "Запустите пункт 3 для перезагрузки."
            )
            pause()
            return

        portfolio_url = (config.get("portfolio_url") or "").strip() or None

        qid = query_key(query)
        needs_test = get_needs_test(state, resume_id)
        denied = get_denied_ids(state, resume_id)

        stale = [t for t in needs_test if t.get("id") in denied]
        if stale:
            for t in stale:
                remove_needs_test(state, resume_id, t["id"])
            save_state(state)
            log.info(f"Тест: авто-очистка needs_test от denied: {len(stale)} шт.")

        current_query_tests = [
            t
            for t in needs_test
            if _needs_test_query_key(t) == qid and t.get("id") not in denied
        ]
        other_query_count = sum(
            1
            for t in needs_test
            if _needs_test_query_key(t) != qid and t.get("id") not in denied
        )

        if not current_query_tests:
            print(f"\nПо запросу '{query['name']}' нет вакансий с тестом.")
            if other_query_count:
                print_info(
                    f"По другим запросам: {other_query_count} "
                    f"{plural(other_query_count, 'вакансия', 'вакансии', 'вакансий')}. "
                    f"Смените активный запрос в пункте 9."
                )
            pause()
            return

        print()
        print(f"Запрос: {query['name']}")
        print(f"Вакансий с тестом: {len(current_query_tests)}")
        if other_query_count:
            print(f"По другим запросам: {other_query_count}")
        print()
        _show_test_vacancies(current_query_tests)

        choice = ask_choice(
            "Выбери действие:",
            [
                (
                    "do",
                    "Пройти тест",
                    "Открыть вакансию, пройти тест на сайте hh.ru\n"
                    "и отправить отклик с письмом.",
                ),
                (
                    "deny",
                    "Отметить как отказ",
                    "Пометить вакансии как неинтересные.\n"
                    "Они больше не будут показываться в этом списке.",
                ),
            ],
            allow_cancel=True,
            cancel_label="Выход в главное меню",
        )

        if choice is None:
            return

        if choice == "deny":
            raw = input(
                "Номера вакансий через запятую (например: 1, 3, 5; " "0 - отмена): "
            ).strip()
            if raw == "0":
                pause()
                continue
            valid, invalid = _parse_test_numbers(raw, len(current_query_tests))
            if invalid:
                print_warning(f"Пропущены некорректные номера: {', '.join(invalid)}")
            if not valid:
                print_error("Ни одного корректного номера не указано.")
                pause()
                continue
            print_info(f"Помечаю как отказ: {len(valid)}.")
            for n in valid:
                vid = current_query_tests[n - 1]["id"]
                mark_denied(state, resume_id, vid)
                log.info(f"Тест: помечен как отказ: {vid}")
            save_state(state)
            print_success("Готово.")
            pause()
            continue

        while True:
            state, config = load_state(), load_config()
            r_idx, resume_id, query = get_current_context(state, config)
            if r_idx is None:
                return
            qid = query_key(query)
            portfolio_url = (config.get("portfolio_url") or "").strip() or None

            needs_test = get_needs_test(state, resume_id)
            denied = get_denied_ids(state, resume_id)
            current_query_tests = [
                t
                for t in needs_test
                if _needs_test_query_key(t) == qid and t.get("id") not in denied
            ]

            if not current_query_tests:
                print_info("Все вакансии с тестом по этому запросу обработаны.")
                pause()
                return

            print()
            print(f"Запрос: {query['name']}")
            print(f"Вакансий с тестом: {len(current_query_tests)}")
            print()
            _show_test_vacancies(current_query_tests)

            num = ask_int(
                f"Номер вакансии (1-{len(current_query_tests)}, 0 - отмена): ",
                allow_cancel=True,
                min_value=1,
                max_value=len(current_query_tests),
            )
            if num is None:
                break

            vacancy = current_query_tests[num - 1]
            result = _process_single_test(
                state,
                resume_id,
                vacancy,
                resume_data,
                candidate_name,
                portfolio_url=portfolio_url,
            )
            pause()
            if result == "exit":
                break


def menu_sync():
    print_info("\n=== Синхронизация с hh.ru ===")
    while True:
        choice = ask_choice(
            "Выбери действие:",
            [
                (
                    "negotiations",
                    "Синхронизировать отклики",
                    "Скачать историю откликов, обновить прогресс\n" "и базу данных.",
                ),
                (
                    "messages_new",
                    "Проверить ответы работодателей",
                    "Загрузить чаты, где hh отметил обновление.\n"
                    "Может пропустить ответы, если hh не обновил метку.",
                ),
            ],
            allow_cancel=True,
            cancel_label="Назад в главное меню",
        )

        if choice is None:
            return

        if choice == "negotiations":
            print("Скачиваем историю откликов и обновляем базу данных...")
            run_script("sync_negotiations.py")
            pause()
            continue

        print("Выгружаем новые сообщения из чатов hh...")
        if not run_script("check_messages.py"):
            print_error("Ошибка выгрузки. Смотрите data/app.log.")
            pause()
            continue

        print("\nПоказываем последние ответы...")
        run_script("show_replies.py")
        pause()


def menu_statistics():
    print_info("\n=== Статистика ===")
    state, config = load_state(), load_config()
    r_idx, resume_id, query = get_current_context(state, config)
    if r_idx is None:
        return

    resume_data = load_resume(resume_id)
    matches = load_matches(resume_id)
    applied = get_applied_ids(state, resume_id)
    denied = get_denied_ids(state, resume_id)
    needs_test = get_needs_test(state, resume_id)

    qid = query_key(query)
    print(
        f"\nРезюме: {resume_data.get('title', resume_id) if resume_data else 'не найдено'}"
    )
    print(f"Текущий запрос: {query['name']}")
    phase_raw = state["resumes"].get(resume_id, {}).get("phase", "not_started")
    print(f"Состояние: {PHASE_RU.get(phase_raw, phase_raw)}\n")

    if matches:
        passed_raw = [
            v for v in matches.get("passed", []) if _match_query_key(v) == qid
        ]
        passed = dedupe_passed(passed_raw)
        passed_ids = {v["id"] for v in passed}
        cur_applied = applied & passed_ids
        cur_denied = denied & passed_ids
        cur_needs_test = {
            i["id"] for i in needs_test if _needs_test_query_key(i) == qid
        } & passed_ids
        not_processed = passed_ids - applied - denied - cur_needs_test

        print(f"ТЕКУЩИЙ ЗАПРОС:")
        print(f"  Всего найдено: {len(passed_raw)}")
        if len(passed_raw) > len(passed):
            print(f"  Уникальных: {len(passed)}")
        print(f"  Отправлено: {len(cur_applied)}")
        print(f"  Ожидают теста: {len(cur_needs_test)}")
        print(f"  Отклонено: {len(cur_denied)}")
        print(f"  Осталось обработать: {len(not_processed)}\n")
    else:
        print("Результаты оценки не найдены.\n")

    print("ОБЩАЯ ИСТОРИЯ ПО РЕЗЮМЕ:")
    print(f"  Всего откликов: {len(applied)}")
    print(f"  Всего ожидают теста: {len(needs_test)}")
    print(f"  Всего отказов: {len(denied)}")
    pause()


def menu_reset_progress():
    print_info("\n=== Сброс прогресса ===")
    state, config = load_state(), load_config()
    r_idx, resume_id, query = get_current_context(state, config)
    if r_idx is None:
        return

    qid = query_key(query)
    resume_data = load_resume(resume_id)
    title = (resume_data.get("title") or "Резюме") if resume_data else "Резюме"
    print(f"Резюме: {title}")
    print(f"Текущий запрос: {query['name']}")
    print()

    choice = ask_choice(
        "Что сбросить?",
        [
            (
                "processed",
                "Проверенные вакансии (только текущий запрос)",
                "При следующей оценке все вакансии этого запроса\n"
                "будут проверены заново. Отклики, отказы и тесты\n"
                "не тронутся.",
            ),
            (
                "applied",
                "Отклики (для всего резюме)",
                "Список откликнутых вакансий по всем запросам\n" "станет пустым.",
            ),
            (
                "denied",
                "Отказы (для всего резюме)",
                "Список отклоненных вакансий станет пустым.",
            ),
            (
                "needs_test",
                "Вакансии с тестом (для всего резюме)",
                "Список вакансий, ожидающих прохождения теста,\n" "станет пустым.",
            ),
            (
                "all",
                "Всё сразу (для всего резюме)",
                "Прогресс, отклики, отказы и тесты будут забыты.\n"
                "Резюме нужно будет оценить заново.",
            ),
        ],
        allow_cancel=True,
    )
    if choice is None:
        return

    label_map = {
        "processed": "проверенные вакансии текущего запроса",
        "applied": "все отклики резюме",
        "denied": "все отказы резюме",
        "needs_test": "все ожидающие теста",
        "all": "весь прогресс резюме",
    }
    print_warning(f"\nБудет сброшено: {label_map[choice]}.")
    if not ask_yes_no("Подтвердить сброс?", allow_cancel=True):
        print("Отменено.")
        return

    if choice == "processed":
        reset_processed(state, resume_id, qid)
        clear_query_hash(resume_id, qid)
    elif choice == "applied":
        reset_applied(state, resume_id)
    elif choice == "denied":
        reset_denied(state, resume_id)
    elif choice == "needs_test":
        reset_needs_test(state, resume_id)
    elif choice == "all":
        reset_all(state, resume_id)
        resume_queries = config["resumes"][r_idx].get("queries", [])
        for q in resume_queries:
            clear_query_hash(resume_id, query_key(q))
    save_state(state)
    print_success("Прогресс сброшен.")
    log.info(f"Сброс (resume={resume_id}, query={qid}, choice={choice})")
    pause()


def menu_manage_base():
    print_info("\n=== Управление базой ===")
    state, config = load_state(), load_config()
    r_idx, _, query = get_current_context(state, config)

    cnt = len(load_vacancies())
    print(f"Собрано вакансий: {cnt}")
    if query:
        print(f"Текущий запрос: {query['name']}")
    print()

    choice = ask_choice(
        "Выбери действие:",
        [
            (
                "progress",
                "Сбросить прогресс",
                "Забыть историю проверки, отклики, отказы и тесты\n"
                "для резюме. При следующей оценке (пункт 3) вакансии\n"
                "будут проверены заново.",
            ),
            (
                "cleanup",
                "Очистить базу вакансий",
                "Удалить собранные вакансии. История откликов и тестов\n" "сохранится.",
            ),
        ],
        allow_cancel=True,
    )
    if choice is None:
        return
    if choice == "progress":
        menu_reset_progress()
    elif choice == "cleanup":
        run_script("vacancy_cleanup.py")
        pause()


def menu_change_query():
    print_info("\n=== Смена активного запроса ===")
    state, config = load_state(), load_config()

    options = []
    for r_idx, resume in enumerate(config.get("resumes", [])):
        resume_id = resume_id_from_url(resume["url"])
        resume_data = load_resume(resume_id)
        resume_title = (
            resume_data.get("title", "Резюме")
            if resume_data
            else "Резюме (не загружено)"
        )
        for query in resume.get("queries", []):
            qid = query_key(query)
            options.append((f"{r_idx}:{qid}", f"[{resume_title}] {query['name']}", ""))

    if not options:
        print_error("Нет доступных запросов.")
        pause()
        return

    current_qid = state.get("current_query_id")
    current_label = "не выбран"
    for key, label, _ in options:
        _, oqid = key.split(":", 1)
        if oqid == current_qid:
            current_label = label
            break
    print(f"\nСейчас активен: {current_label}")
    choice = ask_choice("Выбери новый активный запрос:", options, allow_cancel=True)
    if choice is None:
        return

    r_str, qid = choice.split(":", 1)
    r_idx = int(r_str)
    state["current_resume_index"] = r_idx
    state["current_query_id"] = qid
    save_state(state)
    print_success(f"Активный запрос изменен.")
    log.info(f"Смена запроса на: {qid}")
    pause()


def main():
    if not os.path.exists(CONFIG_FILE):
        print_warning("Настройки не найдены. Сначала настройте поиск (пункт 1).")
        pause()

    _log_tool_version()

    state, config = load_state(), load_config()
    if config.get("resumes"):
        ensure_valid_context(state, config)

    log.info("=== HH ASSISTANT запущен ===")

    while True:
        clear_screen()
        print(MENU)
        choice = input("Твой выбор: ").strip()

        if choice == "1":
            menu_configure()
        elif choice == "2":
            menu_collect_vacancies()
        elif choice == "3":
            menu_process_resume()
        elif choice == "4":
            menu_send_applications()
        elif choice == "5":
            menu_pass_tests()
        elif choice == "6":
            menu_sync()
        elif choice == "7":
            menu_statistics()
        elif choice == "8":
            menu_manage_base()
        elif choice == "9":
            menu_change_query()
        elif choice == "0":
            log.info("=== HH ASSISTANT завершен ===")
            print("До встречи!")
            break
        else:
            print_error("Неверный выбор. Введи число от 0 до 9.")


if __name__ == "__main__":
    main()
