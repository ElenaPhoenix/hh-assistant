import json
import os
import argparse
from shared_api import call_api
from utils import load_config, resume_id_from_url, clean_text, RESUMES_DIR
from state_helper import load_state, save_state, set_phase, set_resume_meta


def _build_candidate_name(first, last):
    first = (first or "").strip()
    last = (last or "").strip()
    if first and last:
        return f"{first} {last}"
    if first:
        return first
    if last:
        return last
    return ""


def parse_resume_via_api(resume_id):
    print(f"Загружаем резюме с hh.ru...")
    status, data = call_api(f"/resumes/{resume_id}")

    if status != "ok" or not isinstance(data, dict):
        print("Не удалось получить резюме с hh.ru.")
        return None

    text_parts = []
    title = data.get("title", "Без названия")
    text_parts.append(f"Должность: {title}")

    # Пол из резюме hh: {"gender": {"id": "female", "name": "Женщина"}}
    gender_data = data.get("gender") or {}
    gender_id = gender_data.get("id")  # "male" / "female" / None
    gender_name = gender_data.get("name")  # "Мужчина" / "Женщина" / None
    if gender_name:
        text_parts.append(f"Пол: {gender_name}")

    for exp in data.get("experience", []):
        company = exp.get("company", "Неизвестно")
        position = exp.get("position", "")
        desc = exp.get("description", "")
        text_parts.append(f"Компания: {company}\nДолжность: {position}\n{desc}")
    skills = data.get("key_skills", [])
    if skills:
        skill_names = [s.get("name") for s in skills]
        text_parts.append(f"Навыки: {', '.join(skill_names)}")
    full_text = "\n\n".join(text_parts)
    area_data = data.get("area") or {}
    city_id = area_data.get("id")
    city_name = area_data.get("name")
    first_name = (data.get("first_name") or "").strip()
    last_name = (data.get("last_name") or "").strip()
    candidate_name = _build_candidate_name(first_name, last_name)
    return {
        "title": title,
        "full_text": clean_text(full_text),
        "url": f"https://hh.ru/resume/{resume_id}",
        "resume_id": resume_id,
        "key_skills": [s.get("name") for s in skills],
        "city_id": city_id,
        "city_name": city_name,
        "candidate_name": candidate_name,
        "first_name": first_name,
        "last_name": last_name,
        "middle_name": (data.get("middle_name") or "").strip(),
        "gender": gender_id,
        "gender_name": gender_name,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--index", type=int, default=None)
    args = parser.parse_args()
    config = load_config()
    idx = args.index if args.index is not None else 0
    resume_url = config["resumes"][idx]["url"]
    resume_id = resume_id_from_url(resume_url)
    result = parse_resume_via_api(resume_id)
    if not result:
        return
    os.makedirs(RESUMES_DIR, exist_ok=True)
    out_path = os.path.join(RESUMES_DIR, f"{resume_id}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    state = load_state()
    set_resume_meta(state, resume_id, url=resume_url, title=result["title"])
    set_phase(state, resume_id, "parsed")
    save_state(state)
    print("Резюме успешно загружено и сохранено.")
    if result.get("candidate_name"):
        print(f"Кандидат: {result['candidate_name']}")
    else:
        print("ВНИМАНИЕ: не удалось получить имя кандидата. Письма будут без подписи.")
    if result.get("city_name"):
        print(f"Город: {result['city_name']}")
    if result.get("gender_name"):
        print(f"Пол: {result['gender_name']}")


if __name__ == "__main__":
    main()
