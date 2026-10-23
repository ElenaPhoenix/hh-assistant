import json
import os
import re
import urllib.parse

DATA_DIR = "data"
RESUMES_DIR = os.path.join(DATA_DIR, "resumes")
MATCHES_DIR = os.path.join(DATA_DIR, "matches")
LETTERS_DIR = os.path.join(DATA_DIR, "letters")
FIXED_LETTER_FILE = os.path.join(DATA_DIR, "fixed_letter.txt")
CONFIG_FILE = "config.json"


def normalize(text):
    """Приводит текст к нижнему регистру, убирает спецсимволы."""
    if not text:
        return ""
    return re.sub(r"[\s\-_/\\|]+", " ", text.lower()).strip()


def clean_text(text):
    """Убирает лишние пробелы и переносы строк."""
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()


def encode_url(value):
    """URL-кодирует строку для GET-запросов."""
    return urllib.parse.quote(str(value), safe="")


def load_config():
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def load_resume(resume_id):
    path = os.path.join(RESUMES_DIR, f"{resume_id}.json")
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_matches(resume_id):
    path = os.path.join(MATCHES_DIR, f"{resume_id}.json")
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def resume_id_from_url(url):
    match = re.search(r"/resume/([a-f0-9]+)", url)
    return match.group(1) if match else None


def load_fixed_letter():
    """Загружает фиксированное письмо из data/fixed_letter.txt."""
    if not os.path.exists(FIXED_LETTER_FILE):
        return None
    with open(FIXED_LETTER_FILE, "r", encoding="utf-8") as f:
        return f.read().strip()
