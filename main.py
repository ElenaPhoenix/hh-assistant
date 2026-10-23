# Оркестратор
import os
import sys
import base64
import subprocess
import webbrowser
from datetime import datetime

from state_helper import (
    load_state,
    save_state,
    get_applied_ids,
    get_denied_ids,
    get_needs_test,
    add_applied_id,
    add_denied_id,
    remove_needs_test,
    set_phase,
)
from shared_api import send_negotiation, TokenManager, generate_letter, fetch_vacancy
from utils import load_config, load_resume, load_matches, resume_id_from_url
from dedupe import dedupe_passed
from ui_helper import (
    ask_yes_no,
    pause,
    print_success,
    print_error,
    print_warning,
    print_info,
    clear_screen,
)

MENU = """
╔══════════════════════════════════════════════════════════════════╗
║                    HH ASSISTANT — ГЛАВНОЕ МЕНЮ                   ║
╠══════════════════════════════════════════════════════════════════╣
║  1. Настроить поиск вакансий                                     ║
║  2. Собрать новые вакансии с hh.ru                               ║
║  3. Обработать резюме (парсинг + матчинг)                        ║
║  4. Отправить отклики                                            ║
║  5. Пройти тесты                                                 ║
║  6. Синхронизировать с hh                                        ║
║  7. Статистика                                                   ║
║  8. Сбросить прогресс                                            ║
║  0. Выход                                                        ║
╚══════════════════════════════════════════════════════════════════╝
"""


def run_script(script_name, *args):
    cmd = [sys.executable, script_name] + list(args)
    return subprocess.run(cmd).returncode == 0


def get_current_resume(state, config):
    idx = state.get("current_resume_index", 0)
    if idx >= len(config["resumes"]):
        return None, None, None
    resume_url = config["resumes"][idx]["url"]
    return idx, resume_id_from_url(resume_url), resume_url


def copy_to_clipboard(text):
    try:
        b64 = base64.b64encode(text.encode("utf-8")).decode("ascii")
        ps_command = f"$bytes = [Convert]::FromBase64String('{b64}'); $text = [Text.Encoding]::UTF8.GetString($bytes); Set-Clipboard -Value $text"
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


def menu_configure():
    print_info("\n=== Настройка поиска ===")
    if os.path.exists("config.json") and not ask_yes_no(
        "config.json будет перезаписан. Продолжить?"
    ):
        return
    run_script("config.py")
    pause()


def menu_collect_vacancies():
    print_info("\n=== Сбор вакансий с hh.ru ===")
    run_script("vacancy_search.py")
    pause()


def menu_process_resume():
    print_info("\n=== Обработка резюме ===")
    state = load_state()
    config = load_config()
    idx, resume_id, _ = get_current_resume(state, config)
    if idx is None:
        print_error("Не удалось определить резюме.")
        pause()
        return
    if not load_resume(resume_id):
        if not run_script("resume_parser.py", "--index", str(idx)):
            print_error("Ошибка парсинга.")
            pause()
            return
    run_script("matcher.py", "--index", str(idx))
    pause()


def menu_send_applications():
    print_info("\n=== Отправка откликов ===")
    state = load_state()
    config = load_config()
    idx, _, _ = get_current_resume(state, config)
    if idx is None:
        print_error("Не удалось определить резюме.")
        pause()
        return
    run_script("apply_via_api.py", "--index", str(idx))
    pause()


def menu_pass_tests():
    print_info("\n=== Прохождение тестов ===")
    while True:
        state = load_state()
        config = load_config()
        idx, resume_id, _ = get_current_resume(state, config)
        if idx is None:
            print_error("Не удалось определить резюме.")
            pause()
            return
        needs_test = get_needs_test(state, resume_id)
        if not needs_test:
            print("Нет вакансий, требующих теста.")
            pause()
            return

        print(f"\nВакансии с обязательным тестом ({len(needs_test)}):\n")
        for i, v in enumerate(needs_test, 1):
            print(
                f"  {i}. {v['name'][:60]}\n     {v.get('employer', 'N/A')} | {v['match_score']}%\n     {v.get('link', 'ссылка отсутствует')}\n"
            )

        if len(needs_test) == 1:
            vacancy = needs_test[0]
            print(
                "Выберите действие:\n  [д] - Обработать сейчас\n  [п] - Вернуться позже\n  [н] - Пропустить навсегда"
            )
            ans = input("Твой выбор (д/п/н): ").strip().lower()
            if ans == "н":
                add_denied_id(state, resume_id, vacancy["id"])
                remove_needs_test(state, resume_id, vacancy["id"])
                save_state(state)
                continue
            elif ans == "п":
                return
            elif ans != "д":
                print_error("Неверный ввод.")
                continue
        else:
            print(
                "Выберите действие:\n  Введи номер вакансии (1-...) для обработки\n  [п] - Вернуться позже\n  [в] - Выход в главное меню"
            )
            choice = input("Твой выбор: ").strip().lower()
            if choice in ("в", "п"):
                return
            try:
                num = int(choice)
                if 1 <= num <= len(needs_test):
                    vacancy = needs_test[num - 1]
                else:
                    print_error("Неверный номер.")
                    continue
            except ValueError:
                print_error("Введи число или букву.")
                continue

        vid = vacancy["id"]
        resume_data = load_resume(resume_id)
        if not resume_data:
            print_error("Не удалось загрузить резюме.")
            pause()
            return
        print("\nГенерируем письмо...")
        try:
            token_mgr = TokenManager()
        except Exception as e:
            print_error(f"Ошибка GigaChat: {e}")
            pause()
            continue

        full_vacancy = fetch_vacancy(vid)
        if not full_vacancy:
            print_error("Не удалось загрузить вакансию.")
            pause()
            continue

        vacancy_for_generation = {
            "name": full_vacancy.get("name", vacancy["name"]),
            "employer": (full_vacancy.get("employer") or {}).get(
                "name", vacancy.get("employer")
            ),
            "full_description": full_vacancy.get("description", ""),
            "key_skills": ", ".join(
                [s.get("name", "") for s in full_vacancy.get("key_skills", [])]
            ),
        }
        letter, key_phrase = generate_letter(
            token_mgr,
            resume_data["full_text"],
            vacancy_for_generation,
            vacancy["match_score"],
        )
        if not letter:
            print_error("Не удалось сгенерировать письмо.")
            pause()
            continue

        if copy_to_clipboard(letter):
            print_success("Письмо скопировано в буфер.")
        else:
            print_warning("Не удалось скопировать — скопируй вручную.")

        print(
            "\n"
            + "=" * 60
            + "\nТЕКСТ ПИСЬМА:\n"
            + "=" * 60
            + f"\n{letter}\n"
            + "=" * 60
        )
        print(f"\nОткрываю {vacancy.get('link', '')} в браузере...")
        if vacancy.get("link"):
            webbrowser.open(vacancy["link"])
        print(
            "\n"
            + "=" * 60
            + "\n1. Нажми 'Откликнуться'.\n2. Ответь на вопросы.\n3. Нажми 'Добавить письмо'.\n4. Вставь: Ctrl+V.\n5. Нажми 'Откликнуться'.\n"
            + "=" * 60
        )

        if ask_yes_no("\nОтклик отправлен?"):
            add_applied_id(state, resume_id, vid)
            remove_needs_test(state, resume_id, vid)
            save_state(state)
            print_success("Вакансия ушла в applied.")
        else:
            print("Оставляю в очереди.")
            pause()


def menu_sync_negotiations():
    print_info("\n=== Синхронизация с hh ===")
    run_script("sync_negotiations.py")
    pause()


def menu_statistics():
    print_info("\n=== Статистика ===")
    state = load_state()
    config = load_config()
    idx, resume_id, _ = get_current_resume(state, config)
    if idx is None:
        print_error("Не удалось определить резюме.")
        pause()
        return

    resume_data = load_resume(resume_id)
    matches = load_matches(resume_id)
    applied = get_applied_ids(state, resume_id)
    denied = get_denied_ids(state, resume_id)
    needs_test = get_needs_test(state, resume_id)

    title = resume_data.get("title", resume_id) if resume_data else "не найдено"
    print(f"\nРезюме: {title}")
    print(f"ID: {resume_id}")
    print(f"Фаза: {state['resumes'].get(resume_id, {}).get('phase', 'unknown')}\n")

    if matches:
        passed_raw = matches.get("passed", [])
        passed = dedupe_passed(passed_raw)
        passed_ids = {v["id"] for v in passed}

        # Пересечения для текущей партии
        cur_applied = applied & passed_ids
        cur_denied = denied & passed_ids
        cur_needs_test = {i["id"] for i in needs_test} & passed_ids
        not_processed = passed_ids - applied - denied - cur_needs_test

        print(f"📊 ТЕКУЩАЯ ПАРТИЯ (найдено нейросетью):")
        print(f"  Всего найдено: {len(passed_raw)}")
        if len(passed_raw) > len(passed):
            print(f"  Уникальных (без дублей): {len(passed)}")
        print(f"  ✅ Отправлено: {len(cur_applied)}")
        print(f"  ⏳ Ожидают теста: {len(cur_needs_test)}")
        print(f"  ❌ Отклонено: {len(cur_denied)}")
        print(f"  ⚠️ Осталось обработать: {len(not_processed)}")
        print()
    else:
        print("Результаты матчинга не найдены. Запустите пункт 3.\n")

    print(f"🌍 ОБЩАЯ ИСТОРИЯ (включая прошлые отклики и ручные):")
    print(f"  ✅ Всего откликов: {len(applied)}")
    print(f"  ⏳ Всего ожидают теста: {len(needs_test)}")
    print(f"  ❌ Всего отказов: {len(denied)}")

    if needs_test:
        print(f"\n=== Вакансии в очереди на тест ===")
        for v in needs_test:
            print(f"  {v['name'][:60]} ({v.get('employer', 'N/A')})")

    pause()


def menu_reset_progress():
    print_info("\n=== Сброс прогресса ===")
    state = load_state()
    config = load_config()
    idx, resume_id, _ = get_current_resume(state, config)
    if idx is None:
        return
    print(
        "Что сбросить?\n  1. 'processed'\n  2. 'applied'\n  3. 'denied'\n  4. 'needs_test'\n  5. Всё сразу\n  0. Отмена"
    )
    choice = input("\nТвой выбор: ").strip()
    from state_helper import (
        reset_processed,
        reset_applied,
        reset_denied,
        reset_needs_test,
        reset_all,
    )

    if choice == "1":
        reset_processed(state, resume_id)
    elif choice == "2":
        reset_applied(state, resume_id)
    elif choice == "3":
        reset_denied(state, resume_id)
    elif choice == "4":
        reset_needs_test(state, resume_id)
    elif choice == "5":
        reset_all(state, resume_id)
    else:
        return
    save_state(state)
    print_success("Прогресс сброшен.")
    pause()


def main():
    if not os.path.exists("config.json"):
        print_warning("config.json не найден. Сначала настрой поиск.")
        pause()
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
            menu_sync_negotiations()
        elif choice == "7":
            menu_statistics()
        elif choice == "8":
            menu_reset_progress()
        elif choice == "0":
            print("До встречи!")
            break
        else:
            print_error("Неверный выбор. Введи цифру от 0 до 8.")
            continue


if __name__ == "__main__":
    main()
