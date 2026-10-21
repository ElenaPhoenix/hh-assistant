import json
import os
import re
import numpy as np
import argparse
from sentence_transformers import CrossEncoder
from state_helper import (
    load_state,
    save_state,
    get_processed_ids,
    add_processed_ids,
    set_phase,
)
from filters import check_filters

CONFIG_FILE = "config.json"
DATA_DIR = "data"
RESUMES_DIR = os.path.join(DATA_DIR, "resumes")
MATCHES_DIR = os.path.join(DATA_DIR, "matches")
VACANCIES_FILE = os.path.join(DATA_DIR, "vacancies_detailed.json")

CROSS_ENCODER = "DiTy/cross-encoder-russian-msmarco"
SIGMOID_CENTER = 0.80
SIGMOID_TEMPERATURE = 0.04


def load_config():
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def load_resume(resume_id):
    with open(
        os.path.join(RESUMES_DIR, f"{resume_id}.json"), "r", encoding="utf-8"
    ) as f:
        return json.load(f)


def load_vacancies():
    with open(VACANCIES_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def clean_text(text):
    return re.sub(r"\s+", " ", text).strip() if text else ""


def calibrate_score(cross_raw):
    return float(
        100 / (1 + np.exp(-((cross_raw - SIGMOID_CENTER) / SIGMOID_TEMPERATURE)))
    )


def _merge_matches(matches_file, new_results, threshold):
    existing_all, existing_passed = {}, {}
    if os.path.exists(matches_file):
        try:
            with open(matches_file, "r", encoding="utf-8") as f:
                old = json.load(f)
            for v in old.get("all", []):
                existing_all[v["id"]] = v
            for v in old.get("passed", []):
                existing_passed[v["id"]] = v
        except:
            pass
    for r in new_results:
        existing_all[r["id"]] = r
        if r["match_score"] >= threshold:
            existing_passed[r["id"]] = r
    return (
        sorted(
            existing_all.values(), key=lambda x: x.get("match_score", 0), reverse=True
        ),
        sorted(
            existing_passed.values(),
            key=lambda x: x.get("match_score", 0),
            reverse=True,
        ),
    )


def match_resume(resume_id, config_index):
    config = load_config()
    resume_data = load_resume(resume_id)
    vacancies = load_vacancies()
    state = load_state()

    resume_text = clean_text(resume_data["full_text"])
    resume_skills = resume_data.get("key_skills", [])
    if isinstance(resume_skills, str):
        resume_skills = [s.strip() for s in resume_skills.split(",")]

    threshold = config["threshold"]
    resume_params = config["resumes"][config_index]
    queries = resume_params.get("queries", [])
    query = (
        queries[0]
        if queries
        else {"target_title": "аналитик", "exclude_words": [], "core_keywords": []}
    )

    processed_ids = get_processed_ids(state, resume_id)
    filtered = []

    for v in vacancies:
        if v.get("id") in processed_ids:
            continue
        name = v.get("name") or ""
        desc = v.get("full_description") or ""

        # Используем общую функцию фильтрации
        if not check_filters(
            name,
            desc,
            query["target_title"],
            query["exclude_words"],
            query.get("core_keywords", []),
            resume_skills,
        ):
            continue
        filtered.append(v)

    print(f"Резюме ID: {resume_id}")
    print(f"Всего вакансий в базе: {len(vacancies)}")
    print(f"Новых вакансий для оценки (после фильтрации): {len(filtered)}")

    if not filtered:
        print("Нет новых вакансий.")
        return None

    print(f"\nЗагружаем cross-encoder: {CROSS_ENCODER}")
    cross = CrossEncoder(CROSS_ENCODER)

    vac_texts = [
        clean_text(
            f"{v.get('name')} {v.get('employer')} {v.get('full_description')} {v.get('key_skills')}"
        )
        for v in filtered
    ]
    pairs = [[resume_text, t] for t in vac_texts]
    cross_raw = np.array(cross.predict(pairs, show_progress_bar=True))

    results = []
    for i, v in enumerate(filtered):
        base = calibrate_score(cross_raw[i])
        results.append(
            {
                "id": v.get("id"),
                "name": v.get("name"),
                "employer": v.get("employer"),
                "link": v.get("link"),
                "match_score": round(base, 1),
                "base_score": round(base, 1),
                "cross_raw": round(float(cross_raw[i]), 3),
                "salary_from": v.get("salary_from"),
                "salary_to": v.get("salary_to"),
                "key_skills_tags": v.get("key_skills"),
                "resume_id": resume_id,
            }
        )

    results.sort(key=lambda x: x["match_score"], reverse=True)
    matches_file = os.path.join(MATCHES_DIR, f"{resume_id}.json")
    final_all, final_passed = _merge_matches(matches_file, results, threshold)

    with open(matches_file, "w", encoding="utf-8") as f:
        json.dump(
            {"all": final_all, "passed": final_passed}, f, ensure_ascii=False, indent=2
        )

    add_processed_ids(state, resume_id, [v["id"] for v in filtered])
    set_phase(state, resume_id, "matched")
    save_state(state)

    print(f"\n{'=' * 70}")
    print(f"Всего проверено: {len(results)}")
    print(
        f"Прошли порог {threshold}%: {sum(1 for r in results if r['match_score'] >= threshold)}"
    )
    print(f"Всего passed (в базе): {len(final_passed)}")
    print(f"{'=' * 70}\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--index", type=int, default=None)
    args = parser.parse_args()
    state = load_state()
    config = load_config()
    idx = args.index if args.index is not None else state.get("current_resume_index", 0)

    if idx >= len(config["resumes"]):
        return
    resume_url = config["resumes"][idx]["url"]
    match = re.search(r"/resume/([a-f0-9]+)", resume_url)
    if not match:
        return
    resume_id = match.group(1)

    if not os.path.exists(os.path.join(RESUMES_DIR, f"{resume_id}.json")):
        print("Резюме не распарсено.")
        return
    match_resume(resume_id, idx)


if __name__ == "__main__":
    main()
