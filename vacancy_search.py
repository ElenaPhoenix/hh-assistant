import os
import time

from logger import log
from shared_api import call_api
from utils import (
    load_config,
    encode_url,
    query_key,
    load_resume,
    resume_id_from_url,
    VACANCIES_FILE,
    load_vacancies,
    save_vacancies,
)
from filters import check_vacancy_relevance
from state_helper import load_state, save_state
from ui_helper import (
    print_warning,
    print_error,
    print_info,
    check_stop_key,
)

PER_PAGE = 100
MAX_PAGES = 20

MAX_SEARCH_CONSECUTIVE_FAILURES = 5
MAX_DETAILS_CONSECUTIVE_FAILURES = 5

PERIOD_LABEL = {
    1: "1 день",
    3: "3 дня",
    7: "7 дней",
    30: "30 дней",
    0: "все время",
}

AREA_LABEL = {
    1: "Москва",
    2: "Санкт-Петербург",
    3: "Екатеринбург",
    4: "Новосибирск",
    113: "Россия",
    1001: "Весь мир",
}

WORK_FORMAT_RU = {"REMOTE": "удаленно", "HYBRID": "гибрид", "ON_SITE": "офис"}


def _find_query(queries, query_id):
    for q in queries:
        if query_key(q) == query_id:
            return q
    return None


def _resolve_areas(formats, resume_data):
    result = []
    formats_set = set(formats)

    if "remote" in formats_set:
        result.append((1001, "Весь мир", ["REMOTE"]))

    local_formats = []
    if "hybrid" in formats_set:
        local_formats.append("HYBRID")
    if "office" in formats_set:
        local_formats.append("ON_SITE")

    if local_formats:
        city_id = (resume_data or {}).get("city_id")
        city_name = (resume_data or {}).get("city_name")

        if not city_id:
            print_warning(
                "Резюме не загружено (нет города). Ищу локальные вакансии "
                "по всей России. Запустите пункт 3 для загрузки резюме."
            )
            log.warning("vacancy_search: нет city_id, fallback 113")
            city_id = 113
            city_name = "Россия"

        if not city_name:
            city_name = AREA_LABEL.get(city_id, f"Регион {city_id}")

        result.append((city_id, city_name, local_formats))

    if not result:
        result.append((113, "Россия", ["REMOTE"]))

    return result


def search_page(
    text,
    area,
    min_salary,
    only_salary,
    work_formats,
    experiences,
    period,
    professional_roles,
    employments,
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
    for wf in work_formats:
        params.append(f"work_format={wf}")
    for exp in experiences:
        params.append(f"experience={exp}")
    for emp in employments:
        params.append(f"employment={emp}")
    for role_id in professional_roles:
        params.append(f"professional_role={role_id}")

    status, data = call_api(
        "/vacancies?" + "&".join(params),
        timeout=30,
        retry_with_captcha=True,
        network_retries=1,
    )
    if status == "timeout":
        log.error("API timeout при поиске вакансий")
        return None
    if status == "captcha":
        log.error("Captcha при поиске вакансий")
        return None
    if status != "ok" or not isinstance(data, dict):
        log.error(f"API ошибка поиска: {str(data)[:500]}")
        return None
    return data


def short_to_full(short):
    salary = short.get("salary") or {}
    emp = short.get("employer") or {}
    snippet = short.get("snippet") or {}
    desc_snippet = (
        (snippet.get("requirement") or "") + " " + (snippet.get("responsibility") or "")
    ).strip()

    area_id = (short.get("area") or {}).get("id")

    return {
        "id": int(short.get("id", 0)),
        "name": short.get("name"),
        "employer": emp.get("name"),
        "salary_from": salary.get("from"),
        "salary_to": salary.get("to"),
        "salary_currency": salary.get("currency"),
        "link": short.get("alternate_url"),
        "full_description": None,
        "snippet": desc_snippet,
        "published_at": short.get("published_at"),
        "area_id": str(area_id) if area_id else None,
        "work_formats": [wf.get("id") for wf in (short.get("work_format") or [])],
    }


def _load_missing_details(merged, need_details):
    print(f"Требуется догрузить описание: {len(need_details)}")
    print()

    consecutive_failures = 0
    stale_vids = set()

    try:
        for i, vid in enumerate(need_details, 1):
            print(f"  [{i}/{len(need_details)}] id={vid}...", end=" ", flush=True)
            st, data = call_api(
                f"/vacancies/{vid}",
                retry_with_captcha=True,
                timeout=30,
                network_retries=2,
            )
            if st == "ok" and isinstance(data, dict):
                merged[vid]["full_description"] = data.get("description", "")
                skills = data.get("key_skills") or []
                merged[vid]["key_skills"] = ", ".join(s.get("name", "") for s in skills)
                if not merged[vid].get("published_at"):
                    merged[vid]["published_at"] = data.get("published_at")

                area_id = (data.get("area") or {}).get("id")
                if area_id:
                    merged[vid]["area_id"] = str(area_id)
                work_formats = [wf.get("id") for wf in (data.get("work_format") or [])]
                if work_formats:
                    merged[vid]["work_formats"] = work_formats

                print("+")
                consecutive_failures = 0
            elif st == "captcha":
                print("!")
                consecutive_failures = 0
            else:
                err_msg = str(data).lower() if data else ""
                if "404" in err_msg or "not_found" in err_msg or "not found" in err_msg:
                    print("x")
                    stale_vids.add(vid)
                    consecutive_failures = 0
                elif st == "timeout" or (
                    st == "error"
                    and any(
                        m in err_msg
                        for m in (
                            "connection",
                            "max retries",
                            "ssl",
                            "timeouterror",
                            "connectionerror",
                        )
                    )
                ):
                    print("-")
                    consecutive_failures += 1
                    log.warning(
                        f"Догрузка {vid} не удалась (сетевая ошибка): {str(data)[:500]}, "
                        f"серия ошибок: {consecutive_failures}"
                    )
                    if consecutive_failures >= MAX_DETAILS_CONSECUTIVE_FAILURES:
                        save_vacancies(merged)
                        print()
                        print_error(
                            f"{consecutive_failures} подряд не удалось загрузить "
                            f"описания. Похоже, hh.ru недоступен. "
                            f"Останавливаюсь, прогресс сохранен."
                        )
                        log.error(
                            f"vacancy_search: остановка догрузки после "
                            f"{consecutive_failures} ошибок подряд"
                        )
                        return True
                else:
                    print("!")
                    consecutive_failures = 0
                    log.warning(
                        f"Догрузка {vid} не удалась (серверная ошибка): {str(data)[:500]}"
                    )
            if i % 50 == 0:
                save_vacancies(merged)
                print(" (сохранено)")
    except KeyboardInterrupt:
        save_vacancies(merged)
        print_warning("\nCtrl+C. Прогресс сохранен.")
        print_info("При следующем запуске догрузка продолжится.")
        return True

    if stale_vids:
        for vid in stale_vids:
            merged.pop(vid, None)
        save_vacancies(merged)
        print_info(f"Удалено из кэша (404 Not Found): {len(stale_vids)}")

    return False


def main():
    config = load_config()
    state = load_state()

    r_idx = state.get("current_resume_index", 0)
    if r_idx >= len(config["resumes"]):
        r_idx = 0
    resume_cfg = config["resumes"][r_idx]
    queries = resume_cfg.get("queries", [])
    if not queries:
        print_error("Нет запросов в конфиге. Настройте через пункт 1.")
        return

    query = _find_query(queries, state.get("current_query_id"))
    if not query:
        query = queries[0]
        state["current_query_id"] = query_key(query)
        save_state(state)
        print(f"Запрос не выбран, автоматически используется: {query['name']}")

    target_title_raw = (query.get("target_title") or "").strip()
    if not target_title_raw:
        print_error(
            "В текущем запросе не заданы слова для поиска в названии. "
            "Настройте через пункт 1."
        )
        log.error("vacancy_search: пустой target_title")
        return

    resume_id = resume_id_from_url(resume_cfg["url"])
    resume_data = load_resume(resume_id) or {}

    existing = load_vacancies()
    print(f"Существующих вакансий в базе: {len(existing)}")
    print(f"РЕЗЮМЕ #{r_idx + 1} | Запрос: {query['name']}")

    all_new = {}
    kw = target_title_raw.replace("|", " OR ")
    excl_words = query.get("exclude_words") or []
    core_kws = query.get("core_keywords") or []
    roles = query.get("professional_roles") or []

    formats = query.get("work_formats") or ["remote"]
    employments = query.get("employments") or ["full", "part", "project"]
    experiences = query.get("experiences") or ["between1And3"]
    periods = query.get("periods") or [0]

    areas = _resolve_areas(formats, resume_data)

    stopped = False
    consecutive_failures = 0

    for area_id, area_label, hh_formats in areas:
        if stopped:
            break
        formats_ru = ", ".join(WORK_FORMAT_RU.get(f, f) for f in hh_formats)
        print(f"\nРегион поиска: {area_label} (формат: {formats_ru})")
        log.info(f"vacancy_search: area={area_id} ({area_label}), formats={hh_formats}")

        for period in periods:
            if stopped:
                break
            period_ru = PERIOD_LABEL.get(period, f"{period} дней")
            print(f"  Поиск вакансий за период: {period_ru}...", end=" ", flush=True)

            period_ok = False
            for page in range(MAX_PAGES):
                if check_stop_key():
                    print("\n  Остановка по команде '0'.")
                    stopped = True
                    break
                data = search_page(
                    kw,
                    area_id,
                    query.get("min_salary", 0),
                    query.get("only_with_salary", False),
                    hh_formats,
                    experiences,
                    period,
                    roles,
                    employments,
                    page,
                )
                if not data:
                    break
                period_ok = True
                items = data.get("items", [])
                if not items:
                    break

                for s in items:
                    v = short_to_full(s)
                    if check_vacancy_relevance(
                        v["name"],
                        v.get("snippet", ""),
                        target_title_raw,
                        excl_words,
                        core_kws,
                    ):
                        all_new[v["id"]] = v

                if page + 1 >= data.get("pages", 0):
                    break
                time.sleep(0.5)

            print(f"найдено {len(all_new)} (всего)")

            if period_ok:
                consecutive_failures = 0
            else:
                consecutive_failures += 1
                log.warning(
                    f"Поиск (area={area_id}, period={period}) без результата, "
                    f"серия ошибок: {consecutive_failures}"
                )
                if consecutive_failures >= MAX_SEARCH_CONSECUTIVE_FAILURES:
                    print_error(
                        f"{consecutive_failures} запросов подряд не удалось. "
                        f"Похоже, hh.ru недоступен. Останавливаюсь."
                    )
                    log.error(
                        f"vacancy_search: остановка поиска после "
                        f"{consecutive_failures} ошибок подряд"
                    )
                    stopped = True
                    break

    print(f"\nВсего уникальных подходящих вакансий: {len(all_new)}")
    merged = dict(existing)
    truly_new = 0

    for vid, v in all_new.items():
        if vid not in existing:
            merged[vid] = v
            truly_new += 1
        elif v.get("published_at") and not existing[vid].get("published_at"):
            merged[vid] = {**existing[vid], "published_at": v["published_at"]}

    print(f"Новых вакансий: {truly_new}")

    if stopped:
        save_vacancies(merged)
        print_warning(
            "Поиск остановлен: hh.ru недоступен. Прогресс сохранен. "
            "Попробуйте позже."
        )
        return

    need_details = [
        vid for vid in merged if not merged.get(vid, {}).get("full_description")
    ]

    if need_details:
        interrupted = _load_missing_details(merged, need_details)
        if interrupted:
            return

    total = save_vacancies(merged)
    print(f"\nВсего вакансий в базе: {total}")
    log.info(
        f"Сбор завершен: новых={truly_new}, " f"всего={total}, query={query_key(query)}"
    )


if __name__ == "__main__":
    main()
