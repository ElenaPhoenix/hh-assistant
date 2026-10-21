import json
import os
import time
import urllib.parse
import re
from rapidfuzz import fuzz
from shared_api import load_config, call_api, DATA_DIR

VACANCIES_FILE = os.path.join(DATA_DIR, "vacancies_detailed.json")
CITY_AREA_MAP = {
    "москва": 1,
    "санкт-петербург": 2,
    "спб": 2,
    "новосибирск": 4,
    "екатеринбург": 3,
    "россия": 113,
}
WORK_FORMAT_MAP = {"remote": "REMOTE", "hybrid": "HYBRID", "office": "ON_SITE"}
VALID_EMPLOYMENTS = {"full", "part", "project"}
PER_PAGE = 100
MAX_PAGES = 20

CORE_KEYWORDS = [
    "sql",
    "bi",
    "python",
    "excel",
    "аналитик",
    "анализ данных",
    "данные",
    "дашборд",
    "отчет",
    "tableau",
    "power bi",
    "clickhouse",
    "pandas",
    "статистик",
    "метрик",
    "воронк",
    "ab-тест",
    "a/b-тест",
    "1с",
    "sap",
    "битрикс",
    "json",
    "api",
]

LOOKALIKE_MAP = str.maketrans(
    {"a": "а", "c": "с", "e": "е", "o": "о", "p": "р", "x": "х", "y": "у"}
)


def get_area_id(city):
    return CITY_AREA_MAP.get((city or "").strip().lower(), 113)


def encode(value):
    return urllib.parse.quote(str(value), safe="")


def normalize_for_match(text):
    if not text:
        return ""
    t = text.lower().translate(LOOKALIKE_MAP)
    t = re.sub(r"[\s\-_/\\|]+", " ", t)
    return t.strip()


def check_filters(name, desc, target_title, exclude_words):
    name_norm = normalize_for_match(name)
    desc_norm = normalize_for_match(desc)

    # 1. Стоп-слова (строгий поиск в названии)
    for word in exclude_words:
        w_norm = normalize_for_match(word)
        if w_norm and w_norm in name_norm:
            return False

    # 2. Явные аналитические названия пропускаем без проверки CORE_KEYWORDS
    strong_analytics = ["аналитик", "analyst", "data", "bi", "sql", "python"]
    if any(sw in name_norm for sw in strong_analytics):
        return True

    # 3. Для остальных названий требуем CORE_KEYWORDS в описании (сниппете)
    has_core_kw = any(kw in desc_norm for kw in CORE_KEYWORDS)
    if not has_core_kw:
        return False

    # 4. Если CORE_KEYWORDS есть, проверяем совпадение с target
    if not target_title:
        return True

    targets = [normalize_for_match(t) for t in target_title.split("|") if t.strip()]
    if not targets:
        return True

    for t in targets:
        if fuzz.partial_ratio(t, name_norm) >= 90 or t in desc_norm:
            return True
    return False


def search_page(
    text, area, min_salary, only_salary, employments, work_format, period, page
):
    params = [
        f"text={encode(text)}",
        f"area={area}",
        "experience=between1And3",
        f"per_page={PER_PAGE}",
        f"page={page}",
        "order_by=publication_time",
    ]
    if min_salary > 0:
        params.append(f"salary={min_salary}")
    if only_salary:
        params.append("only_with_salary=true")
    if period > 0:
        params.append(f"period={period}")
    for e in employments:
        params.append(f"employment={e}")
    if work_format:
        params.append(f"work_format={work_format}")

    status, data = call_api("/vacancies?" + "&".join(params), timeout=60)
    return data if status == "ok" and isinstance(data, dict) else None


def short_to_full(short):
    salary = short.get("salary") or {}
    emp = short.get("employer") or {}
    return {
        "id": int(short.get("id", 0)),
        "name": short.get("name"),
        "employer": emp.get("name"),
        "salary_from": salary.get("from"),
        "salary_to": salary.get("to"),
        "salary_currency": salary.get("currency"),
        "link": short.get("alternate_url"),
        "full_description": None,
    }


def load_existing():
    if not os.path.exists(VACANCIES_FILE):
        return {}
    try:
        with open(VACANCIES_FILE, "r", encoding="utf-8") as f:
            return {int(v["id"]): v for v in json.load(f) if v.get("id")}
    except Exception:
        return {}


def save_all(v_dict):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(VACANCIES_FILE, "w", encoding="utf-8") as f:
        json.dump(
            sorted(v_dict.values(), key=lambda x: x.get("id", 0), reverse=True),
            f,
            ensure_ascii=False,
            indent=2,
        )
    return len(v_dict)


def main():
    config = load_config()
    existing = load_existing()
    print(f"Существующих вакансий в базе: {len(existing)}")
    all_new = {}

    for r_idx, resume in enumerate(config["resumes"]):
        print(f"\n==================================================")
        print(f"РЕЗЮМЕ #{r_idx+1}: {resume['url']}")

        for query in resume.get("queries", []):
            print(f"\n  >>> Запрос: {query['name']}")
            kw = query["target_title"].replace("|", " OR ")

            for wf in query["work_formats"]:
                hh_wf = WORK_FORMAT_MAP.get(wf, wf.upper())
                area = (
                    113 if wf == "remote" else get_area_id(resume.get("city", "Москва"))
                )

                for period in query["periods"]:
                    print(
                        f"    [{wf.upper()} | Период: {period}] Сбор...",
                        end=" ",
                        flush=True,
                    )
                    for page in range(MAX_PAGES):
                        data = search_page(
                            kw,
                            area,
                            query["min_salary"],
                            query["only_with_salary"],
                            query["employments"],
                            hh_wf,
                            period,
                            page,
                        )
                        if not data:
                            break
                        items = data.get("items", [])
                        if not items:
                            break

                        for s in items:
                            v = short_to_full(s)
                            # Безопасное извлечение сниппета
                            snippet = s.get("snippet") or {}
                            desc_snippet = (
                                (snippet.get("requirement") or "")
                                + " "
                                + (snippet.get("responsibility") or "")
                            )

                            if check_filters(
                                v["name"],
                                desc_snippet,
                                query["target_title"],
                                query["exclude_words"],
                            ):
                                all_new[v["id"]] = v

                        if page + 1 >= data.get("pages", 0):
                            break
                        time.sleep(0.5)
                    print(f"найдено {len(all_new)} (всего)")

    print(f"\nВсего уникальных подходящих вакансий: {len(all_new)}")
    merged = dict(existing)
    truly_new = 0
    for vid, v in all_new.items():
        if vid not in existing:
            merged[vid] = v
            truly_new += 1

    print(f"Новых вакансий (которых не было в базе): {truly_new}")
    need_details = [vid for vid, v in merged.items() if not v.get("full_description")]
    print(f"Требуется догрузить описание: {len(need_details)}")

    if need_details:
        for i, vid in enumerate(need_details, 1):
            print(f"  [{i}/{len(need_details)}] id={vid}...", end=" ", flush=True)
            st, data = call_api(f"/vacancies/{vid}")
            if st == "ok" and isinstance(data, dict):
                merged[vid]["full_description"] = data.get("description", "")
                skills = data.get("key_skills") or []
                merged[vid]["key_skills"] = ", ".join(s.get("name", "") for s in skills)
            print("+")
            if i % 50 == 0:
                save_all(merged)
                print(" (сохранено)")

    total = save_all(merged)
    print(f"\nВсего вакансий в базе: {total}")


if __name__ == "__main__":
    main()
