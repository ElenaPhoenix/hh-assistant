"""
Общие функции для работы с hh API и GigaChat.
Используется в apply_via_api.py и main.py.
"""

import json
import os
import re
import uuid
import base64
import subprocess
import urllib.parse
import requests
import urllib3
from datetime import datetime, timedelta
from dotenv import load_dotenv

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
load_dotenv()

CONFIG_FILE = "config.json"
DATA_DIR = "data"
RESUMES_DIR = os.path.join(DATA_DIR, "resumes")
MATCHES_DIR = os.path.join(DATA_DIR, "matches")
LETTERS_DIR = os.path.join(DATA_DIR, "letters")
FIXED_LETTER_FILE = os.path.join(DATA_DIR, "fixed_letter.txt")

OAUTH_URL = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
CHAT_URL = "https://gigachat.devices.sberbank.ru/api/v1/chat/completions"

CANDIDATE_NAME = "Елена Малоросиянцева"
MAX_BODY_LEN = 240


def load_config():
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def load_resume(resume_id):
    with open(
        os.path.join(RESUMES_DIR, f"{resume_id}.json"), "r", encoding="utf-8"
    ) as f:
        return json.load(f)


def load_matches(resume_id):
    with open(
        os.path.join(MATCHES_DIR, f"{resume_id}.json"), "r", encoding="utf-8"
    ) as f:
        return json.load(f)


def resume_id_from_url(url):
    match = re.search(r"/resume/([a-f0-9]+)", url)
    return match.group(1) if match else None


def load_fixed_letter():
    if not os.path.exists(FIXED_LETTER_FILE):
        return None
    with open(FIXED_LETTER_FILE, "r", encoding="utf-8") as f:
        return f.read().strip()


def call_api(endpoint, method="GET", timeout=60):
    cmd = ["hh-applicant-tool", "call-api"]
    if method != "GET":
        cmd.append(method)
    cmd.append(endpoint)
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8", timeout=timeout
        )
    except subprocess.TimeoutExpired:
        return "timeout", None
    if result.returncode != 0:
        return "error", result.stderr[:500]
    text = (result.stdout or "").strip()
    if not text:
        return "ok", {}
    try:
        return "ok", json.loads(text)
    except json.JSONDecodeError:
        return "ok", {"raw": text[:500]}


def fetch_vacancy(vacancy_id):
    status, data = call_api(f"/vacancies/{vacancy_id}")
    return data if status == "ok" and isinstance(data, dict) else None


def check_vacancy_status(vacancy_id, resume_id):
    v = fetch_vacancy(vacancy_id)
    if not v:
        return "unknown"
    if v.get("closed_for_applicants"):
        return "closed"
    if "got_response" in (v.get("relations") or []):
        return "already_applied"
    if v.get("has_test") and v.get("test"):
        return "test_required"
    return "ok"


def _parse_negotiation_response(response_text):
    text = (response_text or "").strip()
    if text in ("", "{}", "null"):
        return "ok", "ok"
    data = None
    try:
        data = json.loads(text)
    except:
        pass
    if data is None:
        brace = text.find("{")
        if brace != -1:
            candidate = text[brace:]
            last = candidate.rfind("}")
            if last != -1:
                try:
                    data = json.loads(candidate[: last + 1])
                except:
                    data = None
    if isinstance(data, dict):
        if not data:
            return "ok", "ok"
        errors = data.get("errors", []) or []
        values = [
            str(e.get("value", "")).lower() for e in errors if isinstance(e, dict)
        ]
        description = str(data.get("description", "")).lower()
        if "test_required" in values or "must process test" in description:
            return "test_required", text[:300]
        if "application_denied" in values or "can't respond" in description:
            return "denied", text[:300]
        if "archived" in description or "vacancy_archived" in values:
            return "denied", text[:300]
        return "other_error", text[:300]
    low = text.lower()
    if "application_denied" in low or "can't respond" in low:
        return "denied", text[:300]
    if "test_required" in low or "must process test" in low:
        return "test_required", text[:300]
    return "other_error", text[:300]


def send_negotiation(vacancy_id, resume_id, message):
    encoded_message = urllib.parse.quote(message, safe="")
    endpoint = f"/negotiations?vacancy_id={vacancy_id}&resume_id={resume_id}&message={encoded_message}"
    try:
        result = subprocess.run(
            ["hh-applicant-tool", "call-api", "POST", endpoint],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=60,
        )
    except subprocess.TimeoutExpired:
        return "other_error", "Timeout"
    combined = (
        (result.stdout or "").strip() + " " + (result.stderr or "").strip()
    ).strip()
    if not combined:
        return "ok", "ok"
    return _parse_negotiation_response(combined)


def fetch_all_negotiations(per_page=100, pause=0.3):  # ИСПРАВЛЕНО! Теперь 100!
    import time as _time

    all_items = []
    page = 0
    while True:
        endpoint = f"/negotiations?per_page={per_page}&page={page}"
        status, data = call_api(endpoint)
        if status != "ok" or not isinstance(data, dict):
            break
        items = data.get("items", [])
        pages = data.get("pages", 0)
        if not items:
            break
        all_items.extend(items)
        page += 1
        if page >= pages:
            break
        _time.sleep(pause)
    return all_items


class TokenManager:
    def __init__(self):
        self.token = None
        self.expires_at = None
        self.remaining_tokens = 999999
        self.refresh()

    def _request(self):
        auth_key = os.getenv("GIGACHAT_AUTH_KEY")
        client_id = os.getenv("GIGACHAT_CLIENT_ID")
        client_secret = os.getenv("GIGACHAT_CLIENT_SECRET")
        if auth_key:
            credentials = auth_key
        elif client_id and client_secret:
            raw = f"{client_id}:{client_secret}".encode("utf-8")
            credentials = base64.b64encode(raw).decode("utf-8")
        else:
            raise ValueError("Не заданы ключи GIGACHAT в .env")
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
            "RqUID": str(uuid.uuid4()),
            "Authorization": f"Basic {credentials}",
        }
        response = requests.post(
            OAUTH_URL,
            headers=headers,
            data={"scope": "GIGACHAT_API_PERS"},
            verify=False,
            timeout=30,
        )
        response.raise_for_status()
        return response.json()["access_token"]

    def refresh(self):
        self.token = self._request()
        self.expires_at = datetime.now() + timedelta(minutes=28)
        return self.token

    def ensure_valid(self):
        if self.expires_at and datetime.now() >= self.expires_at:
            self.refresh()


def _call_gigachat(token_mgr, prompt, retries=2):
    token_mgr.ensure_valid()
    for attempt in range(retries + 1):
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {token_mgr.token}",
        }
        payload = {
            "model": "GigaChat",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.4,
            "max_tokens": 250,
        }
        try:
            response = requests.post(
                CHAT_URL, headers=headers, json=payload, verify=False, timeout=60
            )
            if "x-ratelimit-remaining" in response.headers:
                try:
                    token_mgr.remaining_tokens = int(
                        response.headers["x-ratelimit-remaining"]
                    )
                except:
                    pass
            if response.status_code == 200:
                return response.json()["choices"][0]["message"]["content"].strip()
            elif response.status_code == 401 and attempt < retries:
                token_mgr.refresh()
                continue
            else:
                return None
        except:
            return None
    return None


def find_key_phrase(vacancy_text):
    if not vacancy_text:
        return None
    text = vacancy_text.replace("\xa0", " ")
    patterns = [
        r'укажите\s+(?:в\s+)?(?:сопроводительном\s+)?письме[^\w]{0,10}([^"\'\.\n]+?)(?:[\.,\n]|$)',
        r'начните\s+(?:сопроводительное\s+)?письмо\s+со\s+слов[^\w]{0,5}([^"\'\.\n]+?)(?:[\.,\n]|$)',
        r'начните\s+(?:сопроводительное\s+)?письмо\s+с\s+фразы[^\w]{0,5}([^"\'\.\n]+?)(?:[\.,\n]|$)',
        r'в\s+(?:сопроводительном\s+)?письме\s+(?:просим\s+)?(?:указать|написать|напишите)[^\w]{0,5}([^"\'\.\n]+?)(?:[\.,\n]|$)',
        r'добавьте\s+(?:в\s+)?(?:сопроводительное\s+)?письмо[^\w]{0,5}([^"\'\.\n]+?)(?:[\.,\n]|$)',
        r'в\s+теме\s+письма\s+укажите[^\w]{0,5}([^"\'\.\n]+?)(?:[\.,\n]|$)',
        r'(?:фразу|фраза|слово|кодовое\s+слово)\s+["\']([^"\']{3,60})["\']',
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            phrase = match.group(1).strip()
            phrase = re.sub(r"\s+", " ", phrase)
            phrase = phrase.strip("\"',.:; ")
            if 3 <= len(phrase) <= 80:
                return phrase
    return None


def sanitize_body(text):
    if not text:
        return ""
    text = text.replace("ё", "е").replace("Ё", "Е")
    text = re.sub(r"[—–―]", "-", text)
    text = re.sub(r"[«»„“‟]", '"', text)
    text = text.replace("\xa0", " ").replace("\u2009", " ").replace("\u202f", " ")
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"\*(.+?)\*", r"\1", text)
    text = re.sub(r"__(.+?)__", r"\1", text)
    text = re.sub(r"_(.+?)_", r"\1", text)
    text = re.sub(r"`(.+?)`", r"\1", text)
    text = re.sub(r"^#+\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*[-•*]\s+", "", text, flags=re.MULTILINE)
    emoji_pattern = re.compile(
        "["
        "\U0001f600-\U0001f64f"
        "\U0001f300-\U0001f5ff"
        "\U0001f680-\U0001f6ff"
        "\U0001f1e0-\U0001f1ff"
        "\U00002700-\U000027bf"
        "\U0001f900-\U0001f9ff"
        "]+",
        flags=re.UNICODE,
    )
    text = emoji_pattern.sub("", text)
    text = re.sub(
        r"^(?:здравствуйте|добрый\s+день|уважаемые?\s+[^\n,]+)[!,\.\s]*",
        "",
        text.strip(),
        flags=re.IGNORECASE,
    )
    text = re.sub(r"\s*с\s+уважением[^\n]*$", "", text.strip(), flags=re.IGNORECASE)
    text = re.sub(r"^\s*\d+[\.,]\d*\s*%\s*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"\.{2,}", ".", text)
    text = re.sub(r"\n{2,}", "\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


def _build_prompt(resume_text, vacancy, match_score):
    vacancy_text = f"Название: {vacancy.get('name')}\nКомпания: {vacancy.get('employer')}\nОписание: {(vacancy.get('full_description') or '')[:2500]}\nКлючевые навыки: {vacancy.get('key_skills') or ''}"
    return f"""Ты - карьерный консультант. Напиши ТОЛЬКО центральную часть сопроводительного письма.
ФОРМАТ:
- От 1 до 3 предложений. Сама реши, сколько нужно по смыслу.
- Все предложения вместе: СТРОГО НЕ БОЛЬШЕ {MAX_BODY_LEN} символов.
- Каждое предложение: НЕ БОЛЬШЕ 110 символов.
СТИЛЬ:
- Простой язык. Короткие предложения.
- Одна мысль - одно предложение.
- Без придаточных, деепричастных оборотов, вводных слов.
ЗАПРЕЩЕНО:
- обобщённые фразы: "многолетние обязанности", "богатый опыт", "широкий спектр", "эффективно управлять", "успешно решать", "командный игрок", "стрессоустойчивый", "быстро обучаюсь";
- приветствие: "Здравствуйте", "Добрый день", "Уважаемые коллеги";
- подпись: "С уважением", имя;
- процент соответствия;
- markdown, эмодзи, многоточия;
- буква "ё";
- длинное тире "—";
- кавычки вокруг текста;
- "Спасибо за внимание".
ПРИМЕРЫ:
ПЛОХО: "Мои многолетние обязанности по созданию отчётов, что позволяло эффективно управлять данными..."
ХОРОШО: "Автоматизировала отчётность в 4 отделах, продуктивность выросла на 20%. Это поможет вашей команде быстрее получать данные."
ПЛОХО: "Являясь специалистом в аналитике, могу с уверенностью заявить..."
ХОРОШО: "Создала базу знаний для 2 отделов. Обучила 6 сотрудников работе с BI."
КОНТЕКСТ:
- Кандидат: {CANDIDATE_NAME}, аналитик данных.
- Соответствие вакансии: {match_score}%.
- Резюме (фрагмент):
{resume_text[:2500]}
- Вакансия:
{vacancy_text}
Верни ТОЛЬКО текст тела письма. Без пояснений, без кавычек, без заголовков."""


def _assemble_letter(key_phrase, body):
    parts = []
    if key_phrase:
        phrase = key_phrase.replace("ё", "е").replace("Ё", "Е")
        phrase = re.sub(r"[—–―]", "-", phrase)
        phrase = phrase.strip().rstrip(".!?")
        parts.append(f"{phrase}.")
    parts.append("Здравствуйте!")
    parts.append("Мой опыт будет ценен для вашей компании.")
    body = body.strip()
    if body and not body.endswith((".", "!", "?")):
        body += "."
    parts.append(body)
    parts.append(f"С уважением,\n{CANDIDATE_NAME}")
    return "\n\n".join(p for p in parts if p)


def generate_letter(token_mgr, resume_text, vacancy, match_score):
    key_phrase = find_key_phrase(vacancy.get("full_description") or "")
    prompt = _build_prompt(resume_text, vacancy, match_score)
    raw = _call_gigachat(token_mgr, prompt)
    if not raw:
        return None, key_phrase
    body = sanitize_body(raw)
    if len(body) > MAX_BODY_LEN:
        print(
            f"  Тело {len(body)} символов (лимит {MAX_BODY_LEN}). Принимаем как есть."
        )
    letter = _assemble_letter(key_phrase, body)
    return letter, key_phrase
