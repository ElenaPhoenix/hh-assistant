import os
import json
import warnings
import numpy as np
import argparse

# Подавляем технический мусор от HuggingFace и токенизаторов
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
os.environ["TOKENIZERS_PARALLELISM"] = "false"
warnings.filterwarnings("ignore")
from transformers import logging as hf_logging

hf_logging.set_verbosity_error()

from sentence_transformers import CrossEncoder
from state_helper import (
    load_state,
    save_state,
    get_processed_ids,
    add_processed_ids,
    set_phase,
)
from utils import (
    load_config,
    load_resume,
    clean_text,
    normalize,
    resume_id_from_url,
    MATCHES_DIR,
    RESUMES_DIR,
    DATA_DIR,
)
from filters import check_name_filters

VACANCIES_FILE = os.path.join(DATA_DIR, "vacancies_detailed.json")
CROSS_ENCODER = "DiTy/cross-encoder-russian-msmarco"
SIGMOID_CENTER = 0.80
SIGMOID_TEMPERATURE = 0.04


def load_vacancies():
    with open(VACANCIES_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


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
        except Exception:
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

    if not resume_skills:
        # Если API не отдал навыки, вытаскиваем их из конфига
        resume_skills = (
            config["resumes"][config_index]
            .get("queries", [{}])[0]
            .get("core_keywords", [])
        )

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

        # Жесткий фильтр: проверяем только название и стоп-слова
        if not check_name_filters(name, query["target_title"], query["exclude_words"]):
            continue

        filtered.append(v)

    print(f"Резюме ID: {resume_id}")
    print(f"Всего вакансий в базе: {len(vacancies)}")
    print(f"Новых вакансий для оценки (после фильтрации по названию): {len(filtered)}")

    if not filtered:
        print("Нет новых вакансий.")
        return None

    print("\nЗагружаем нейросеть для оценки релевантности...")
    cross = CrossEncoder(CROSS_ENCODER)

    vac_texts = [
        clean_text(
            f"{v.get('name')} {v.get('employer')} {v.get('full_description')} {v.get('key_skills')}"
        )
        for v in filtered
    ]
    pairs = [[resume_text, t] for t in vac_texts]

    print("Оцениваем совпадение (это может занять несколько минут)...")
    # Встроенный прогресс-бар, максимально быстрый
    cross_raw = cross.predict(pairs, show_progress_bar=True)

    results = []
    for i, v in enumerate(filtered):
        base = calibrate_score(cross_raw[i])

        # Мягкая проверка core_keywords (второй эшелон)
        desc_norm = normalize(v.get("full_description") or "")
        core_kws = query.get("core_keywords", [])
        penalty = 1.0

        if core_kws:
            has_core = any(normalize(kw) in desc_norm for kw in core_kws)
            has_skill = any(normalize(s) in desc_norm for s in resume_skills)

            # Если нейросеть дала высокий балл, но в описании нет ключевых слов — слегка штрафуем
            if not has_core and not has_skill and base > 70:
                penalty = 0.85

        final_score = base * penalty

        results.append(
            {
                "id": v.get("id"),
                "name": v.get("name"),
                "employer": v.get("employer"),
                "link": v.get("link"),
                "match_score": round(final_score, 1),
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
    resume_id = resume_id_from_url(resume_url)

    if not os.path.exists(os.path.join(RESUMES_DIR, f"{resume_id}.json")):
        print("Резюме не распарсено.")
        return
    match_resume(resume_id, idx)


if __name__ == "__main__":
    main()
