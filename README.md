# HH Assistant: ETL & AI-Pipeline для автоматизации поиска работы

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-15%2B-336791.svg)](https://www.postgresql.org/)
[![GigaChat](https://img.shields.io/badge/AI-GigaChat_API-orange.svg)](https://developers.sber.ru/)
[![HuggingFace](https://img.shields.io/badge/NLP-CrossEncoder-yellow.svg)](https://huggingface.co/DiTy/cross-encoder-russian-msmarco)

## О проекте
**HH Assistant** — это end-to-end (сквозной) ETL-пайплайн и AI-ассистент, разработанный для автоматизации рутинных процессов поиска работы. Проект решает проблему "холодных" откликов, автоматизируя сбор вакансий, семантический анализ текста, генерацию персонализированных писем и трекинг обратной связи от HR. 
Это **pet-проект**, демонстрирующий навыки построения данных (Data Engineering), работы с NLP и интеграции с LLM.

## Ключевой функционал (Features)
*   **Data Ingestion (Сбор данных):** Использование мобильного API hh.ru (через `hh-applicant-tool`) для обхода ограничений антибот-систем. Умный парсинг с учетом пагинации, периодов публикации и фильтрации по опыту работы (один, несколько или все варианты).
*   **NLP & Semantic Search:** Использование `Cross-Encoder` (модель `DiTy/cross-encoder-russian-msmarco`) для точной семантической оценки релевантности резюме и вакансии. Быстрая предфильтрация на основе `RapidFuzz` и кастомных стоп-слов.
*   **LLM Generation:** Интеграция с **GigaChat REST API** для генерации уникальных, коротких и адаптивных сопроводительных писем.
*   **Data Engineering (PostgreSQL):** Проектирование и поддержка реляционной базы данных. Пайплайн ETL для синхронизации вакансий, откликов и переписки с рекрутерами (таблицы: `vacancies`, `negotiations`, `messages`, `resumes`).
*   **Token Rate-Limit Management:** Умный контроль токенов LLM с автоматическим переключением на fallback-шаблон (`fixed_letter.txt`) при достижении критического минимума.
*   **Concurrent Processing:** Безопасная многопоточная обработка (`ThreadPoolExecutor`) для асинхронного сбора ответов от HR без риска блокировки аккаунта.

## Архитектура проекта
Проект построен по модульному принципу. Ниже — полная структура рабочих файлов.

hh-assistant/
├── main.py                # Оркестратор (главное меню)
├── config.py              # Интерактивная настройка config.json
├── filters.py             # Логика фильтрации (Fuzzy, стоп-слова)
├── vacancy_search.py      # Сбор вакансий через API hh
├── matcher.py             # Семантический скоринг (Cross-Encoder)
├── apply_via_api.py       # Генерация писем и отправка откликов
├── check_messages.py      # Выгрузка переписки с HR в БД (многопоточность)
├── sync_negotiations.py   # Синхронизация всех откликов с hh
├── show_replies.py        # Просмотр ответов HR из БД
├── db.py                  # Подключение и схема PostgreSQL
├── save_to_db.py          # ETL: загрузка JSON-данных в БД
├── shared_api.py          # Обертка над hh API, GigaChat и токенами
├── dedupe.py              # Утилита дедупликации
├── resume_parser.py       # Парсинг резюме (Playwright, fallback)
├── state_helper.py        # Управление state.json
│
├── .env                   # Секреты (НЕ коммитится в Git)
├── .env.example           # Шаблон для секретов (для других разработчиков)
├── .gitignore             # Исключения для Git
├── config.json            # Настройки поиска (ключевые слова, фильтры)
├── state.json             # Прогресс (applied, denied, needs_test)
├── requirements.txt       # Зависимости проекта (pip install -r)
├── README.md              # Документация проекта
│
└── data/                  # Папка с данными (НЕ коммитится в Git)
    ├── vacancies_detailed.json
    ├── fixed_letter.txt
    ├── resumes/           # Кэш распарсенных резюме
    ├── matches/           # Результаты скоринга
    └── letters/           # Логи отправленных писем

## Установка и запуск
1. **Клонировать репозиторий:**
git clone https://github.com/ElenaPhoenix/hh-assistant.git
cd hh-assistant

2. **Создать виртуальное окружение и установить зависимости:**
python -m venv venv
source venv/Scripts/activate  # Windows
pip install -r requirements.txt

3. **Настроить переменные окружения:**
Скопируй .env.example в .env и заполни своими данными:

cp .env.example .env

**Внутри .env должно быть:**
# --- hh.ru ---
HH_LOGIN=твой_номер_телефона_без_плюса
HH_PASSWORD=твой_пароль_от_hh

# --- GigaChat (Base64 от Client_ID:Client_Secret) ---
GIGACHAT_AUTH_KEY=твой_длинный_base64_ключ_из_личного_кабинета_sber

# --- PostgreSQL ---
DB_HOST=localhost
DB_PORT=твой_порт
DB_NAME=hh_vacancies
DB_USER=postgres
DB_PASSWORD=твой_пароль_от_базы

4. **Инициализировать базу данных (опционально):**
python db.py  # создаст таблицы
python save_to_db.py  # загрузит существующие JSON в БД

5. **Запустить главное меню:**
python main.py

## Технические решения (Why I Built It This Way)
**Почему мобильное API hh, а не Playwright?** 
Прямой парсинг через браузер блокируется Group-IB (антибот hh). Мобильное API (hh-applicant-tool) позволяет обходить эти ограничения и работает стабильнее.

**Почему Cross-Encoder, а не обычные эмбеддинги?** 
Cross-Encoder обрабатывает пару «резюме-вакансия» одновременно, что дает более точную семантическую оценку релевантности, чем косинусное сходство между отдельными векторами.

**Зачем RapidFuzz перед ML?** 
Это быстрый предфильтр. Отсеивается 90% мусора (стоп-слова, нерелевантные названия) до того, как запускать тяжелую нейросеть. Это экономит время и ресурсы CPU.

**Как решена проблема с токенами GigaChat?** 
В shared_api.py перехватывается заголовок x-ratelimit-remaining. При достижении порога в 1000 токенов скрипт автоматически переключается на фиксированное письмо из data/fixed_letter.txt.

## Автор
Елена Малоросиянцева
GitHub: ElenaPhoenix
Резюме-сайт: elenaphoenix.github.io/cv
Telegram: @yeganebirlane
Email: latikayegane@yandex.ru
Mob.: +79163266925

*Pet-проект, разработанный как демонстрация навыков работы с API, базами данных, NLP и AI-инструментами.*