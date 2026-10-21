# HH Assistant: ETL & AI-Pipeline для автоматизации поиска работы

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-15%2B-336791.svg)](https://www.postgresql.org/)
[![GigaChat](https://img.shields.io/badge/AI-GigaChat_API-orange.svg)](https://developers.sber.ru/)
[![HuggingFace](https://img.shields.io/badge/NLP-CrossEncoder-yellow.svg)](https://huggingface.co/DiTy/cross-encoder-russian-msmarco)

## О проекте

**HH Assistant** — это end-to-end (сквозной) ETL-пайплайн и AI-ассистент, разработанный для автоматизации рутинных процессов поиска работы. Проект решает проблему "холодных" откликов, автоматизируя сбор вакансий, семантический анализ текста, генерацию персонализированных писем и трекинг обратной связи от HR.

## Ключевой функционал (Features)

- **Data Ingestion (Сбор данных):** Использование мобильного API hh.ru (через `hh-applicant-tool`) для обхода ограничений антибот-систем (Group-IB). Умный парсинг с учетом пагинации, периодов публикации и опыта работы.
- **NLP & Semantic Search:** Использование `Cross-Encoder` (модель `DiTy/cross-encoder-russian-msmarco`) для точной семантической оценки релевантности резюме и вакансии. Быстрая предфильтрация на основе `RapidFuzz` и кастомных стоп-слов.
- **LLM Generation:** Интеграция с **GigaChat REST API** для генерации уникальных, коротких и адаптивных сопроводительных писем.
- **Data Engineering (PostgreSQL):** Проектирование и поддержка реляционной базы данных. Пайплайн ETL для синхронизации вакансий, откликов и переписки с рекрутерами (таблицы: `vacancies`, `negotiations`, `messages`, `resumes`).
- **Token Rate-Limit Management:** Умный контроль токенов LLM с автоматическим переключением на fallback-шаблон при достижении критического минимума.
- **Concurrent Processing:** Безопасная многопоточная обработка (ThreadPool) для асинхронного сбора ответов от HR без риска блокировки аккаунта.

## 🏗 Архитектура проекта

1. `vacancy_search.py` — Парсинг вакансий (ETL Extract).
2. `matcher.py` — Предфильтрация + ML-скоринг.
3. `apply_via_api.py` — Генерация писем и отправка откликов (Act).
4. `check_messages.py` / `sync_negotiations.py` — Синхронизация данных с БД PostgreSQL (Load).
5. `db.py` — Управление схемой данных и подключением.

## 🚀 Установка и запуск

```bash
# 1. Клонировать репозиторий
git clone https://github.com/ElenaPhoenix/hh-assistant.git
cd hh-assistant

# 2. Установить зависимости
pip install -r requirements.txt

# 3. Настроить .env (ключи hh и GigaChat)
# 4. Запустить
python main.py
```
