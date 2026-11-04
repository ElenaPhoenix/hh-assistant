import os
import re
import json
import time
import subprocess
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

ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]")

RETRYABLE_MARKERS = (
    "ConnectionResetError",
    "Connection broken",
    "ConnectionError",
    "TimeoutError",
    "ConnectionAbortedError",
    "SSLError",
    "SSLEOFError",
    "EOF occurred in violation",
    "Max retries exceeded",
)
CAPTCHA_MARKERS = ("captcha", "are you a robot", "запросы от робота")
AUTH_ERROR_MARKERS = (
    "please authorize",
    "you need to authorize",
    "not authorized",
    "unauthorized",
    "access denied",
    "session expired",
    "invalid_token",
    "invalid_grant",
    "not logged in",
    "login required",
)

TRANSIENT_EXC = (
    requests.exceptions.SSLError,
    requests.exceptions.ConnectionError,
    requests.exceptions.Timeout,
    requests.exceptions.ChunkedEncodingError,
    requests.exceptions.RetryError,
)

CAPTCHA_TIMEOUT = 600
DEFAULT_TIMEOUT = 60
NETWORK_RETRIES = 2


def _strip_ansi(text):
    if not text:
        return text
    return ANSI_RE.sub("", text)


def _run_hh_tool(args, timeout, encoding="utf-8"):
    kwargs = {
        "capture_output": True,
        "text": True,
        "timeout": timeout,
        "encoding": encoding or "utf-8",
        "errors": "replace",
        "stdin": subprocess.DEVNULL,
    }
    try:
        result = subprocess.run(args, **kwargs)
        return (
            result.returncode,
            _strip_ansi(result.stdout or ""),
            _strip_ansi(result.stderr or ""),
        )
    except subprocess.TimeoutExpired:
        return None, "", "timeout"


def probe_auth(max_retries=2, timeout=30):
    for attempt in range(max_retries):
        rc, stdout, stderr = _run_hh_tool(
            ["hh-applicant-tool", "whoami"], timeout=timeout
        )
        if rc == 0:
            return "ok"
        combined = (stdout + " " + stderr).lower()
        if any(m in combined for m in AUTH_ERROR_MARKERS):
            return "auth_required"
        if attempt < max_retries - 1:
            time.sleep(min(2**attempt, 8))
            continue
    return "error"


def prompt_reauth():
    from ui_helper import print_info, print_error, print_success

    phone = (os.getenv("HH_LOGIN") or "").strip()
    if not phone:
        try:
            phone = input("  Номер телефона (без +): ").strip()
        except (EOFError, KeyboardInterrupt):
            return False
    if not phone:
        return False

    print_info(f"  Запускаю: hh-applicant-tool authorize {phone}")
    print_info("  Введите код из SMS, когда появится запрос.")
    print()
    try:
        subprocess.run(["hh-applicant-tool", "authorize", phone])
    except Exception as e:
        print_error(f"Не удалось запустить авторизацию: {e}")
        return False
    print()
    if probe_auth() == "ok":
        print_success("Авторизация успешна.")
        return True
    print_error("Авторизация не удалась.")
    return False


def _build_call_cmd(endpoint, method, interactive):
    cmd = ["hh-applicant-tool"]
    if interactive:
        cmd.append("--manual-captcha")
    cmd.append("call-api")
    if method != "GET":
        cmd.append(method)
    cmd.append(endpoint)
    return cmd


def hh_api(
    endpoint,
    method="GET",
    timeout=DEFAULT_TIMEOUT,
    interactive=False,
    max_captcha_retries=1,
    network_retries=NETWORK_RETRIES,
    encoding="utf-8",
):
    last_error = None
    last_status = "error"

    if not interactive:
        for attempt in range(network_retries):
            cmd = _build_call_cmd(endpoint, method, False)
            rc, stdout, stderr = _run_hh_tool(cmd, timeout, encoding)

            if rc is None:
                last_error = "timeout"
                last_status = "timeout"
                if attempt < network_retries - 1:
                    time.sleep(min(2**attempt, 8))
                    continue
                break

            combined = (stdout + " " + stderr).strip()
            low = combined.lower()

            if any(m in low for m in AUTH_ERROR_MARKERS):
                return "auth_required", combined[:500]

            if any(m in low for m in CAPTCHA_MARKERS):
                last_error = combined[:500]
                last_status = "captcha"
                break

            if rc != 0:
                last_error = combined[:2000]
                last_status = "error"
                if any(m.lower() in low for m in RETRYABLE_MARKERS):
                    if attempt < network_retries - 1:
                        time.sleep(min(2**attempt, 8))
                        continue
                return "error", last_error

            text = stdout.strip()
            if not text:
                return "ok", {}
            try:
                return "ok", json.loads(text)
            except json.JSONDecodeError:
                return "ok", {"raw": text[:2000]}

    if interactive or last_status == "captcha":
        captcha_attempts = 1 if interactive else max_captcha_retries
        for _ in range(captcha_attempts):
            cmd = _build_call_cmd(endpoint, method, True)
            rc, stdout, stderr = _run_hh_tool(cmd, CAPTCHA_TIMEOUT, encoding)

            if rc is None:
                last_error = "timeout"
                last_status = "timeout"
                continue

            combined = (stdout + " " + stderr).strip()
            low = combined.lower()

            if any(m in low for m in AUTH_ERROR_MARKERS):
                return "auth_required", combined[:500]

            if any(m in low for m in CAPTCHA_MARKERS):
                last_error = combined[:500]
                last_status = "captcha"
                continue

            if rc != 0:
                return "error", combined[:2000]

            text = stdout.strip()
            if not text:
                return "ok", {}
            try:
                return "ok", json.loads(text)
            except json.JSONDecodeError:
                return "ok", {"raw": text[:2000]}

    return last_status, last_error


def call_api(
    endpoint,
    method="GET",
    timeout=DEFAULT_TIMEOUT,
    interactive=False,
    retry_with_captcha=False,
    network_retries=None,
    **_,
):
    max_captcha = 1 if retry_with_captcha else 0
    kwargs = {"max_captcha_retries": max_captcha}
    if network_retries is not None:
        kwargs["network_retries"] = network_retries
    return hh_api(
        endpoint,
        method=method,
        timeout=timeout,
        interactive=interactive,
        **kwargs,
    )


def fetch_vacancy(vacancy_id, retry_with_captcha=False):
    max_captcha = 1 if retry_with_captcha else 0
    status, data = hh_api(f"/vacancies/{vacancy_id}", max_captcha_retries=max_captcha)
    return data if status == "ok" and isinstance(data, dict) else None


def check_vacancy_status(vacancy_id, resume_id, retry_with_captcha=False):
    max_captcha = 1 if retry_with_captcha else 0
    status, data = hh_api(f"/vacancies/{vacancy_id}", max_captcha_retries=max_captcha)

    if status == "auth_required":
        return "auth_required"
    if status == "captcha":
        return "captcha"
    if status == "error":
        err = str(data or "").lower()
        if re.search(r"\b404\b", err) or "not_found" in err:
            return "not_found"
        return "unknown"
    if status != "ok" or not isinstance(data, dict):
        return "unknown"

    if data.get("archived"):
        return "archived"
    if data.get("closed_for_applicants"):
        return "closed"
    if "got_response" in (data.get("relations") or []):
        return "already_applied"
    if data.get("has_test") and data.get("test"):
        return "test_required"
    return "ok"


def _parse_negotiation_response(response_text):
    text = (response_text or "").strip()
    if text in ("", "{}", "null"):
        return "ok", "ok"
    data = None
    try:
        data = json.loads(text)
    except Exception:
        pass
    if data is None:
        brace = text.find("{")
        if brace != -1:
            candidate = text[brace:]
            last = candidate.rfind("}")
            if last != -1:
                try:
                    data = json.loads(candidate[: last + 1])
                except Exception:
                    data = None
    if isinstance(data, dict):
        if not data:
            return "ok", "ok"
        errors = data.get("errors", []) or []
        values = [
            str(e.get("value", "")).lower() for e in errors if isinstance(e, dict)
        ]
        desc = str(data.get("description", "")).lower()
        if "already_applied" in values or "already applied" in desc:
            return "already", text[:300]
        if "limit_exceeded" in values or "daily negotiations limit" in desc:
            return "limit_exceeded", text[:300]
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
    if "captcha" in low:
        return "captcha", text[:300]
    if "already_applied" in low or "already applied" in low:
        return "already", text[:300]
    if "limit_exceeded" in low or "daily negotiations limit" in low:
        return "limit_exceeded", text[:300]
    if "application_denied" in low or "can't respond" in low:
        return "denied", text[:300]
    if "test_required" in low:
        return "test_required", text[:300]
    return "other_error", text[:300]


def send_negotiation(vacancy_id, resume_id, message, retry_with_captcha=False):
    encoded = encode_url(message)
    endpoint = (
        f"/negotiations?vacancy_id={vacancy_id}&resume_id={resume_id}&message={encoded}"
    )
    max_captcha = 1 if retry_with_captcha else 0
    status, data = hh_api(
        endpoint,
        method="POST",
        timeout=DEFAULT_TIMEOUT,
        max_captcha_retries=max_captcha,
        encoding="utf-8",
    )

    if status == "auth_required":
        return "auth_required", str(data)[:300]
    if status == "captcha":
        return "captcha", str(data)[:300]
    if status == "timeout":
        return "other_error", "Timeout"
    if status == "error":
        return _parse_negotiation_response(str(data))
    if status == "ok":
        if not data:
            return "ok", "ok"
        if isinstance(data, dict) and "raw" in data:
            return _parse_negotiation_response(data["raw"])
        if isinstance(data, dict):
            return _parse_negotiation_response(json.dumps(data, ensure_ascii=False))
        return "ok", "ok"
    return "other_error", str(data)[:300]


def fetch_all_negotiations(per_page=100, pause=0.3, callback=None):
    from ui_helper import check_stop_key

    all_items = []
    page = 0
    while True:
        if check_stop_key():
            print("\n  Остановка по команде '0'.")
            break
        status, data = call_api(f"/negotiations?per_page={per_page}&page={page}")
        if status != "ok" or not isinstance(data, dict):
            break
        items = data.get("items", [])
        if not items:
            break
        all_items.extend(items)
        page += 1

        if callback:
            callback(len(all_items), page)

        if page >= data.get("pages", 0):
            break
        time.sleep(pause)
    return all_items


class TokenManager:
    def __init__(self):
        self.token = None
        self.expires_at = None
        self.remaining_tokens = 999999
        self.refresh()

    def _request(self, max_retries=5):
        auth_key = os.getenv("GIGACHAT_AUTH_KEY")
        if not auth_key:
            raise ValueError("Не задан GIGACHAT_AUTH_KEY в .env")
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
            "RqUID": str(uuid.uuid4()),
            "Authorization": f"Basic {auth_key}",
        }
        last_exc = None
        for attempt in range(max_retries):
            try:
                response = requests.post(
                    OAUTH_URL,
                    headers=headers,
                    data={"scope": "GIGACHAT_API_PERS"},
                    verify=False,
                    timeout=30,
                )
                response.raise_for_status()
                return response.json()["access_token"]
            except TRANSIENT_EXC as e:
                last_exc = e
                if attempt < max_retries - 1:
                    time.sleep(min(2**attempt, 8))
                    continue
                raise
        if last_exc is not None:
            raise last_exc
        raise RuntimeError("_request: не удалось получить токен")

    def refresh(self):
        self.token = self._request()
        self.expires_at = datetime.now() + timedelta(minutes=28)

    def ensure_valid(self):
        if self.expires_at and datetime.now() >= self.expires_at:
            self.refresh()


def _call_gigachat(token_mgr, prompt, retries=3):
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
        except TRANSIENT_EXC:
            if attempt < retries:
                time.sleep(min(2**attempt, 8))
                continue
            return None
        except Exception:
            return None

        if "x-ratelimit-remaining" in response.headers:
            try:
                token_mgr.remaining_tokens = int(
                    response.headers["x-ratelimit-remaining"]
                )
            except ValueError:
                pass

        if response.status_code == 200:
            try:
                return response.json()["choices"][0]["message"]["content"].strip()
            except Exception:
                return None
        elif response.status_code == 401 and attempt < retries:
            try:
                token_mgr.refresh()
            except TRANSIENT_EXC:
                if attempt < retries:
                    time.sleep(min(2**attempt, 8))
                    continue
                return None
            continue
        else:
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


def generate_letter(token_mgr, resume_text, vacancy, match_score, candidate_name):
    key_phrase = find_key_phrase(vacancy.get("full_description") or "")
    if not (candidate_name or "").strip():
        return None, key_phrase

    prompt = (
        f"Ты - высококлассный карьерный консультант. Напиши ТОЛЬКО центральную часть сопроводительного письма (до 240 символов). Без приветствий и подписей. "
        f"Текст должен пояснять, почему меня должны принять на работу, какие мои навыки и опыт принесут пользу для компании. "
        f"Текст должен быть написан в едином стиле, исчерпывающим, интересным, цепляющим. НЕ ПРИВОДИ ПРИМЕРЫ МОИХ РЕЗУЛЬТАТОВ В ЧИСЛАХ И НЕ ОБЕЩАЙ ИХ."
        f"Не повторяй название вакансии, сразу говори о моей ценности."
        f"Вакансия: {vacancy.get('name')}. Резюме: {resume_text[:2000]}"
    )
    raw = _call_gigachat(token_mgr, prompt)
    if not raw:
        return None, key_phrase

    body = sanitize_body(raw)
    parts = []
    if key_phrase:
        parts.append(f"{key_phrase}.")
    parts.append("Здравствуйте!")
    parts.append(body if body.endswith(".") else body + ".")
    parts.append(f"С уважением,\n{candidate_name}")

    return "\n\n".join(p for p in parts if p), key_phrase
