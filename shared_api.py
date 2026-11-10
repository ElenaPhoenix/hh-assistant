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
from logger import log

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
load_dotenv()

OAUTH_URL = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
CHAT_URL = "https://gigachat.devices.sberbank.ru/api/v1/chat/completions"

# pymorphy3 - морфологический анализатор русского языка. Нужен для пост-
# обработки рода (см. _fix_gender_forms) и определения пола имени (см.
# _gender_from_resume). Если не установлен - программа работает, но
# пост-обработка рода отключена (полагаемся только на промпт), а пол
# имени определяется по окончанию.
try:
    import pymorphy3 as _pymorphy3

    _MORPH = _pymorphy3.MorphAnalyzer()
except ImportError:
    _MORPH = None

ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]")
_RUS_WORD_RE = re.compile(r"\b[а-яёА-ЯЁ]+\b")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
_YA_RE = re.compile(r"\bя\b", re.IGNORECASE)
# Порог уверенности pymorphy: ниже - не заменяем (неоднозначный разбор).
_MORPH_SCORE_THRESHOLD = 0.5

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


def _run_hh_tool(args, timeout, encoding="utf-8", allow_stdin=False):
    kwargs = {
        "capture_output": True,
        "text": True,
        "timeout": timeout,
        "encoding": encoding or "utf-8",
        "errors": "replace",
    }
    if not allow_stdin:
        kwargs["stdin"] = subprocess.DEVNULL
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
        print_error(
            "Не удалось запустить процесс авторизации. "
            "Проверьте, что утилита hh-applicant-tool установлена."
        )
        log.error(f"authorize failed: {e}")
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
        for attempt in range(captcha_attempts):
            cmd = _build_call_cmd(endpoint, method, True)
            log.info(
                f"hh_api: interactive captcha attempt {attempt + 1}/{captcha_attempts} "
                f"for {endpoint[:80]}"
            )
            rc, stdout, stderr = _run_hh_tool(
                cmd, CAPTCHA_TIMEOUT, encoding, allow_stdin=True
            )

            if rc is None:
                last_error = "timeout"
                last_status = "timeout"
                log.warning(
                    f"hh_api: captcha timeout (rc=None) after {CAPTCHA_TIMEOUT}s"
                )
                continue

            combined = (stdout + " " + stderr).strip()
            low = combined.lower()

            if any(m in low for m in AUTH_ERROR_MARKERS):
                return "auth_required", combined[:500]

            if any(m in low for m in CAPTCHA_MARKERS):
                last_error = combined[:500]
                last_status = "captcha"
                log.warning(
                    f"hh_api: captcha attempt {attempt + 1} still failed "
                    f"(rc={rc}, stdout={stdout[:100]}, stderr={stderr[:200]})"
                )
                continue

            if rc != 0:
                log.warning(
                    f"hh_api: captcha attempt {attempt + 1} returned non-zero rc={rc} "
                    f"without captcha markers: {combined[:300]}"
                )
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
            return all_items, "stopped"

        status, data = call_api(
            f"/negotiations?per_page={per_page}&page={page}",
            retry_with_captcha=True,
        )

        if status != "ok" or not isinstance(data, dict):
            log.warning(
                f"fetch_all_negotiations: page={page} status={status}, "
                f"data={str(data)[:300]}"
            )
            return all_items, status

        items = data.get("items", [])
        if not items:
            return all_items, "ok"

        all_items.extend(items)
        page += 1

        if callback:
            callback(len(all_items), page)

        if page >= data.get("pages", 0):
            return all_items, "ok"

        time.sleep(pause)


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


def _call_gigachat(token_mgr, prompt, retries=3, max_tokens=250, temperature=0.4):
    token_mgr.ensure_valid()
    for attempt in range(retries + 1):
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token_mgr.token}",
        }
        payload = {
            "model": "GigaChat",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
            "max_tokens": max_tokens,
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


def _truncate_body(text, limit=300):
    if len(text) <= limit:
        return text
    cut = text[:limit]
    last_p = max(cut.rfind("."), cut.rfind("!"), cut.rfind("?"))
    if last_p > limit // 2:
        return cut[: last_p + 1].strip()
    last_sp = cut.rfind(" ")
    if last_sp > 0:
        return cut[:last_sp].rstrip(",;: ") + "..."
    return cut


# --- Род: пост-обработка через pymorphy3 -------------------------------
#
# GigaChat при явном промпте обычно использует правильный род, но иногда
# ошибается. pymorphy3 знает грамматику: для каждого слова определяет
# часть речи, время, число, род - и умеет ставить в нужную форму.
# Никаких списков «готов/уверен/сделал» - морфология работает для всех
# глаголов прошедшего времени и кратких прилагательных единственного
# числа.
#
# Защита от 3-го лица («компания готова»):
#   - Если в предложении есть «я» - заменяем все подходящие слова.
#   - Если «я» нет, но первое слово предложения - глагол/прил. в прошедшем
#     времени единственного числа - заменяем все (эллипсис подлежащего,
#     типично для писем: «Строила отчеты. Сократила время.»).
#   - Иначе не заменяем: «Компания готова к переменам» останется как есть.
#
# Граммемы pymorphy3 - строчные: masc, femn, neut. POS - заглавные:
# VERB, ADJS, NOUN. Грамматические признаки (past, sing) - строчные.


def _preserve_case(original, replacement):
    if original and original[0].isupper():
        return replacement[0].upper() + replacement[1:]
    return replacement


def _is_past_singular_verb_or_adjs(parse):
    """True, если разбор - глагол прош. вр. ед.ч. или краткое прил. ед.ч."""
    if parse.score < _MORPH_SCORE_THRESHOLD:
        return False
    tag = parse.tag
    if tag.POS == "VERB" and "past" in tag and "sing" in tag:
        return True
    if tag.POS == "ADJS" and "sing" in tag:
        return True
    return False


def _fix_sentence(sentence, target_gender):
    """Заменяет формы в предложении, если это предложение от 1-го лица.

    target_gender: "femn" или "masc" (граммемы pymorphy3).
    """
    words = list(_RUS_WORD_RE.finditer(sentence))
    if not words:
        return sentence

    has_ya = _YA_RE.search(sentence) is not None
    if not has_ya:
        # «я» нет. Проверяем первое слово: если это глагол/прил. в прош.
        # вр. ед.ч. - эллипсис подлежащего, заменяем все предложение.
        # Перебираем все разборы: у слова может быть несколько частей речи,
        # и не все они сработают как VERB/ADJS.
        first = words[0].group(0).lower()
        parses = _MORPH.parse(first)
        if not parses or not any(_is_past_singular_verb_or_adjs(p) for p in parses):
            return sentence

    replacements = []
    for m in words:
        word = m.group(0)
        word_lower = word.lower()
        parses = _MORPH.parse(word_lower)
        if not parses:
            continue
        # Перебираем все разборы: берем первый, который подходит под
        # VERB/ADJS в прош. вр. ед.ч. и для которого inflect дает
        # другую форму.
        new_word = None
        for p in parses:
            if not _is_past_singular_verb_or_adjs(p):
                continue
            inflected = p.inflect({target_gender})
            if not inflected:
                continue
            candidate = inflected.word
            if candidate != word_lower:
                new_word = candidate
                break
        if new_word is None:
            continue
        replacements.append((m.start(), m.end(), _preserve_case(word, new_word)))

    for start, end, new_word in sorted(replacements, reverse=True):
        sentence = sentence[:start] + new_word + sentence[end:]
    return sentence


def _fix_gender_forms(text, gender):
    """Приводит глаголы прошедшего времени и краткие прилагательные
    единственного числа к роду gender ("female" / "male").

    Универсально, без списков слов. Если pymorphy3 не установлен -
    возвращает текст как есть (работаем только на промпте).
    """
    if not text or _MORPH is None:
        return text
    target = "femn" if gender == "female" else "masc"
    sentences = _SENTENCE_SPLIT_RE.split(text)
    fixed = [_fix_sentence(s, target) for s in sentences]
    return " ".join(fixed)


def _gender_from_resume(resume_text, candidate_name):
    """Определяет пол кандидата. Всегда возвращает "female" или "male".

    1. Ищем 'Пол: Женский' / 'Пол: Женщина' / 'Пол: Мужской' / 'Пол: Мужчина'
       в тексте резюме (эту строку добавляет resume_parser.py из hh API;
       hh возвращает name = 'Женский' / 'Мужской').
    2. Иначе - по имени через pymorphy3: если это имя (тег Name) и род
       однозначен (только masc или только femn) - используем.
    3. Иначе - эвристика по окончанию.
    4. Если ничего не помогло - "female" по умолчанию.
    """
    if resume_text:
        m = re.search(r"Пол:\s*(Жен\w*|Муж\w*)", resume_text, re.IGNORECASE)
        if m:
            return "female" if m.group(1).lower().startswith("жен") else "male"

    if not candidate_name:
        return "female"

    first = candidate_name.split()[0].strip().lower()
    if not first:
        return "female"

    # Имя через pymorphy3: у имен тег Name + masc/femn. Для унисекс-имен
    # (Саша, Женя) pymorphy может вернуть оба рода - тогда не угадываем.
    if _MORPH is not None:
        name_masc = False
        name_femn = False
        for p in _MORPH.parse(first):
            tag = p.tag
            if "Name" in tag:
                if "masc" in tag:
                    name_masc = True
                if "femn" in tag:
                    name_femn = True
        if name_masc and not name_femn:
            return "male"
        if name_femn and not name_masc:
            return "female"

    # Fallback - по окончанию имени.
    if first.endswith(("а", "я", "ия")):
        return "female"
    if first[-1] not in "аяиыоуэю":
        return "male"
    return "female"


def generate_letter(
    token_mgr,
    resume_text,
    vacancy,
    match_score,
    candidate_name,
    gender=None,
    key_skills=None,
    portfolio_url=None,
):
    """Генерирует письмо из 5 блоков.

    1. Приветствие.
    2. Текст от GigaChat (максимум 300 символов), с явным полом и списком
       навыков, чтобы GigaChat не выдумывал.
    3. Ссылка на портфолио (если portfolio_url задан).
    4. Готовность оперативно выйти.
    5. Подпись.

    gender - "male"/"female" из resume_data. Если None - fallback:
    ищем "Пол: ..." в resume_text, иначе по имени.
    key_skills - список навыков из resume_data. Передается в промпт
    явно, чтобы GigaChat видел "белый список" и не выдумывал.
    portfolio_url - URL портфолио. Если задан - добавляется отдельной
    строкой перед подписью. Если None - блок портфолио отсутствует.

    Возвращает готовый текст письма (str) или None при неудаче.
    """
    if not (candidate_name or "").strip():
        return None

    if not gender:
        gender = _gender_from_resume(resume_text, candidate_name)

    if gender == "male":
        gender_human = "мужчина"
        gender_rod = "ТОЛЬКО мужского рода"
        gender_examples = '"я уверен", "я сделал", "я умею", "я смог", "я работал"'
        gender_negative = (
            '"я уверена", "я сделала", "я готова", "я смогла", "я работала"'
        )
        gender_word = "Готов"
    else:
        gender_human = "женщина"
        gender_rod = "ТОЛЬКО женского рода"
        gender_examples = '"я уверена", "я сделала", "я умею", "я смогла", "я работала"'
        gender_negative = '"я уверен", "я сделал", "я готов", "я смог", "я работал"'
        gender_word = "Готова"

    if key_skills:
        if isinstance(key_skills, list):
            skills_str = ", ".join(str(s) for s in key_skills)
        else:
            skills_str = str(key_skills)
    else:
        skills_str = "(нет данных)"

    vacancy_desc = (vacancy.get("full_description") or "")[:1000]
    # Few-shot пример написан в настоящем времени - форма рода не важна,
    # поэтому для female/male он нейтрален. Без конкретных технологий,
    # чтобы не подсовывать чужие навыки. Без чисел - в промпте есть
    # правило «не обещай результатов в числах».
    prompt = (
        f"Ты - карьерный консультант. Напиши центральную часть сопроводительного "
        f"письма от лица кандидата.\n\n"
        f"Кандидат: {candidate_name}, {gender_human}.\n"
        f"Жесткое правило рода: все глаголы и прилагательные в 1-м лице - "
        f"{gender_rod}. Примеры правильных форм: {gender_examples}. "
        f"НЕ используй: {gender_negative}. По возможности избегай прошедшего "
        f"времени - используй настоящее и будущее, где естественно.\n\n"
        f"Ключевые навыки кандидата (белый список): {skills_str}.\n"
        f"Контекст из резюме (для фактов, не для пересказа): "
        f"{resume_text[:1000]}\n\n"
        f"Что ищет работодатель в вакансии «{vacancy.get('name')}»:\n"
        f"{vacancy_desc}\n\n"
        f"Алгоритм:\n"
        f"1. Сравни требования вакансии с моими ключевыми навыками. "
        f"Найди 2-3 пересечения.\n"
        f"2. Напиши 2-3 предложения о том, как именно мой опыт по этим "
        f"пересечениям поможет работодателю. Показывай, а не перечисляй: "
        f"не 'у меня есть SQL', а конкретное действие (например, "
        f"'строю отчеты на SQL для нескольких отделов', если это есть "
        f"в моем резюме).\n"
        f"3. Если релевантного опыта нет - сделай акцент на смежном опыте "
        f"и готовности быстро разобраться. Не извиняйся, не пиши "
        f"'к сожалению', 'к сожалению у меня нет'.\n\n"
        f"Жесткие ограничения:\n"
        f"- Максимум 300 символов. Считай символы, не слова.\n"
        f"- 2-3 предложения, каждое 60-100 символов.\n"
        f"- Только навыки из белого списка. Не выдумывай технологии, "
        f"которых нет в списке, даже если они требуются в вакансии. "
        f"Лучше короче и точнее, чем соврать.\n"
        f"- Не повторяй название вакансии дословно.\n"
        f"- Не пиши про готовность приступить к работе - это в финальном блоке.\n"
        f"- Не обещай результатов в числах.\n"
        f"- Без приветствий, подписей, ссылок, markdown.\n"
        f"- Без штампов: 'стрессоустойчивость', 'командный игрок', "
        f"'быстро обучаюсь', 'целеустремленность', 'клиентоориентированность', "
        f"'многозадачность'.\n"
        f"- Без канцелярита ('осуществляла', 'в рамках', 'в целях', "
        f"'функционал', 'компетенции').\n"
        f"- Первое лицо, единственное число, деловой но живой тон.\n\n"
        f"Пример плохого ответа (не пиши так):\n"
        f"«Я целеустремленный и стрессоустойчивый специалист с большим опытом. "
        f"Готов быстро обучаться и приносить пользу компании.»\n\n"
        f"Пример хорошего ответа (пиши так, но со своими навыками):\n"
        f"«Строю отчеты и дашборды для нескольких отделов, сокращаю время "
        f"подготовки аналитики. Автоматизирую рутинные выгрузки - этим закрою "
        f"ваши задачи по отчетности.»\n\n"
        f"Перед отправкой проверь свой ответ:\n"
        f"1. Все глаголы в 1-м лице {gender_rod}?\n"
        f"2. Все навыки из белого списка?\n"
        f"3. Длина ≤ 300 символов?\n"
        f"4. Нет запрещенных штампов?\n"
        f"Если что-то не так - исправь. Верни только финальный текст."
    )
    raw = _call_gigachat(token_mgr, prompt, max_tokens=150, temperature=0.3)
    if not raw:
        return None

    body = sanitize_body(raw)
    if not body:
        return None
    body = _truncate_body(body, limit=300)

    # Страховка: pymorphy3 приводит прошедшее время к нужному роду,
    # если GigaChat ошибся. Универсально, без списков слов.
    body = _fix_gender_forms(body, gender)

    parts = []
    parts.append("Здравствуйте!")
    parts.append(body if body.endswith(".") else body + ".")
    if portfolio_url:
        parts.append(f"Мое портфолио: {portfolio_url}")
    parts.append(f"{gender_word} оперативно выйти на новую работу.")
    parts.append(f"С уважением,\n{candidate_name}")

    return "\n\n".join(p for p in parts if p)
