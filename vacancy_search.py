import json
import os
import time
from shared_api import call_api
from utils import load_config, encode_url, DATA_DIR
from filters import check_name_filters

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
PER_PAGE = 100
MAX_PAGES = 20


def get_area_id(city):
    return CITY_AREA_MAP.get((city or "").strip().lower(), 113)


def search_page(
    text,
    area,
    min_salary,
    only_salary,
    employments,
    work_formats,
    experiences,
    period,
    professional_roles,
    excluded_text,
    page,
):
    params = [
        f"text={encode_url(text)}",
        f"area={area}",
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

    if employments:
        params.append(f"employment={','.join(employments)}")
    if work_formats:
        params.append(f"work_format={','.join(work_formats)}")
    if experiences:
        params.append(f"experience={','.join(experiences)}")

    for role_id in professional_roles:
        params.append(f"professional_role={role_id}")

    if excluded_text:
        params.append(f"excluded_text={encode_url(excluded_text)}")

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

            kw = query.get("target_title", "аналитик").replace("|", " OR ")
            excl = ", ".join(query.get("exclude_words", []))
            roles = query.get("professional_roles", [])
            if roles:
                print(f"    Профессиональные роли: {roles}")

            formats = query.get("work_formats", ["remote"])
            hh_formats = [WORK_FORMAT_MAP.get(f, f.upper()) for f in formats]
            area = (
                113
                if "remote" in formats
                else get_area_id(resume.get("city", "Москва"))
            )

            for period in query["periods"]:
                print(f"    [Период: {period}] Сбор...", end=" ", flush=True)
                for page in range(MAX_PAGES):
                    data = search_page(
                        kw,
                        area,
                        query["min_salary"],
                        query["only_with_salary"],
                        query["employments"],
                        hh_formats,
                        query["experiences"],
                        period,
                        roles,
                        excl,
                        page,
                    )
                    if not data:
                        break
                    items = data.get("items", [])
                    if not items:
                        break

                    for s in items:
                        v = short_to_full(s)
                        if roles:
                            if check_name_filters(
                                v["name"], "", query["exclude_words"]
                            ):
                                all_new[v["id"]] = v
                        else:
                            if check_name_filters(
                                v["name"], query["target_title"], query["exclude_words"]
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

    print(f"Новых вакансий: {truly_new}")

    need_details = [vid for vid, v in all_new.items() if not v.get("full_description")]

    if need_details:
        print(f"Требуется догрузить описание: {len(need_details)}")
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
    else:
        print("Новых вакансий без описания нет. Догрузка не требуется.")

    total = save_all(merged)
    print(f"\nВсего вакансий в базе: {total}")


if __name__ == "__main__":
    main()
