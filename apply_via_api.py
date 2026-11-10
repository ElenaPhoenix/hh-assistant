import json
import os
import time
import random
import argparse
from datetime import datetime

from logger import log
from state_helper import (
    load_state,
    save_state,
    get_applied_ids,
    get_denied_ids,
    get_needs_test,
    add_applied_id,
    add_needs_test,
    remove_needs_test,
    mark_denied,
    set_phase,
)
from shared_api import (
    probe_auth,
    prompt_reauth,
    check_vacancy_status,
    send_negotiation,
    TokenManager,
    generate_letter,
)
from utils import (
    load_config,
    load_resume,
    load_matches,
    resume_id_from_url,
    query_key,
    remove_vacancies_from_cache,
    LETTERS_DIR,
    load_fixed_letter,
)
from dedupe import dedupe_passed
from ui_helper import (
    ask_yes_no,
    check_stop_key,
    wait_with_stop,
    print_error,
    print_success,
    print_warning,
    print_info,
)

PAUSE_MIN = 4
PAUSE_MAX = 7
CONSECUTIVE_ERROR_LIMIT = 3
AUTH_RETRY_LIMIT = 2

CAPTCHA_HINT = (
    "  Если окно с капчей не появилось - проверьте, не включен ли VPN. "
    "hh.ru блокирует показ капчи при подозрительном IP."
)


def process_vacancy(
    vacancy,
    resume_id,
    resume_text,
    token_mgr,
    state,
    use_fixed_letter,
    query_id,
    query_name,
    candidate_name,
    resume_gender=None,
    resume_key_skills=None,
    portfolio_url=None,
):
    vid = vacancy["id"]
    print("  Проверяем статус...")
    check = check_vacancy_status(vid, resume_id, retry_with_captcha=True)

    if check == "auth_required":
        return "auth_required", False
    if check == "captcha":
        print_warning("  hh требует проверки на робота (не пройдена).")
        print_info(CAPTCHA_HINT)
        return "captcha", False
    if check == "archived":
        print("  Вакансия в архиве.")
        mark_denied(state, resume_id, vid)
        return "denied", True
    if check == "not_found":
        print("  Вакансия не найдена на hh.")
        mark_denied(state, resume_id, vid)
        return "denied", True
    if check == "closed":
        print("  Вакансия закрыта.")
        mark_denied(state, resume_id, vid)
        return "denied", True
    if check == "already_applied":
        print("  Вы уже откликались на эту вакансию.")
        add_applied_id(state, resume_id, vid)
        remove_needs_test(state, resume_id, vid)
        save_state(state)
        return "already", False
    if check == "test_required":
        print("  По вакансии требуется пройти тест.")
        add_needs_test(
            state,
            resume_id,
            {
                "id": vid,
                "name": vacancy["name"],
                "employer": vacancy.get("employer"),
                "link": vacancy.get("link"),
                "match_score": vacancy["match_score"],
                "query_id": query_id,
                "query_name": query_name,
                "discovered_at": datetime.now().isoformat(timespec="seconds"),
            },
        )
        save_state(state)
        return "test_required", False

    if check != "ok":
        print_error("Не удалось проверить статус вакансии (сеть или ошибка hh).")
        log.warning(f"check_vacancy_status({vid}) -> {check}")
        return "failed", False

    if use_fixed_letter:
        letter = load_fixed_letter()
        if not letter:
            log.error(f"Нет фиксированного письма для {vid}")
            print_error(
                "Файл с шаблоном письма пуст или отсутствует. "
                "Проверьте data/fixed_letter.txt."
            )
            return "failed", False
    else:
        print("  Создаем письмо...")
        letter = generate_letter(
            token_mgr,
            resume_text,
            vacancy,
            vacancy["match_score"],
            candidate_name,
            gender=resume_gender,
            key_skills=resume_key_skills,
            portfolio_url=portfolio_url,
        )
        if not letter:
            print("  Не удалось создать письмо. Беру готовый шаблон.")
            letter = load_fixed_letter()
            if not letter:
                log.error(f"Нет фиксированного письма для {vid}")
                print_error(
                    "Файл с шаблоном письма пуст или отсутствует. "
                    "Проверьте data/fixed_letter.txt."
                )
                return "failed", False

    os.makedirs(LETTERS_DIR, exist_ok=True)
    letters_log_path = os.path.join(LETTERS_DIR, f"{resume_id}.json")
    letters_log = {}
    if os.path.exists(letters_log_path):
        try:
            with open(letters_log_path, "r", encoding="utf-8") as f:
                letters_log = json.load(f)
        except Exception:
            pass

    letters_log[str(vid)] = {
        "letter": letter,
        "match_score": vacancy["match_score"],
        "name": vacancy["name"],
        "employer": vacancy.get("employer"),
        "link": vacancy.get("link"),
        "query_id": query_id,
        "query_name": query_name,
        "attempted_at": datetime.now().isoformat(timespec="seconds"),
    }

    print("  Отправляем отклик...")
    status, response = send_negotiation(vid, resume_id, letter, retry_with_captcha=True)
    log.info(f"Отправка {vid}: {status}")

    if status == "ok":
        print("  Отклик успешно отправлен.")
        add_applied_id(state, resume_id, vid)
        remove_needs_test(state, resume_id, vid)
        letters_log[str(vid)]["status"] = "sent"
        save_state(state)
        with open(letters_log_path, "w", encoding="utf-8") as f:
            json.dump(letters_log, f, ensure_ascii=False, indent=2)
        return "sent", False
    if status == "already":
        print("  hh сообщает: вы уже откликались на эту вакансию.")
        add_applied_id(state, resume_id, vid)
        remove_needs_test(state, resume_id, vid)
        save_state(state)
        return "already", False
    if status == "limit_exceeded":
        print_warning("  Дневной лимит откликов на hh исчерпан.")
        return "limit_exceeded", False
    if status == "auth_required":
        print_warning("  Требуется авторизация hh.")
        return "auth_required", False
    if status == "test_required":
        print("  По вакансии требуется пройти тест.")
        add_needs_test(
            state,
            resume_id,
            {
                "id": vid,
                "name": vacancy["name"],
                "employer": vacancy.get("employer"),
                "link": vacancy.get("link"),
                "match_score": vacancy["match_score"],
                "query_id": query_id,
                "query_name": query_name,
                "discovered_at": datetime.now().isoformat(timespec="seconds"),
            },
        )
        save_state(state)
        return "test_required", False
    if status == "denied":
        print("  Работодатель отклонил отклик.")
        mark_denied(state, resume_id, vid)
        return "denied", False
    if status == "captcha":
        print_warning("  hh требует проверки на робота (не пройдена).")
        print_info(CAPTCHA_HINT)
        return "captcha", False

    print_error("Не удалось отправить отклик. Подробности в data/app.log.")
    log.error(f"Ошибка отправки {vid}: {response[:500]}")
    return "failed", False


def main(index=None):
    state = load_state()
    config = load_config()

    if index is not None:
        r_idx = index
    else:
        r_idx = state.get("current_resume_index", 0)

    if r_idx >= len(config.get("resumes", [])):
        print_error("Резюме не найдено. Проверьте настройки поиска.")
        return

    state["current_resume_index"] = r_idx

    queries = config["resumes"][r_idx].get("queries", [])
    if not queries:
        print_error("В настройках нет поисковых запросов.")
        return

    current_qid = state.get("current_query_id")
    query = next((q for q in queries if query_key(q) == current_qid), None)
    if not query:
        query = queries[0]
        state["current_query_id"] = query_key(query)
        save_state(state)
        print(f"Запрос не выбран, использую: {query['name']}")

    qid = query_key(query)
    qname = query["name"]

    resume_id = resume_id_from_url(config["resumes"][r_idx]["url"])
    resume_data = load_resume(resume_id)
    if not resume_data:
        print_error("Резюме не загружено. Запустите пункт 3 для загрузки резюме.")
        return

    candidate_name = (resume_data.get("candidate_name") or "").strip()
    if not candidate_name:
        print_error(
            "В резюме нет имени кандидата. Запустите пункт 3 для перезагрузки резюме."
        )
        return

    resume_text = (resume_data.get("full_text") or "").strip()
    if not resume_text:
        print_error("Резюме не содержит текста. Запустите пункт 3.")
        return

    resume_gender = resume_data.get("gender")
    resume_key_skills = resume_data.get("key_skills")
    portfolio_url = (config.get("portfolio_url") or "").strip() or None

    matches = load_matches(resume_id)
    if not matches:
        print_error("Результаты оценки не найдены. Запустите пункт 3.")
        return

    passed_raw = [
        v for v in matches.get("passed", []) if v.get("query_id", "default") == qid
    ]
    passed = dedupe_passed(passed_raw)

    applied = get_applied_ids(state, resume_id)
    denied = get_denied_ids(state, resume_id)
    needs_test = get_needs_test(state, resume_id)
    needs_test_ids = {i["id"] for i in needs_test}

    to_apply = [
        v
        for v in passed
        if v["id"] not in applied
        and v["id"] not in denied
        and v["id"] not in needs_test_ids
    ]

    skipped_applied = sum(1 for v in passed if v["id"] in applied)
    skipped_test = sum(1 for v in passed if v["id"] in needs_test_ids)
    skipped_denied = sum(1 for v in passed if v["id"] in denied)
    dedup_diff = len(passed_raw) - len(passed)

    print(f"\n{'=' * 60}")
    print(f"РЕЗЮМЕ: {resume_data.get('title', resume_id)}")
    print(f"Кандидат: {candidate_name}")
    print(f"ЗАПРОС: {qname}")
    print(f"Подходящих вакансий: {len(passed_raw)}")
    if dedup_diff > 0:
        print(f"  уникальных (после удаления дублей): {len(passed)}")
    if skipped_applied:
        print(f"  уже откликались ранее: {skipped_applied}")
    if skipped_test:
        print(f"  ожидают прохождения теста: {skipped_test}")
    if skipped_denied:
        print(f"  отклонено: {skipped_denied}")
    print(f"К отправке сейчас: {len(to_apply)}")
    print(f"{'=' * 60}\n")

    if not to_apply:
        print("Нет новых вакансий для отправки откликов.")
        return

    print("Проверяем авторизацию на hh...")
    if probe_auth() != "ok":
        print_warning("\nСессия hh истекла или отсутствует.")
        if not prompt_reauth():
            print_error("Без авторизации отправка невозможна.")
            return
    print_success("Авторизация в порядке.\n")

    print("Подключаемся к GigaChat...")
    token_mgr = None
    use_fixed_letter = False
    try:
        token_mgr = TokenManager()
        print_success(
            f"Соединение установлено. Остаток: {token_mgr.remaining_tokens}\n"
        )
    except Exception as e:
        print_error(
            "Не удалось подключиться к GigaChat. " "Подробности в data/app.log."
        )
        log.error(f"GigaChat: {e}")
        if ask_yes_no("Использовать шаблонное письмо?"):
            use_fixed_letter = True
        else:
            return

    if token_mgr and token_mgr.remaining_tokens <= 1000:
        if ask_yes_no("Остаток GigaChat заканчивается. Переключиться на шаблон?"):
            use_fixed_letter = True

    if use_fixed_letter and not load_fixed_letter():
        print_error(
            "Файл с шаблоном письма (data/fixed_letter.txt) пуст или отсутствует. "
            "Проверьте файл."
        )
        return

    print_warning(
        "Остановить работу: нажми '0' в любой момент (без Enter).\n"
        "Прогресс сохраняется после каждого отклика."
    )
    print()

    stats = {
        "sent": 0,
        "test_required": 0,
        "denied": 0,
        "failed": 0,
        "already": 0,
        "captcha": 0,
        "limit_exceeded": 0,
        "auth_required": 0,
    }
    consecutive_errors = 0
    auth_retries = 0
    stopped_reason = None
    pending_removals = set()

    for i, vacancy in enumerate(to_apply, 1):
        if check_stop_key():
            print_warning("\nПолучена команда остановки ('0'). Сохраняю прогресс...")
            stopped_reason = "пользователь (0)"
            break

        print(f"\n[{i}/{len(to_apply)}] {vacancy['name'][:60]}")

        if not use_fixed_letter and token_mgr and token_mgr.remaining_tokens <= 1000:
            use_fixed_letter = True
            print("  Остаток GigaChat заканчивается - переключаюсь на шаблон.")

        status, should_remove = process_vacancy(
            vacancy,
            resume_id,
            resume_text,
            token_mgr,
            state,
            use_fixed_letter,
            qid,
            qname,
            candidate_name,
            resume_gender=resume_gender,
            resume_key_skills=resume_key_skills,
            portfolio_url=portfolio_url,
        )

        if should_remove:
            pending_removals.add(vacancy["id"])

        if status == "auth_required":
            auth_retries += 1
            if auth_retries > AUTH_RETRY_LIMIT:
                stopped_reason = "требуется авторизация hh (лимит попыток)"
                stats["auth_required"] += 1
                break
            print_warning("\nСессия hh истекла. Авторизуйтесь.")
            if not prompt_reauth():
                stopped_reason = "авторизация отменена"
                stats["auth_required"] += 1
                break
            print_info("Повторяю отправку для этой вакансии...")
            status, should_remove = process_vacancy(
                vacancy,
                resume_id,
                resume_text,
                token_mgr,
                state,
                use_fixed_letter,
                qid,
                qname,
                candidate_name,
                resume_gender=resume_gender,
                resume_key_skills=resume_key_skills,
                portfolio_url=portfolio_url,
            )
            if should_remove:
                pending_removals.add(vacancy["id"])
            if status == "auth_required":
                stopped_reason = "требуется авторизация hh"
                stats["auth_required"] += 1
                break

        stats[status] = stats.get(status, 0) + 1

        if status == "captcha":
            stopped_reason = "требуется проверка на робота"
            break
        if status == "limit_exceeded":
            stopped_reason = "дневной лимит откликов hh"
            break

        if status == "failed":
            consecutive_errors += 1
            if consecutive_errors >= CONSECUTIVE_ERROR_LIMIT:
                print_error(
                    f"\n{CONSECUTIVE_ERROR_LIMIT} ошибки подряд. "
                    f"Возможно, нет интернета или hh.ru недоступен. "
                    f"Останавливаюсь, прогресс сохранен."
                )
                log.error(
                    f"apply_via_api: остановка по {CONSECUTIVE_ERROR_LIMIT} "
                    f"подряд ошибкам"
                )
                stopped_reason = f"{CONSECUTIVE_ERROR_LIMIT} ошибки подряд"
                break
        else:
            consecutive_errors = 0
            auth_retries = 0

        if i < len(to_apply):
            delay = random.uniform(PAUSE_MIN, PAUSE_MAX)
            if wait_with_stop(delay):
                print_warning(
                    "\nПолучена команда остановки ('0'). Сохраняю прогресс..."
                )
                stopped_reason = "пользователь (0)"
                break

    try:
        set_phase(state, resume_id, "applied")
        save_state(state)
    except Exception as e:
        log.error(f"Не удалось сохранить финальную фазу: {e}")

    if pending_removals:
        removed = remove_vacancies_from_cache(pending_removals)
        if removed > 0:
            print_info(
                f"Удалено из локальной базы (в архиве или удалены с hh): {removed}"
            )
        log.info(
            f"apply_via_api: удалено из кэша {removed} "
            f"из {len(pending_removals)} запланированных"
        )

    print(f"\n{'=' * 60}")
    print(f"Отправлено откликов: {stats['sent']}")
    print(f"Требуют прохождения теста: {stats['test_required']}")
    print(f"Отклонено работодателем: {stats['denied']}")
    print(f"Уже откликались ранее: {stats['already']}")
    print(f"Ошибок при отправке: {stats['failed']}")
    if stats["captcha"]:
        print(f"Проверка на робота не пройдена: {stats['captcha']}")
    if stats["limit_exceeded"]:
        print(f"Дневной лимит hh: {stats['limit_exceeded']}")
    if stats["auth_required"]:
        print(f"Требуется авторизация: {stats['auth_required']}")
    if stopped_reason:
        print(f"\nОстановлено: {stopped_reason}. Прогресс сохранен.")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--index", type=int, default=None)
    args = parser.parse_args()
    main(index=args.index)
