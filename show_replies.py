"""
Выгружает из БД только те переписки, где ответил работодатель.
"""

from db import get_connection


def main():
    conn = get_connection()
    cur = conn.cursor()

    # Берем последнее сообщение от работодателя для каждого отклика
    query = """
    WITH LastEmployerMsg AS (
        SELECT 
            m.negotiation_id,
            m.text,
            m.created_at,
            ROW_NUMBER() OVER(PARTITION BY m.negotiation_id ORDER BY m.created_at DESC) as rn
        FROM messages m
        WHERE m.author_id != 'applicant'
    )
    SELECT 
        v.name AS vacancy_name,
        v.employer,
        lem.text,
        lem.created_at,
        n.id AS neg_id
    FROM LastEmployerMsg lem
    JOIN negotiations n ON lem.negotiation_id = n.id
    JOIN vacancies v ON n.vacancy_id = v.id
    WHERE lem.rn = 1
    ORDER BY lem.created_at DESC;
    """

    cur.execute(query)
    rows = cur.fetchall()

    print(f"{'=' * 80}")
    print(f"Найдено диалогов с ответами работодателей: {len(rows)}")
    print(f"{'=' * 80}\n")

    for row in rows:
        name, employer, text, created_at, neg_id = row
        date_str = created_at.strftime("%d.%m.%Y %H:%M") if created_at else "Неизвестно"

        print(f"📅 {date_str} | 🏢 {employer}")
        print(f"💼 Вакансия: {name}")
        print(f"🔗 Ссылка: https://hh.ru/applicant/negotiations/{neg_id}")
        print(f"💬 Сообщение: {text}")
        print("-" * 80)

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
