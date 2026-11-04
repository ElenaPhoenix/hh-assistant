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
):
    vid = vacancy["id"]
    print("  Проверяем статус...")
    check = check_vacancy_status(vid, resume_id, retry_with_captcha=True)

    if check == "auth_required":
        return "auth_required", False
    if check == "captcha":
        print_warning("  HH вернул капчу на проверке статуса.")
        return "captcha", False
    # unknown = сетевая ошибка или 500-я от hh.
    # Не тратим токены GigaChat - сразу fail.
    if check == "unknown":
        print_error("Не удалось проверить статус вакансии (сеть/hh).")
        log.warning(f"check_vacancy_status({vid}) -> unknown")
        return "failed", False
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
        print("  Уже откликались.")
        add_applied_id(state, resume_id, vid)
        remove_needs_test(state, resume_id, vid)
        save_state(state)
        return "already", False
    if check == "test_required":
        print("  Требуется тест.")
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

    if use_fixed_letter:
        letter = load_fixed_letter()
        key_phrase = None
    else:
        print("  Генерируем письмо...")
        letter, key_phrase = generate_letter(
            token_mgr, resume_text, vacancy, vacancy["match_score"], candidate_name
        )
        if not letter:
            print("  Не удалось сгенерировать. Берем шаблон.")
            letter = load_fixed_letter()
            key_phrase = None
            if not letter:
                log.error(f"Нет фиксированного письма для {vid}")
                return "failed", False

    if key_phrase:
        print(f"  Фраза: {key_phrase}")

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
        "key_phrase": key_phrase,
        "match_score": vacancy["match_score"],
        "name": vacancy["name"],
        "employer": vacancy.get("employer"),
        "link": vacancy.get("link"),
        "query_id": query_id,
        "query_name": query_name,
        "attempted_at": datetime.now().isoformat(timespec="seconds"),
    }

    print("  Отправляем...")
    status, response = send_negotiation(vid, resume_id, letter, retry_with_captcha=True)
    log.info(f"Отправка {vid}: {status}")

    if status == "ok":
        print("  Отклик отправлен.")
        add_applied_id(state, resume_id, vid)
        remove_needs_test(state, resume_id, vid)
        letters_log[str(vid)]["status"] = "sent"
        save_state(state)
        with open(letters_log_path, "w", encoding="utf-8") as f:
            json.dump(letters_log, f, ensure_ascii=False, indent=2)
        return "sent", False
    if status == "already":
        print("  HH сообщает: уже откликались.")
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
        print("  Требуется тест.")
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
        print("  Отказ.")
        mark_denied(state, resume_id, vid)
        return "denied", False
    if status == "captcha":
        print_warning("  HH вернул капчу при отправке (не решена).")
        return "captcha", False

    print_error(response[:200])
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
        print_error("В настройках нет запросов.")
        return

    current_qid = state.get("current_query_id")
    query = next((q for q in queries if query_key(q) == current_qid), None)
    if not query:
        query = queries[0]
        state["current_query_id"] = query_key(query)
        save_state(state)
        print(f"Запрос не выбран, используется: {query['name']}")

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

    print(f"\n{'=' * 60}")
    print(f"РЕЗЮМЕ: {resume_data.get('title', resume_id)}")
    print(f"Кандидат: {candidate_name}")
    print(f"ЗАПРОС: {qname}")
    print(f"Подходящих вакансий: {len(passed_raw)}")
    print(f"К отправке сейчас: {len(to_apply)}")
    print(f"{'=' * 60}\n")

    if not to_apply:
        print("Нет новых вакансий для отправки.")
        return

    print("Проверяем авторизацию hh...")
    auth_status = probe_auth()
    if auth_status == "auth_required":
        print_warning("\nСессия hh истекла. Требуется повторная авторизация.")
        if not prompt_reauth():
            print_error("Без авторизации отправка невозможна.")
            return
    elif auth_status == "error":
        print_error(
            "Не удалось проверить авторизацию (сетевая ошибка). "
            "Проверьте интернет и попробуйте снова."
        )
        return
    print_success("Авторизация в порядке.\n")

    print("Подключаемся к GigaChat...")
    token_mgr = None
    use_fixed_letter = False
    try:
        token_mgr = TokenManager()
        print_success(f"Токен получен. Остаток: {token_mgr.remaining_tokens}\n")
    except Exception as e:
        print_error(f"Ошибка GigaChat: {e}")
        log.error(f"GigaChat: {e}")
        if ask_yes_no("Использовать шаблонное письмо?"):
            use_fixed_letter = True
        else:
            return

    if token_mgr and token_mgr.remaining_tokens <= 1000:
        if ask_yes_no("Мало токенов. Переключиться на шаблон?"):
            use_fixed_letter = True

    print_warning(
        "Остановить работу: нажми '0' в любой момент (без Enter).\n"
        "Прогресс сохраняется после каждого отклика.\n"
        "Или Ctrl+C - тоже безопасно."
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

    try:
        for i, vacancy in enumerate(to_apply, 1):
            if check_stop_key():
                print_warning(
                    "\nПолучена команда остановки ('0'). Сохраняю прогресс..."
                )
                stopped_reason = "пользователь (0)"
                break

            print(f"\n[{i}/{len(to_apply)}] {vacancy['id']} - {vacancy['name'][:60]}")

            if (
                not use_fixed_letter
                and token_mgr
                and token_mgr.remaining_tokens <= 1000
            ):
                use_fixed_letter = True
                print("  Токенов GigaChat осталось мало - переключаемся на шаблон.")

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
                print_info("Повторяю текущую вакансию...")
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
                )
                if should_remove:
                    pending_removals.add(vacancy["id"])
                if status == "auth_required":
                    stopped_reason = "требуется авторизация hh"
                    stats["auth_required"] += 1
                    break

            stats[status] = stats.get(status, 0) + 1

            if status == "captcha":
                stopped_reason = "капча от hh.ru (не решена)"
                break
            if status == "limit_exceeded":
                stopped_reason = "дневной лимит откликов hh"
                break

            if status == "failed":
                consecutive_errors += 1
                if consecutive_errors >= CONSECUTIVE_ERROR_LIMIT:
                    print_error(
                        f"{CONSECUTIVE_ERROR_LIMIT} ошибки подряд. "
                        f"Возможно, нет интернета или hh.ru недоступен. "
                        f"Останавливаюсь, прогресс сохранён."
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

    except KeyboardInterrupt:
        print_warning("\nCtrl+C. Сохраняю прогресс...")
        log.info("apply_via_api: остановка Ctrl+C")
        stopped_reason = "Ctrl+C"

    finally:
        try:
            set_phase(state, resume_id, "applied")
            save_state(state)
        except Exception as e:
            log.error(f"Не удалось сохранить финальную фазу: {e}")

        if pending_removals:
            removed = remove_vacancies_from_cache(pending_removals)
            if removed > 0:
                print_info(f"Удалено из локальной базы (архив/не найдено): {removed}")
            log.info(
                f"apply_via_api: удалено из кэша {removed} "
                f"из {len(pending_removals)} запланированных"
            )

    print(f"\n{'=' * 60}")
    print(f"Отправлено: {stats['sent']}")
    print(f"Требуется тест: {stats['test_required']}")
    print(f"Отклонено: {stats['denied']}")
    print(f"Уже откликнуто: {stats['already']}")
    print(f"Ошибок: {stats['failed']}")
    if stats["captcha"]:
        print(f"Капча: {stats['captcha']}")
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
