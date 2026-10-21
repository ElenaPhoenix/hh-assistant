# Оркестратор
import os
import sys
import base64
import subprocess
import webbrowser
import json
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
from shared_api import (
    load_config,
    load_resume,
    load_matches,
    resume_id_from_url,
    send_negotiation,
    TokenManager,
    generate_letter,
    fetch_vacancy,
)
from dedupe import dedupe_passed

MENU = """
╔══════════════════════════════════════════════════════════════════╗
║                    HH ASSISTANT — ГЛАВНОЕ МЕНЮ                   ║
╠══════════════════════════════════════════════════════════════════╣
║                                                                  ║
║  1. Настроить поиск вакансий                                     ║
║     Меню для ввода: список резюме, ключевые слова, стоп-слова,   ║
║     зарплата, формат работы, порог соответствия.                 ║
║     Результат сохраняется в config.json.                         ║
║                                                                  ║
║  2. Собрать новые вакансии с hh.ru                               ║
║     Парсит вакансии по фильтрам из config.json, сохраняет        ║
║     в data/vacancies_detailed.json.                              ║
║                                                                  ║
║  3. Обработать резюме (парсинг + матчинг)                        ║
║     Загружает резюме с hh, прогоняет матчинг по всем вакансиям,  ║
║     сохраняет список прошедших порог в data/matches/.            ║
║                                                                  ║
║  4. Отправить отклики                                            ║
║     Для каждой passed-вакансии: проверяет возможность отклика,   ║
║     генерирует письмо через GigaChat, отправляет через hh API.   ║
║                                                                  ║
║  5. Пройти тесты                                                 ║
║     Генерирует письмо через GigaChat, копирует в буфер,          ║
║     открывает вакансию. Ты отвечаешь на вопросы и вставляешь     ║
║     письмо (Ctrl+V) в браузере.                                  ║
║                                                                  ║
║  6. Синхронизировать с hh                                        ║
║     Загружает все твои отклики с hh.ru в state.json.             ║
║     Нужно для дедупликации при ручных откликах.                  ║
║                                                                  ║
║  7. Статистика                                                   ║
║     Показывает текущий прогресс по текущему резюме.              ║
║                                                                  ║
║  8. Сбросить прогресс                                            ║
║     Удаляет данные о просмотренных/откликнутых вакансиях.        ║
║                                                                  ║
║  0. Выход                                                        ║
║                                                                  ║
╚══════════════════════════════════════════════════════════════════╝
"""


def pause():
    input("\nНажми Enter для продолжения...")


def run_script(script_name, *args):
    cmd = [sys.executable, script_name] + list(args)
    print(f"\n>>> Запуск: {' '.join(cmd)}\n")
    result = subprocess.run(cmd)
    return result.returncode == 0


def get_current_resume(state, config):
    idx = state.get("current_resume_index", 0)
    if idx >= len(config["resumes"]):
        return None, None, None
    resume_url = config["resumes"][idx]["url"]
    resume_id = resume_id_from_url(resume_url)
    return idx, resume_id, resume_url


def copy_to_clipboard(text):
    try:
        b64 = base64.b64encode(text.encode("utf-8")).decode("ascii")
        ps_command = (
            f"$bytes = [Convert]::FromBase64String('{b64}'); "
            f"$text = [Text.Encoding]::UTF8.GetString($bytes); "
            f"Set-Clipboard -Value $text"
        )
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_command],
            capture_output=True,
            timeout=15,
        )
        return result.returncode == 0
    except Exception:
        return False


# ============================================================
# Пункты меню
# ============================================================


def menu_configure():
    print("\n=== Настройка поиска ===")
    if os.path.exists("config.json"):
        print("Внимание: config.json будет перезаписан.")
        if input("Продолжить? (y/n): ").strip().lower() != "y":
            return
    run_script("config.py")
    pause()


def menu_collect_vacancies():
    print("\n=== Сбор вакансий с hh.ru ===")
    run_script("vacancy_search.py")
    pause()


def menu_process_resume():
    print("\n=== Обработка резюме ===")
    state = load_state()
    config = load_config()
    idx, resume_id, _ = get_current_resume(state, config)
    if idx is None:
        print("Ошибка: не удалось определить текущее резюме.")
        pause()
        return

    resume_data = load_resume(resume_id)
    if not resume_data:
        print(f"\n[1/2] Резюме не найдено — парсим...")
        if not run_script("resume_parser.py", "--index", str(idx)):
            print("Ошибка парсинга.")
            pause()
            return
    else:
        print(f"\n[1/2] Резюме уже распарсено: {resume_data.get('title', resume_id)}")

    print(f"\n[2/2] Запускаем матчинг...")
    run_script("matcher.py", "--index", str(idx))
    pause()


def menu_send_applications():
    print("\n=== Отправка откликов ===")
    state = load_state()
    config = load_config()
    idx, _, _ = get_current_resume(state, config)
    if idx is None:
        print("Ошибка: не удалось определить текущее резюме.")
        pause()
        return
    run_script("apply_via_api.py", "--index", str(idx))
    pause()


def menu_pass_tests():
    print("\n=== Прохождение тестов ===")
    while True:
        state = load_state()
        config = load_config()
        idx, resume_id, _ = get_current_resume(state, config)
        if idx is None:
            print("Ошибка: не удалось определить текущее резюме.")
            pause()
            return

        needs_test = get_needs_test(state, resume_id)

        if not needs_test:
            print("Нет вакансий, требующих теста. Возврат в главное меню.")
            pause()
            return

        print(f"\nВакансии с обязательным тестом ({len(needs_test)}):\n")
        for i, v in enumerate(needs_test, 1):
            print(f"  {i}. {v['name'][:60]}")
            print(f"     {v.get('employer', 'N/A')} | {v['match_score']}%")
            print(f"     {v.get('link', 'ссылка отсутствует')}")
            print()

        if len(needs_test) == 1:
            vacancy = needs_test[0]
            ans = (
                input(
                    "Обработать эту вакансию? (y - сейчас, l - позже, n - пропустить): "
                )
                .strip()
                .lower()
            )
            if ans == "n":
                add_denied_id(state, resume_id, vacancy["id"])
                remove_needs_test(state, resume_id, vacancy["id"])
                save_state(state)
                print("Вакансия помечена как проигнорированная и больше не появится.")
                continue
            elif ans == "l":
                return
            elif ans != "y":
                continue
        else:
            choice = (
                input(
                    f"Введи номер (1-{len(needs_test)}), 'l' (вернуться позже) или 'q' (выход): "
                )
                .strip()
                .lower()
            )
            if choice in ("q", "l"):
                return
            try:
                num = int(choice)
            except ValueError:
                print("Неверный ввод.")
                pause()
                continue
            if num < 1 or num > len(needs_test):
                print(f"Номера {num} нет в списке.")
                pause()
                continue
            vacancy = needs_test[num - 1]

        vid = vacancy["id"]

        resume_data = load_resume(resume_id)
        if not resume_data:
            print("Не удалось загрузить резюме. Сначала пункт 3.")
            pause()
            return
        resume_text = resume_data["full_text"]

        print("\nГенерируем сопроводительное письмо через GigaChat...")
        try:
            token_mgr = TokenManager()
        except Exception as e:
            print(f"❌ Ошибка GigaChat: {e}")
            pause()
            continue

        full_vacancy = fetch_vacancy(vid)
        if not full_vacancy:
            print("Не удалось загрузить данные вакансии.")
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
            token_mgr, resume_text, vacancy_for_generation, vacancy["match_score"]
        )
        if not letter:
            print("Не удалось сгенерировать письмо.")
            pause()
            continue

        if copy_to_clipboard(letter):
            print("\n📋 Письмо скопировано в буфер обмена. В браузере вставишь Ctrl+V.")
        else:
            print(
                "\n⚠️ Не удалось скопировать в буфер — скопируй вручную из текста ниже."
            )

        print("\n" + "=" * 60)
        print("ТЕКСТ ПИСЬМА:")
        print("=" * 60)
        print(letter)
        print("=" * 60)

        print(f"\nОткрываю {vacancy.get('link', '')} в браузере...")
        if vacancy.get("link"):
            webbrowser.open(vacancy["link"])

        print("\n" + "=" * 60)
        print("ЧТО ДЕЛАТЬ В БРАУЗЕРЕ:")
        print("1. Нажми 'Откликнуться'.")
        print("2. Ответь на вопросы работодателя.")
        print("3. Нажми 'Добавить сопроводительное письмо'.")
        print("4. Вставь письмо: Ctrl+V.")
        print("5. Нажми синюю кнопку 'Откликнуться' внизу формы.")
        print("=" * 60)

        ans = input("\nОтклик отправлен? (y/n): ").strip().lower()
        if ans == "y":
            add_applied_id(state, resume_id, vid)
            remove_needs_test(state, resume_id, vid)
            save_state(state)
            print("✅ Отмечено: вакансия ушла в applied, из очереди на тест удалена.")
        else:
            print("Оставляю в очереди на тест — можно вернуться сюда позже.")

        pause()


def menu_sync_negotiations():
    print("\n=== Синхронизация с hh ===")
    run_script("sync_negotiations.py")
    pause()


def menu_statistics():
    print("\n=== Статистика ===")
    state = load_state()
    config = load_config()
    idx, resume_id, _ = get_current_resume(state, config)
    if idx is None:
        print("Ошибка: не удалось определить текущее резюме.")
        pause()
        return

    resume_data = load_resume(resume_id)
    matches = load_matches(resume_id)

    applied = get_applied_ids(state, resume_id)
    denied = get_denied_ids(state, resume_id)
    needs_test = get_needs_test(state, resume_id)

    print(
        f"\nРезюме: {resume_data.get('title', resume_id) if resume_data else 'не найдено'}"
    )
    print(f"ID: {resume_id}")
    print(f"Фаза: {state['resumes'].get(resume_id, {}).get('phase', 'unknown')}")
    print()

    if matches:
        passed_raw = matches.get("passed", [])
        passed = dedupe_passed(passed_raw)
        passed_ids = {v["id"] for v in passed}
        deduped_count = len(passed_raw) - len(passed)

        print(f"Прошли порог: {len(passed_raw)}")
        if deduped_count > 0:
            print(f"  Уникальных (без дублей): {len(passed)}")
        print(f"  Уже откликнуто (из passed): {len(applied & passed_ids)}")
        print(f"  В очереди на тест: {len(needs_test)}")
        print(f"  Отклонено: {len(denied & passed_ids)}")
        not_processed = passed_ids - applied - denied - {i["id"] for i in needs_test}
        print(f"  Ещё не обработано: {len(not_processed)}")
    else:
        print("Результаты матчинга не найдены.")

    print(f"\nВсего в state.json:")
    print(f"  Откликов (applied): {len(applied)}")
    print(f"  Отклонено (denied): {len(denied)}")
    print(f"  Требуют теста: {len(needs_test)}")

    if needs_test:
        print(f"\n=== Вакансии в очереди на тест ===")
        for v in needs_test:
            print(f"  {v['name'][:60]} ({v.get('employer', 'N/A')})")

    pause()


def menu_reset_progress():
    print("\n=== Сброс прогресса ===")
    state = load_state()
    config = load_config()
    idx, resume_id, _ = get_current_resume(state, config)
    if idx is None:
        print("Ошибка: не удалось определить текущее резюме.")
        pause()
        return

    print(f"\nТекущее резюме: {resume_id}")
    print("Что сбросить?")
    print("  1. Только 'processed' (просмотренные матчером)")
    print("  2. Только 'applied' (отклики)")
    print("  3. Только 'denied' (отклонённые)")
    print("  4. Только 'needs_test' (очередь на тест)")
    print("  5. Всё сразу (полный сброс)")
    print("  0. Отмена")

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
        print("Отменено.")
        pause()
        return

    save_state(state)
    print("Готово.")
    pause()


# ============================================================
# Основной цикл
# ============================================================


def main():
    if not os.path.exists("config.json"):
        print("config.json не найден. Сначала настрой поиск (пункт 1).")
        pause()

    while True:
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
            print("Неверный выбор.")
            pause()


if __name__ == "__main__":
    main()
