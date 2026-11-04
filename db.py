"""
Модуль для работы с PostgreSQL.
"""

import os
import psycopg2
from contextlib import contextmanager
from dotenv import load_dotenv

load_dotenv()


def get_connection():
    host = os.getenv("DB_HOST")
    port = os.getenv("DB_PORT")
    dbname = os.getenv("DB_NAME")
    user = os.getenv("DB_USER")
    password = os.getenv("DB_PASSWORD")

    if not all([host, port, dbname, user, password]):
        raise ValueError(
            "Ошибка конфигурации БД: не заданы переменные в .env "
            "(DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD)"
        )

    return psycopg2.connect(
        host=host, port=port, dbname=dbname, user=user, password=password
    )


@contextmanager
def db_cursor():
    """Контекстный менеджер для безопасной работы с БД.

    Автоматически делает commit при успехе, rollback при ошибке
    и закрывает соединение.
    """
    conn = None
    cur = None
    try:
        conn = get_connection()
        cur = conn.cursor()
        yield cur
        conn.commit()
    except Exception:
        if conn is not None:
            try:
                conn.rollback()
            except Exception:
                pass
        raise
    finally:
        if cur is not None:
            try:
                cur.close()
            except Exception:
                pass
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def init_db():
    """Создает таблицы (если их нет) и обновляет схему при необходимости."""
    with db_cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS resumes (
                id TEXT PRIMARY KEY, title TEXT, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS vacancies (
                id BIGINT PRIMARY KEY, name TEXT, employer TEXT, salary_from INT,
                salary_to INT, salary_currency TEXT, link TEXT, full_description TEXT
            );
        """)
        # Добавляем новые колонки, если их еще нет
        cur.execute("ALTER TABLE vacancies ADD COLUMN IF NOT EXISTS area_id TEXT;")
        cur.execute("ALTER TABLE vacancies ADD COLUMN IF NOT EXISTS work_formats TEXT;")

        cur.execute("""
            CREATE TABLE IF NOT EXISTS negotiations (
                id BIGINT PRIMARY KEY, vacancy_id BIGINT REFERENCES vacancies(id),
                resume_id TEXT REFERENCES resumes(id), status TEXT, 
                hh_updated_at TEXT, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        cur.execute(
            "ALTER TABLE negotiations ALTER COLUMN hh_updated_at TYPE TEXT USING hh_updated_at::text;"
        )
        cur.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id BIGINT PRIMARY KEY, negotiation_id BIGINT REFERENCES negotiations(id),
                author_id TEXT, text TEXT, created_at TIMESTAMP
            );
        """)


def tables_ready():
    """Проверка, что все нужные таблицы существуют и доступны."""
    try:
        with db_cursor() as cur:
            for table in ("resumes", "vacancies", "negotiations", "messages"):
                cur.execute(f"SELECT 1 FROM {table} LIMIT 1;")
        return True
    except Exception:
        return False


if __name__ == "__main__":
    init_db()
