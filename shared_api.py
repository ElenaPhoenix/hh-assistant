import os
import json
import subprocess
import base64
import uuid
import requests
import urllib3
from datetime import datetime, timedelta
from dotenv import load_dotenv
from utils import encode_url

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
load_dotenv()

OAUTH_URL = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
CHAT_URL = "https://gigachat.devices.sberbank.ru/api/v1/chat/completions"
CANDIDATE_NAME = "Елена Малоросиянцева"


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
        desc = str(data.get("description", "")).lower()
        if "test_required" in values or "must process test" in desc:
            return "test_required", text[:300]
        if (
            "application_denied" in values
            or "can't respond" in desc
            or "archived" in desc
        ):
            return "denied", text[:300]
        return "other_error", text[:300]
    low = text.lower()
    if "application_denied" in low or "can't respond" in low:
        return "denied", text[:300]
    if "test_required" in low:
        return "test_required", text[:300]
    return "other_error", text[:300]


def send_negotiation(vacancy_id, resume_id, message):
    encoded = encode_url(message)
    endpoint = (
        f"/negotiations?vacancy_id={vacancy_id}&resume_id={resume_id}&message={encoded}"
    )
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


def fetch_all_negotiations(per_page=100, pause=0.3):
    import time as _time

    all_items = []
    page = 0
    while True:
        status, data = call_api(f"/negotiations?per_page={per_page}&page={page}")
        if status != "ok" or not isinstance(data, dict):
            break
        items = data.get("items", [])
        if not items:
            break
        all_items.extend(items)
        page += 1
        if page >= data.get("pages", 0):
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
        if not auth_key:
            raise ValueError("Не задан GIGACHAT_AUTH_KEY в .env")
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
            "RqUID": str(uuid.uuid4()),
            "Authorization": f"Basic {auth_key}",
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

    def ensure_valid(self):
        if self.expires_at and datetime.now() >= self.expires_at:
            self.refresh()


def _call_gigachat(token_mgr, prompt, retries=2):
    token_mgr.ensure_valid()
    for attempt in range(retries + 1):
        headers = {
            "Content-Type": "application/json",
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
                token_mgr.remaining_tokens = int(
                    response.headers["x-ratelimit-remaining"]
                )
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
        r'в\s+(?:сопроводительном\s+)?письме\s+(?:просим\s+)?(?:указать|написать|напишите)[^\w]{0,5}([^"\'\.\n]+?)(?:[\.,\n]|$)',
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            phrase = match.group(1).strip()
            if 3 <= len(phrase) <= 80:
                return phrase
    return None


def sanitize_body(text):
    if not text:
        return ""
    text = text.replace("ё", "е").replace("Ё", "Е")
    text = re.sub(r"[—–―]", "-", text)
    text = re.sub(r"[«»„“‟]", '"', text)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(
        r"^(?:здравствуйте|добрый\s+день)[!,\.\s]*", "", text, flags=re.IGNORECASE
    )
    text = re.sub(r"\s*с\s+уважением[^\n]*$", "", text, flags=re.IGNORECASE)
    return text.strip()


def generate_letter(token_mgr, resume_text, vacancy, match_score):
    key_phrase = find_key_phrase(vacancy.get("full_description") or "")
    prompt = f"Ты - карьерный консультант. Напиши ТОЛЬКО центральную часть сопроводительного письма (до 240 символов). Без приветствий и подписей. Вакансия: {vacancy.get('name')}. Резюме: {resume_text[:2000]}"
    raw = _call_gigachat(token_mgr, prompt)
    if not raw:
        return None, key_phrase

    body = sanitize_body(raw)
    parts = []
    if key_phrase:
        parts.append(f"{key_phrase}.")
    parts.append("Здравствуйте!")
    parts.append("Мой опыт будет ценен для вашей компании.")
    parts.append(body if body.endswith(".") else body + ".")
    parts.append(f"С уважением,\n{CANDIDATE_NAME}")

    return "\n\n".join(p for p in parts if p), key_phrase
