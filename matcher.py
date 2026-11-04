import os
import json
import hashlib
import warnings
import argparse

os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
os.environ["TOKENIZERS_PARALLELISM"] = "false"
warnings.filterwarnings("ignore")
from transformers import logging as hf_logging

hf_logging.set_verbosity_error()

from logger import log
from state_helper import (
    load_state,
    save_state,
    get_processed_ids,
    add_processed_ids,
    set_phase,
    get_applied_ids,
    get_resume_state,
)
from utils import (
    load_config,
    load_resume,
    resume_id_from_url,
    query_key,
    MATCHES_DIR,
    RESUMES_DIR,
    load_vacancies,
    atomic_write_json,
    DEFAULT_THRESHOLD,
)
from filters import check_vacancy_relevance
from dedupe import dedupe_passed
from ui_helper import print_info

TITLE_HIT_SCORE = 40
KEYWORD_HIT_SCORE = 5
KEYWORD_HIT_CAP = 60


def _check_vacancy_area(vacancy, query, resume_data):
    """Проверяет, подходит ли вакансия по городу и формату работы."""
    user_formats = query.get("work_formats") or ["remote"]
    user_city = str(resume_data.get("city_id") or "")
    vac_area = str(vacancy.get("area_id") or "")
    vac_formats = vacancy.get("work_formats") or []

    # 1. Если формат неизвестен (старые данные) - ПРИНИМАЕМ.
    if not vac_formats:
        return True

    # 2. Если это удаленка
    if "REMOTE" in vac_formats:
        if "remote" in user_formats:
            return True

    # 3. Если это офис/гибрид
    if "HYBRID" in vac_formats or "ON_SITE" in vac_formats:
        if "hybrid" in user_formats or "office" in user_formats:
            # Если у вакансии нет города - ПРИНИМАЕМ
            if not vac_area:
                return True
            return vac_area == user_city

    return False


def _query_hash(query, threshold, resume_data):
    """Вычисляет хэш конфигурации запроса.

    Включает гео-параметры (форматы работы и город резюме), чтобы
    при их изменении матчер автоматически запускал полный пересчет.
    """
    payload = json.dumps(
        {
            "target_title": query.get("target_title", ""),
            "exclude_words": sorted(query.get("exclude_words") or []),
            "core_keywords": sorted(query.get("core_keywords") or []),
            "work_formats": sorted(query.get("work_formats") or []),
            "threshold": float(threshold),
            "city_id": str(resume_data.get("city_id") or ""),
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.md5(payload.encode("utf-8")).hexdigest()[:12]


def _compute_rules_score(vacancy, query):
    name_l = (vacancy.get("name") or "").lower()
    desc_l = (
        (vacancy.get("full_description") or "")
        + " "
        + (vacancy.get("key_skills") or "")
    ).lower()
    targets = [
        t.strip().lower() for t in query.get("target_title", "").split("|") if t.strip()
    ]
    matched_targets = [t for t in targets if t in name_l]
    title_hits = len(matched_targets)

    if title_hits == 0:
        return 0, {
            "title_hits": 0,
            "kw_hits": 0,
            "matched_targets": [],
            "reason": "no_title",
        }

    core_keywords = query.get("core_keywords") or []
    matched_kws = [kw for kw in core_keywords if kw.lower() in desc_l]
    kw_hits = len(matched_kws)

    if kw_hits == 0:
        return 0, {
            "title_hits": title_hits,
            "kw_hits": 0,
            "matched_targets": matched_targets,
            "reason": "no_kw",
        }

    title_score = TITLE_HIT_SCORE
    kw_score = min(KEYWORD_HIT_CAP, kw_hits * KEYWORD_HIT_SCORE)
    total = min(100, title_score + kw_score)
    return total, {
        "title_hits": title_hits,
        "kw_hits": kw_hits,
        "matched_targets": matched_targets,
        "reason": "ok",
    }


def _read_matches(matches_file):
    if not os.path.exists(matches_file):
        return {}, {}, {}
    try:
        with open(matches_file, "r", encoding="utf-8") as f:
            old = json.load(f)
    except Exception as e:
        log.warning(f"Не удалось прочитать matches.json: {e}")
        return {}, {}, {}
    if not isinstance(old, dict):
        return {}, {}, {}
    all_list = old.get("all", [])
    passed_list = old.get("passed", [])
    if not isinstance(all_list, list) or not isinstance(passed_list, list):
        return {}, {}, {}
    try:
        all_dict = {(v["id"], v.get("query_id", "default")): v for v in all_list}
        passed_dict = {(v["id"], v.get("query_id", "default")): v for v in passed_list}
    except (KeyError, TypeError):
        return {}, {}, {}
    query_hashes = old.get("query_hashes", {})
    if not isinstance(query_hashes, dict):
        query_hashes = {}
    return all_dict, passed_dict, query_hashes


def _write_matches(matches_file, all_dict, passed_dict, query_hashes):
    os.makedirs(MATCHES_DIR, exist_ok=True)
    payload = {
        "query_hashes": query_hashes,
        "all": sorted(
            all_dict.values(), key=lambda x: x.get("match_score", 0), reverse=True
        ),
        "passed": sorted(
            passed_dict.values(), key=lambda x: x.get("match_score", 0), reverse=True
        ),
    }
    atomic_write_json(matches_file, payload)


def _matches_any_query(name, description, queries):
    for query in queries:
        if check_vacancy_relevance(
            name,
            description,
            query.get("target_title", ""),
            query.get("exclude_words", []),
            query.get("core_keywords", []),
        ):
            return True
    return False


def _get_aggregated_skills(resume_data, queries):
    skills = set(resume_data.get("key_skills", []) or [])
    for query in queries:
        for kw in query.get("core_keywords", []):
            skills.add(kw)
    return list(skills)


def _print_score_histogram(results, threshold):
    buckets = [
        (0, 20),
        (20, 40),
        (40, 50),
        (50, 60),
        (60, 65),
        (65, 70),
        (70, 80),
        (80, 90),
        (90, 101),
    ]
    print_info(f"Распределение оценки соответствия (всего {len(results)}):")
    max_cnt = max(
        [sum(1 for r in results if lo <= r["match_score"] < hi) for lo, hi in buckets]
        + [1]
    )
    for lo, hi in buckets:
        cnt = sum(1 for r in results if lo <= r["match_score"] < hi)
        bar_len = int(40 * cnt / max_cnt)
        bar = "#" * bar_len
        marker = "  <-- порог" if lo <= threshold < hi else ""
        print(f"  [{lo:3d}-{hi - 1:3d}]: {cnt:5d}  {bar}{marker}")


def _finalize(
    state,
    resume_id,
    qid,
    checked_ids,
    query_hashes,
    current_hash,
    matches_file,
    existing_all,
    existing_passed,
):
    query_hashes[qid] = current_hash
    _write_matches(matches_file, existing_all, existing_passed, query_hashes)
    add_processed_ids(state, resume_id, qid, checked_ids)
    set_phase(state, resume_id, "matched")
    save_state(state)


def _cleanup_orphans(
    state, resume_id, query_hashes, existing_all, existing_passed, valid_qids
):
    all_orphans = {k[1] for k in existing_all.keys() if k[1] not in valid_qids}
    passed_orphans = {k[1] for k in existing_passed.keys() if k[1] not in valid_qids}
    hash_orphans = {qid for qid in query_hashes.keys() if qid not in valid_qids}
    orphans = all_orphans | passed_orphans | hash_orphans

    if orphans:
        for oqid in orphans:
            query_hashes.pop(oqid, None)
        existing_all = {k: v for k, v in existing_all.items() if k[1] in valid_qids}
        existing_passed = {
            k: v for k, v in existing_passed.items() if k[1] in valid_qids
        }
        log.info(f"Matcher: удалены orphan qid из matches.json: {sorted(orphans)}")

    rs = get_resume_state(state, resume_id)
    processed = rs.get("processed_vacancy_ids", {})
    state_orphans = [k for k in list(processed.keys()) if k not in valid_qids]
    if state_orphans:
        for k in state_orphans:
            del processed[k]
        save_state(state)
        log.info(f"Matcher: удалены orphan qid из state.json: {state_orphans}")

    return bool(orphans or state_orphans), existing_all, existing_passed


def _cleanup_stale_processed(state, resume_id, qid, processed_ids, vacancies):
    if not processed_ids:
        return 0
    stale = set()
    for vid in processed_ids:
        v = vacancies.get(vid)
        if v and not v.get("full_description"):
            stale.add(vid)
    if not stale:
        return 0
    rs = get_resume_state(state, resume_id)
    current = rs["processed_vacancy_ids"].get(qid, [])
    rs["processed_vacancy_ids"][qid] = [vid for vid in current if vid not in stale]
    save_state(state)
    processed_ids -= stale
    log.info(
        f"Matcher: снята отметка 'processed' с {len(stale)} вакансий без "
        f"full_description (будут пересчитаны после догрузки)"
    )
    return len(stale)


def match_resume(resume_id, config_index, query_id=None):
    config = load_config()
    resume_data = load_resume(resume_id)
    vacancies = load_vacancies()
    state = load_state()

    threshold = float(config.get("threshold", DEFAULT_THRESHOLD))

    queries = config["resumes"][config_index].get("queries", [])
    if not queries:
        print("В конфиге нет запросов.")
        return

    query = None
    if query_id:
        for q in queries:
            if query_key(q) == query_id:
                query = q
                break
    if not query:
        query = queries[0]
    qid = query_key(query)
    qname = query["name"]

    # Передаем resume_data в хэш, чтобы изменение города триггерило пересчет
    current_hash = _query_hash(query, threshold, resume_data)
    matches_file = os.path.join(MATCHES_DIR, f"{resume_id}.json")
    existing_all, existing_passed, query_hashes = _read_matches(matches_file)

    valid_qids = {query_key(q) for q in queries}
    cleaned, existing_all, existing_passed = _cleanup_orphans(
        state, resume_id, query_hashes, existing_all, existing_passed, valid_qids
    )
    if cleaned:
        _write_matches(matches_file, existing_all, existing_passed, query_hashes)

    is_current = query_hashes.get(qid) == current_hash

    if not is_current:
        if qid in query_hashes:
            print_info(
                f"Конфиг запроса '{qname}' изменился - полный пересчет этого запроса."
            )
        elif os.path.exists(matches_file):
            print_info(
                f"Запрос '{qname}' новый (или формат файла результатов устарел) - "
                f"полный пересчет."
            )
        log.info(f"Matcher: полный пересчет qid={qid}, query_hash={current_hash}")

        existing_all = {k: v for k, v in existing_all.items() if k[1] != qid}
        existing_passed = {k: v for k, v in existing_passed.items() if k[1] != qid}
        processed_ids = set()
    else:
        processed_ids = get_processed_ids(state, resume_id, qid)
        _cleanup_stale_processed(state, resume_id, qid, processed_ids, vacancies)

    applied_global = get_applied_ids(state, resume_id)

    filtered = []
    checked_ids = []
    skipped_applied = 0
    skipped_no_description = 0
    skipped_area = 0

    for v in vacancies.values():
        vid = v.get("id")
        if vid in processed_ids:
            continue

        if not _check_vacancy_area(v, query, resume_data):
            skipped_area += 1
            continue

        if not v.get("full_description"):
            skipped_no_description += 1
            continue

        checked_ids.append(vid)
        if vid in applied_global:
            skipped_applied += 1
            continue
        if check_vacancy_relevance(
            v.get("name") or "",
            v.get("full_description") or "",
            query.get("target_title", ""),
            query.get("exclude_words") or [],
            query.get("core_keywords") or [],
        ):
            filtered.append(v)

    print(f"Резюме: {resume_id} | Запрос: {qname} (код: {qid})")
    print(f"Всего вакансий в базе: {len(vacancies)}")
    print(f"Проверено сейчас (новых для запроса): {len(checked_ids)}")
    if skipped_no_description:
        print(
            f"Пропущено (нет описания, будут обработаны после догрузки): "
            f"{skipped_no_description}"
        )
    if skipped_area:
        print(f"Пропущено (не подходит город/формат работы): " f"{skipped_area}")
    print(f"Уже откликались (пропуск): {skipped_applied}")
    print(f"Прошли предварительный фильтр: {len(filtered)}")
    print(f"Порог соответствия: {threshold}")
    log.info(
        f"Матчинг: query={qid}, checked={len(checked_ids)}, "
        f"skipped_no_description={skipped_no_description}, "
        f"skipped_area={skipped_area}, "
        f"filtered={len(filtered)}, skipped_applied={skipped_applied}, "
        f"query_hash={current_hash}, is_current={is_current}"
    )

    if not filtered:
        print("Нет вакансий для оценки после предварительного фильтра.")
        if checked_ids:
            _finalize(
                state,
                resume_id,
                qid,
                checked_ids,
                query_hashes,
                current_hash,
                matches_file,
                existing_all,
                existing_passed,
            )
            print_info("Состояние сохранено, при следующем запуске пересчета не будет.")
        return

    print("\nОценка соответствия...")
    candidates = []
    skipped_no_title = 0
    skipped_no_kw = 0

    for v in filtered:
        score, meta = _compute_rules_score(v, query)
        if meta["reason"] == "no_title":
            skipped_no_title += 1
        elif meta["reason"] == "no_kw":
            skipped_no_kw += 1
        else:
            candidates.append((v, score, meta))

    print_info(f"Отсеяно (нет слов из названия в заголовке): {skipped_no_title}")
    print_info(f"Отсеяно (нет ключевых слов в описании): {skipped_no_kw}")
    print_info(f"Кандидатов на оценку: {len(candidates)}")
    log.info(
        f"Матчинг: skipped_no_title={skipped_no_title}, "
        f"skipped_no_kw={skipped_no_kw}, candidates={len(candidates)}"
    )

    if not candidates:
        print("Нет кандидатов после оценки.")
        _finalize(
            state,
            resume_id,
            qid,
            checked_ids,
            query_hashes,
            current_hash,
            matches_file,
            existing_all,
            existing_passed,
        )
        print_info("Состояние сохранено, при следующем запуске пересчета не будет.")
        return

    results = []
    for v, score, meta in candidates:
        results.append(
            {
                "id": v.get("id"),
                "name": v.get("name"),
                "employer": v.get("employer"),
                "link": v.get("link"),
                "match_score": round(score, 1),
                "title_hits": meta["title_hits"],
                "kw_hits": meta["kw_hits"],
                "matched_targets": meta["matched_targets"],
                "query_id": qid,
                "query_name": qname,
                "resume_id": resume_id,
            }
        )

    _print_score_histogram(results, threshold)

    passed_raw = [r for r in results if r["match_score"] >= threshold]
    passed_raw.sort(key=lambda x: x["match_score"], reverse=True)
    passed_unique = dedupe_passed(passed_raw)
    passed_ids = {r["id"] for r in passed_unique}

    print_info(
        f"\nПрошли порог: {len(passed_raw)}, "
        f"после удаления дублей: {len(passed_unique)}"
    )
    log.info(
        f"Matcher: threshold={threshold}, passed_raw={len(passed_raw)}, "
        f"passed_unique={len(passed_unique)}"
    )

    for r in results:
        key = (r["id"], r["query_id"])
        existing_all[key] = r
        if r["id"] in passed_ids:
            existing_passed[key] = r

    _finalize(
        state,
        resume_id,
        qid,
        checked_ids,
        query_hashes,
        current_hash,
        matches_file,
        existing_all,
        existing_passed,
    )

    print(f"\n{'=' * 70}")
    print(f"Проверено сейчас: {len(checked_ids)}")
    print(f"Уже откликались (пропуск): {skipped_applied}")
    print(f"Отсеяно (нет слов из названия в заголовке): {skipped_no_title}")
    print(f"Отсеяно (нет ключевых слов в описании): {skipped_no_kw}")
    print(f"Всего проверено: {len(results)}")
    print(f"Прошли порог: {len(passed_raw)}")
    print(f"После удаления дублей: {len(passed_unique)}")
    print(f"{'=' * 70}\n")
    log.info(
        f"Матчинг завершен: checked={len(checked_ids)}, "
        f"skipped_applied={skipped_applied}, "
        f"skipped_no_title={skipped_no_title}, "
        f"skipped_no_kw={skipped_no_kw}, "
        f"passed_raw={len(passed_raw)}, passed_unique={len(passed_unique)}"
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--index", type=int, default=None)
    args = parser.parse_args()
    state = load_state()
    config = load_config()

    idx = args.index if args.index is not None else 0
    if idx >= len(config["resumes"]):
        return

    resume_url = config["resumes"][idx]["url"]
    resume_id = resume_id_from_url(resume_url)

    if not os.path.exists(os.path.join(RESUMES_DIR, f"{resume_id}.json")):
        print("Резюме не загружено. Запустите пункт 3.")
        return

    match_resume(resume_id, idx, state.get("current_query_id"))


if __name__ == "__main__":
    main()
