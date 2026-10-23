import time
import random
from concurrent.futures import ThreadPoolExecutor, as_completed
from shared_api import call_api
from db import get_connection


def fetch_and_save_messages(neg_id):
    time.sleep(random.uniform(0.1, 0.3))
    status, msg_data = call_api(f"/negotiations/{neg_id}/messages")
    if status != "ok" or not isinstance(msg_data, dict):
        return 0, 0

    items = msg_data.get("items", [])
    new_count = 0
    if not items:
        return 0, 0

    conn = get_connection()
    cur = conn.cursor()
    for m in items:
        msg_id = m.get("id")
        p_type = (m.get("author") or {}).get("participant_type", "")
        text = m.get("text") or ""
        created_at = m.get("created_at")
        if not msg_id:
            continue
        cur.execute(
            """
            INSERT INTO messages (id, negotiation_id, author_id, text, created_at)
            VALUES (%s, %s, %s, %s, %s) ON CONFLICT (id) DO NOTHING;
        """,
            (msg_id, neg_id, p_type, text, created_at),
        )
        if cur.rowcount > 0:
            new_count += 1
    cur.close()
    conn.close()
    return new_count, len(items)


def main():
    print("Подключаемся к базе данных...")
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT n.id, v.name, v.employer FROM negotiations n JOIN vacancies v ON n.vacancy_id = v.id WHERE n.status IN ('active', 'invited', 'response')"
    )
    active_negs = cur.fetchall()
    cur.close()
    conn.close()

    print(f"Найдено активных откликов: {len(active_negs)}")
    print("Запускаем параллельную выгрузку (3 потока)...\n")

    total_new = 0
    completed = 0
    with ThreadPoolExecutor(max_workers=3) as executor:
        future_to_neg = {
            executor.submit(fetch_and_save_messages, neg[0]): neg for neg in active_negs
        }
        for future in as_completed(future_to_neg):
            neg_id, vacancy_name, employer = future_to_neg[future]
            completed += 1
            try:
                new_count, total_msgs = future.result()
                if new_count > 0:
                    total_new += new_count
                    print(
                        f"[{completed}/{len(active_negs)}] {vacancy_name[:30]}... (+{new_count} сообщ.)"
                    )
                else:
                    if completed % 20 == 0:
                        print(f"[{completed}/{len(active_negs)}] Обработано...")
            except Exception as exc:
                print(f"[{completed}/{len(active_negs)}] Ошибка: {exc}")

    print(
        f"\n{'=' * 50}\nВсего новых сообщений добавлено в БД: {total_new}\n{'=' * 50}"
    )


if __name__ == "__main__":
    main()
