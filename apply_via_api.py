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
    load_config,
    load_resume,
    load_matches,
    resume_id_from_url,
    check_vacancy_status,
    send_negotiation,
    TokenManager,
    generate_letter,
    load_fixed_letter,
    LETTERS_DIR,
)
from dedupe import dedupe_passed

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
        print("  ℹ️ Уже откликались на эту вакансию.")
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

    # Логика получения письма
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
            print(
                "  ❌ Не удалось сгенерировать письмо через GigaChat. Пробуем фиксированное..."
            )
            letter = load_fixed_letter()
            key_phrase = None
            if not letter:
                # Если и фиксированного нет, то это критическая ошибка,
                # но мы не можем остановить процесс здесь, поэтому просто пропускаем
                print(
                    "  ❌ Файл с фиксированным письмом отсутствует! Пропускаем вакансию."
                )
                return "failed"

        if key_phrase:
            print(f"  Ключевая фраза: «{key_phrase}»")

    print(f"  Письмо готово ({len(letter)} символов).")

    # Сохраняем лог
    os.makedirs(LETTERS_DIR, exist_ok=True)
    letters_log_path = os.path.join(LETTERS_DIR, f"{resume_id}.json")
    letters_log = {}
    if os.path.exists(letters_log_path):
        try:
            with open(letters_log_path, "r", encoding="utf-8") as f:
                letters_log = json.load(f)
        except json.JSONDecodeError:
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
            print("Не удалось определить резюме.")
            return
        args.index = config_index

    resume_url = config["resumes"][args.index]["url"]
    resume_id = resume_id_from_url(resume_url)

    resume_data = load_resume(resume_id)
    if not resume_data:
        print(f"Резюме не найдено: {resume_id}. Запусти resume_parser.py")
        return
    resume_text = resume_data["full_text"]

    matches = load_matches(resume_id)
    if not matches:
        print(f"Результаты матчинга не найдены: {resume_id}. Запусти matcher.py")
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

    deduped_count = len(passed_raw) - len(passed)

    print(f"\n{'=' * 60}")
    print(f"РЕЗЮМЕ: {resume_data.get('title', resume_id)}")
    print(f"Прошли порог: {len(passed_raw)}")
    if deduped_count > 0:
        print(f"Удалено дублей: {deduped_count} (уникальных: {len(passed)})")
    print(f"Уже откликнуто: {len(applied & {v['id'] for v in passed})}")
    print(f"Требуют теста (в очереди): {len(needs_test_ids)}")
    print(f"Отклонено работодателем: {len(denied & {v['id'] for v in passed})}")
    print(f"К отправке сейчас: {len(to_apply)}")
    print(f"Режим: {'DRY-RUN' if args.dry_run else 'РЕАЛЬНЫЙ'}")
    print(f"{'=' * 60}\n")

    if not to_apply:
        print("Нечего отправлять.")
        return

    for i, v in enumerate(to_apply, 1):
        print(f"  {i}. {v['match_score']}% - {v['name'][:60]} ({v['employer'][:30]})")
    print()

    if args.limit:
        to_apply = to_apply[: args.limit]
        print(f"Ограничено до {len(to_apply)}.\n")

    if args.dry_run:
        for i, v in enumerate(to_apply, 1):
            print(f"[{i}/{len(to_apply)}] {v['id']} — {v['name'][:60]}")
        print("\nРежим: DRY-RUN (ничего не отправлено)")
        return

    print("Получаем access_token GigaChat...")
    try:
        token_mgr = TokenManager()
        print(f"Токен получен. Остаток токенов: {token_mgr.remaining_tokens}\n")
    except Exception as e:
        print(f"❌ Ошибка GigaChat: {e}")
        print("Переключаемся на фиксированное письмо, так как GigaChat недоступен.")
        token_mgr = None

    # Проверка токенов ПЕРЕД началом
    use_fixed_letter = False
    if token_mgr is None or token_mgr.remaining_tokens <= 1000:
        print(
            f"⚠️ ВНИМАНИЕ! Остаток токенов GigaChat: {token_mgr.remaining_tokens if token_mgr else 0}"
        )
        print("Требуется фиксированное письмо.")
        use_fixed_letter = True

        if not load_fixed_letter():
            print(
                "\n❌ КРИТИЧЕСКАЯ ОШИБКА: Файл data/fixed_letter.txt не найден или пуст!"
            )
            print("Создайте его с текстом письма и запустите скрипт заново.")
            sys.exit(1)
        else:
            print("✅ Фиксированное письмо загружено.\n")

    set_phase(state, resume_id, "applying")
    save_state(state)

    stats = {"sent": 0, "test_required": 0, "denied": 0, "failed": 0, "already": 0}

    for i, vacancy in enumerate(to_apply, 1):
        vid = vacancy["id"]
        print(f"\n[{i}/{len(to_apply)}] {vid} — {vacancy['name'][:60]}")

        # Динамическая проверка токенов в процессе
        if not use_fixed_letter and token_mgr and token_mgr.remaining_tokens <= 1000:
            print(
                f"  ⚠️ Остаток токенов упал до {token_mgr.remaining_tokens}. Переключаемся на фикс-письмо."
            )
            if not load_fixed_letter():
                print(
                    "  ❌ Файл с фиксированным письмом отсутствует! Останавливаем процесс."
                )
                sys.exit(1)
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
