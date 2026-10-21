# Парсинг резюме с hh.
from patchright.sync_api import sync_playwright
import time
import json
import os
import re
import argparse
from state_helper import load_state, save_state, set_phase, set_resume_meta

SESSION_FILE = "hh_session.json"
CONFIG_FILE = "config.json"
DATA_DIR = "data"
RESUMES_DIR = os.path.join(DATA_DIR, "resumes")


def ensure_dirs():
    os.makedirs(RESUMES_DIR, exist_ok=True)


def verify_session(page):
    """Проверяет, что сессия валидна."""
    try:
        page.goto(
            "https://hh.ru/applicant/profile/me",
            wait_until="domcontentloaded",
            timeout=60000,
        )
        time.sleep(4)
        url = page.url
        if "/account/login" in url or "/login" in url:
            return False
        body = page.inner_text("body")
        if "Войти с паролем" in body and "Поиск работы" in body:
            return False
        return "/applicant/" in url
    except Exception as e:
        print(f"Ошибка проверки сессии: {e}")
        return False


def clean_resume_text(raw_text):
    """Очищает текст резюме от мусора."""
    text = raw_text
    text = re.sub(r"^Профиль\s*/\s*[^\n]+\n", "", text)

    text = re.sub(
        r"Контакты\nМобильный телефон\n\+?[\d\s\-()]+\n"
        r"Электронная почта[^\n]*\n[^\n]+\n",
        "Контакты: скрыты\n",
        text,
    )
    text = re.sub(
        r"Рекомендации\nПокажите в резюме рекомендации.*?Показывать рекомендации\n?",
        "",
        text,
        flags=re.DOTALL,
    )
    text = re.sub(r"\nРедактировать\n", "\n", text)
    text = re.sub(r"\nДобавить\n", "\n", text)
    text = re.sub(r"\nРазвернуть\n", "\n", text)
    text = re.sub(r"\nУказать уровни\n", "\n", text)

    idx = text.find("Опыт работы")
    if idx != -1:
        text = text[idx:]

    end_markers = [
        "Подтверждение навыков",
        "Курсы по профессии",
        "Курсы от проверенных школ",
        "Портфолио\nДобавьте работы",
    ]
    for marker in end_markers:
        idx = text.find(marker)
        if idx != -1:
            text = text[:idx]

    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def parse_resume(resume_url):
    """Парсит резюме по URL. Возвращает словарь или None."""
    ensure_dirs()

    if not os.path.exists(SESSION_FILE):
        print("Файл сессии не найден. Сначала запусти hh_login_patchright.py")
        return None

    match = re.search(r"/resume/([a-f0-9]+)", resume_url)
    if not match:
        print(f"Не удалось извлечь ID резюме из URL: {resume_url}")
        return None
    resume_id = match.group(1)

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
            locale="ru-RU",
            storage_state=SESSION_FILE,
        )
        page = context.new_page()
        page.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )

        print("Проверяем сессию...")
        if not verify_session(page):
            print("Сессия недействительна.")
            print("Решение: запусти python hh_login_patchright.py")
            browser.close()
            return None

        print(f"Открываем резюме: {resume_url}")
        page.goto(resume_url, wait_until="domcontentloaded", timeout=60000)
        time.sleep(5)

        # Проверка: не выкинуло ли на логин
        body = page.inner_text("body")
        if "Войти с паролем" in body and "Поиск работы" in body:
            print("Сессия слетела при переходе на резюме.")
            print("Решение: запусти python hh_login_patchright.py")
            browser.close()
            return None

        cleaned_text = ""
        try:
            block = page.query_selector("main")
            if block:
                cleaned_text = clean_resume_text(block.inner_text())
        except Exception:
            pass

        if not cleaned_text or len(cleaned_text) < 500:
            cleaned_text = clean_resume_text(page.inner_text("body"))

        title = page.title()
        browser.close()

    return {
        "title": title,
        "full_text": cleaned_text,
        "url": resume_url,
        "resume_id": resume_id,
    }


def main():
    parser = argparse.ArgumentParser(description="Парсер резюме hh.ru")
    parser.add_argument(
        "--index", type=int, default=None, help="Индекс резюме в config.json"
    )
    parser.add_argument("--url", type=str, default=None, help="URL резюме напрямую")
    args = parser.parse_args()

    if args.url:
        resume_url = args.url
    elif args.index is not None:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            config = json.load(f)
        resume_url = config["resumes"][args.index]["url"]
    else:
        resume_url = input("Введи URL резюме: ").strip()

    if not resume_url:
        print("URL не указан.")
        return

    result = parse_resume(resume_url)
    if not result:
        return

    ensure_dirs()
    out_path = os.path.join(RESUMES_DIR, f"{result['resume_id']}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    state = load_state()
    set_resume_meta(state, result["resume_id"], url=resume_url, title=result["title"])
    set_phase(state, result["resume_id"], "parsed")
    save_state(state)

    print(f"\nРезюме сохранено: {out_path}")
    print(f"Длина текста: {len(result['full_text'])} символов")
    print(f"ID: {result['resume_id']}")
    print(f"Фаза: parsed")


if __name__ == "__main__":
    main()
