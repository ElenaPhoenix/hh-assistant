"""
Модуль для работы с PostgreSQL.
Создает таблицы и предоставляет подключение.
"""

import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()


def get_connection():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=os.getenv("DB_PORT", "5433"),
        dbname=os.getenv("DB_NAME", "hh_vacancies"),
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASSWORD", ""),
    )


def init_db():
    conn = get_connection()
    cur = conn.cursor()

    print("Очищаем старые таблицы...")
    # Удаляем старый мусор
    cur.execute("""
        DROP TABLE IF EXISTS applications CASCADE;
        DROP TABLE IF EXISTS applied_vacancies CASCADE;
        DROP TABLE IF EXISTS vacancies CASCADE;
        DROP TABLE IF EXISTS negotiations CASCADE;
        DROP TABLE IF EXISTS letters CASCADE;
        DROP TABLE IF EXISTS messages CASCADE;
        DROP TABLE IF EXISTS resumes CASCADE;
    """)

    print("Создаем новые таблицы...")

    # 1. Резюме (пока просто для связи)
    cur.execute("""
        CREATE TABLE resumes (
            id TEXT PRIMARY KEY,
            title TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    # 2. Вакансии (храним базовую инфу и полное описание)
    cur.execute("""
        CREATE TABLE vacancies (
            id BIGINT PRIMARY KEY,
            name TEXT,
            employer TEXT,
            salary_from INT,
            salary_to INT,
            salary_currency TEXT,
            link TEXT,
            full_description TEXT
        );
    """)

    # 3. Отклики (здесь правильный PK - id отклика на hh)
    cur.execute("""
        CREATE TABLE negotiations (
            id BIGINT PRIMARY KEY,
            vacancy_id BIGINT REFERENCES vacancies(id),
            resume_id TEXT REFERENCES resumes(id),
            status TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    # 4. Сообщения (чат)
    cur.execute("""
        CREATE TABLE messages (
            id BIGINT PRIMARY KEY,
            negotiation_id BIGINT REFERENCES negotiations(id),
            author_id TEXT,
            text TEXT,
            created_at TIMESTAMP
        );
    """)

    conn.commit()
    cur.close()
    conn.close()
    print("База данных успешно инициализирована.")


if __name__ == "__main__":
    init_db()
