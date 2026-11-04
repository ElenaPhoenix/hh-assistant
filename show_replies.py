from db import get_connection, tables_ready
from ui_helper import print_info, print_warning


def main():
    if not tables_ready():
        print_warning("Таблицы в БД не созданы. Запустите пункт 6.")
        return

    try:
        conn = get_connection()
    except Exception as e:
        print_warning(f"Нет подключения к PostgreSQL: {e}")
        return

    cur = conn.cursor()
    cur.execute("""
        WITH LastEmployerMsg AS (
            SELECT m.negotiation_id, m.text, m.created_at,
                   ROW_NUMBER() OVER(
                       PARTITION BY m.negotiation_id
                       ORDER BY m.created_at DESC NULLS LAST
                   ) as rn
            FROM messages m
            WHERE m.author_id != 'applicant'
        ),
        Recent10 AS (
            SELECT v.name, v.employer, lem.text, lem.created_at, n.id
            FROM LastEmployerMsg lem
            JOIN negotiations n ON lem.negotiation_id = n.id
            JOIN vacancies v ON n.vacancy_id = v.id
            WHERE lem.rn = 1
            ORDER BY lem.created_at DESC NULLS LAST
            LIMIT 10
        )
        SELECT name, employer, text, created_at, id
        FROM Recent10
        ORDER BY created_at ASC NULLS LAST;
    """)
    rows = cur.fetchall()
    cur.close()
    conn.close()

    if not rows:
        print_warning(
            "Переписок с ответами работодателей нет.\n"
            "Если ожидались ответы - запустите пункт 6 (синхронизация), затем снова пункт 10."
        )
        return

    print_info(
        f"\nПоследние {len(rows)} переписок с ответами работодателей (от старых к новым):\n"
    )

    for row in rows:
        name, employer, text, created_at, neg_id = row
        date_str = (
            created_at.strftime("%d.%m.%Y %H:%M") if created_at else "дата неизвестна"
        )
        print(f"📅 {date_str} | 🏢 {employer}")
        print(f"💼 {name}")
        print(f"🔗 https://hh.ru/applicant/negotiations/{neg_id}")
        print(f"💬 {text or '(пусто)'}")
        print("-" * 80)


if __name__ == "__main__":
    main()
