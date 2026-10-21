from shared_api import call_api
import time


def main():
    print("Запрашиваем 3 отклика для теста...")
    status, data = call_api("/negotiations?per_page=3")
    if status != "ok" or not isinstance(data, dict):
        print("Не удалось получить список откликов.")
        return

    items = data.get("items", [])
    for item in items:
        neg_id = item.get("id")
        state = (item.get("state") or {}).get("id")
        vacancy = (item.get("vacancy") or {}).get("name", "Неизвестно")[:30]

        print(f"\n--- Отклик ID: {neg_id} | Статус: {state} | Вакансия: {vacancy} ---")

        st, msg_data = call_api(f"/negotiations/{neg_id}/messages")
        print(f"Статус API: {st}")
        print(f"Данные от API:\n{msg_data}")
        time.sleep(0.5)


if __name__ == "__main__":
    main()
