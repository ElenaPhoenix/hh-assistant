import json
import os
import sys
import time
import random
import argparse
from datetime import datetime

from state_helper import (
    load_state,
    save_state,
    get_applied_ids,
    get_denied_ids,
    get_needs_test,
    add_applied_id,
    add_denied_id,
    add_needs_test,
    set_phase,
)
from shared_api import (
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
    LETTERS_DIR,
    load_fixed_letter,
)
from dedupe import dedupe_passed
from ui_helper import ask_yes_no, print_error, print_success, print_warning, print_info

PAUSE_MIN = 5
PAUSE_MAX = 10


def get_current_resume(state, config):
    idx = state.get("current_resume_index", 0)
    if idx >= len(config["resumes"]):
        return None, None
    resume_url = config["resumes"][idx]["url"]
    return idx, resume_id_from_url(resume_url)


def process_vacancy(
    vacancy, resume_id, resume_text, token_mgr, state, use_fixed_letter
):
    vid = vacancy["id"]
    print("  Проверяем возможность отклика...")
    check = check_vacancy_status(vid, resume_id)

    if check == "closed":
        print("  ❌ Вакансия закрыта для откликов.")
        add_denied_id(state, resume_id, vid)
        save_state(state)
        return "denied"
    if check == "already_applied":
        print("  ℹ️ Уже откликались.")
        add_applied_id(state, resume_id, vid)
        save_state(state)
        return "already"
    if check == "test_required":
        print("  ⚠️ Требуется тест. Сохраняем в очередь.")
        add_needs_test(
            state,
            resume_id,
            {
                "id": vid,
                "name": vacancy["name"],
                "employer": vacancy.get("employer"),
                "link": vacancy.get("link"),
                "match_score": vacancy["match_score"],
                "discovered_at": datetime.now().isoformat(timespec="seconds"),
            },
        )
        save_state(state)
        return "test_required"
    if check == "unknown":
        print("  ⚠️ Не удалось проверить статус. Пробуем отправить.")

    if use_fixed_letter:
        print("  Используем фиксированное письмо...")
        letter = load_fixed_letter()
        key_phrase = None
    else:
        print("  Генерируем письмо...")
        letter, key_phrase = generate_letter(
            token_mgr, resume_text, vacancy, vacancy["match_score"]
        )
        if not letter:
            print("  ❌ Не удалось сгенерировать письмо. Пробуем фиксированное...")
            letter = load_fixed_letter()
            key_phrase = None
            if not letter:
                print("  ❌ Файл с фиксированным письмом отсутствует! Пропускаем.")
                return "failed"
        if key_phrase:
            print(f"  Ключевая фраза: «{key_phrase}»")
    print(f"  Письмо готово ({len(letter)} символов).")

    os.makedirs(LETTERS_DIR, exist_ok=True)
    letters_log_path = os.path.join(LETTERS_DIR, f"{resume_id}.json")
    letters_log = {}
    if os.path.exists(letters_log_path):
        try:
            with open(letters_log_path, "r", encoding="utf-8") as f:
                letters_log = json.load(f)
        except:
            letters_log = {}

    letters_log[str(vid)] = {
        "letter": letter,
        "key_phrase": key_phrase,
        "match_score": vacancy["match_score"],
        "name": vacancy["name"],
        "employer": vacancy.get("employer"),
        "link": vacancy.get("link"),
        "attempted_at": datetime.now().isoformat(timespec="seconds"),
    }

    print("  Отправляем отклик...")
    status, response = send_negotiation(vid, resume_id, letter)

    if status == "ok":
        print("  ✅ Отклик отправлен.")
        add_applied_id(state, resume_id, vid)
        letters_log[str(vid)]["status"] = "sent"
        save_state(state)
        with open(letters_log_path, "w", encoding="utf-8") as f:
            json.dump(letters_log, f, ensure_ascii=False, indent=2)
        return "sent"
    if status == "test_required":
        print("  ⚠️ Требуется тест. Сохраняем в очередь.")
        add_needs_test(
            state,
            resume_id,
            {
                "id": vid,
                "name": vacancy["name"],
                "employer": vacancy.get("employer"),
                "link": vacancy.get("link"),
                "match_score": vacancy["match_score"],
                "discovered_at": datetime.now().isoformat(timespec="seconds"),
            },
        )
        letters_log[str(vid)]["status"] = "test_required"
        save_state(state)
        with open(letters_log_path, "w", encoding="utf-8") as f:
            json.dump(letters_log, f, ensure_ascii=False, indent=2)
        return "test_required"
    if status == "denied":
        print("  ❌ Работодатель не принимает отклик.")
        add_denied_id(state, resume_id, vid)
        letters_log[str(vid)]["status"] = "denied"
        save_state(state)
        with open(letters_log_path, "w", encoding="utf-8") as f:
            json.dump(letters_log, f, ensure_ascii=False, indent=2)
        return "denied"

    print(f"  ❌ Другая ошибка: {response[:200]}")
    letters_log[str(vid)]["status"] = "failed"
    letters_log[str(vid)]["error"] = response
    with open(letters_log_path, "w", encoding="utf-8") as f:
        json.dump(letters_log, f, ensure_ascii=False, indent=2)
    return "failed"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--index", type=int, default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    state = load_state()
    config = load_config()

    if args.index is not None:
        config_index = args.index
    else:
        config_index, _ = get_current_resume(state, config)
        if config_index is None:
            return
        args.index = config_index

    resume_url = config["resumes"][args.index]["url"]
    resume_id = resume_id_from_url(resume_url)

    resume_data = load_resume(resume_id)
    if not resume_data:
        return
    resume_text = resume_data["full_text"]

    matches = load_matches(resume_id)
    if not matches:
        return
    passed_raw = matches.get("passed", [])
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
    print(f"Прошли порог: {len(passed_raw)}")
    if len(passed_raw) > len(passed):
        print(
            f"Удалено дублей: {len(passed_raw) - len(passed)} (уникальных: {len(passed)})"
        )
    print(f"Уже откликнуто: {len(applied & {v['id'] for v in passed})}")
    print(f"Требуют теста: {len(needs_test_ids)}")
    print(f"Отклонено: {len(denied & {v['id'] for v in passed})}")
    print(f"К отправке: {len(to_apply)}")
    print(f"{'=' * 60}\n")

    if not to_apply:
        return

    if args.dry_run:
        for i, v in enumerate(to_apply, 1):
            print(f"[{i}] {v['id']} — {v['name'][:60]}")
        return

    print("Подключаемся к GigaChat...")
    token_mgr = None
    use_fixed_letter = False

    try:
        token_mgr = TokenManager()
        print_success(f"Токен получен. Остаток токенов: {token_mgr.remaining_tokens}\n")
    except Exception as e:
        print_error(f"Не удалось подключиться к GigaChat: {e}")
        print_warning("Это может быть связано с проблемами сети или VPN.")

        if ask_yes_no("Продолжить отправку, используя фиксированное письмо?"):
            use_fixed_letter = True
            if not load_fixed_letter():
                print_error("Файл data/fixed_letter.txt не найден!")
                sys.exit(1)
        else:
            print("Отправка отменена. Проверьте соединение и запустите снова.")
            return

    # Проверка токенов, если GigaChat доступен
    if token_mgr and token_mgr.remaining_tokens <= 1000:
        print_warning(
            f"ВНИМАНИЕ! Остаток токенов GigaChat: {token_mgr.remaining_tokens}"
        )
        if ask_yes_no("Переключиться на фиксированное письмо?"):
            use_fixed_letter = True
            if not load_fixed_letter():
                print_error("Файл data/fixed_letter.txt не найден!")
                sys.exit(1)

    set_phase(state, resume_id, "applying")
    save_state(state)
    stats = {"sent": 0, "test_required": 0, "denied": 0, "failed": 0, "already": 0}

    for i, vacancy in enumerate(to_apply, 1):
        vid = vacancy["id"]
        print(f"\n[{i}/{len(to_apply)}] {vid} — {vacancy['name'][:60]}")

        if not use_fixed_letter and token_mgr and token_mgr.remaining_tokens <= 1000:
            print_warning("⚠️ Токены на исходе. Переключаемся на фикс-письмо.")
            use_fixed_letter = True

        status = process_vacancy(
            vacancy, resume_id, resume_text, token_mgr, state, use_fixed_letter
        )
        stats[status] = stats.get(status, 0) + 1

        if i < len(to_apply):
            pause = random.uniform(PAUSE_MIN, PAUSE_MAX)
            print(f"  Пауза {pause:.1f} сек...")
            time.sleep(pause)

    print(f"\n{'=' * 60}")
    print(f"Отправлено: {stats['sent']}")
    print(f"Требуется тест: {stats['test_required']}")
    print(f"Отклонено: {stats['denied']}")
    print(f"Уже откликнуто: {stats['already']}")
    print(f"Ошибок: {stats['failed']}")
    print(f"{'=' * 60}")

    remaining_tests = get_needs_test(state, resume_id)
    if remaining_tests:
        print(f"\n⚠️ В очереди на тест: {len(remaining_tests)}. Фаза: applying")
    elif stats["failed"] > 0:
        print(f"\n⚠️ Есть ошибки. Фаза: applying")
    else:
        set_phase(state, resume_id, "done")
        save_state(state)
        print("\nФаза: done")


if __name__ == "__main__":
    main()
