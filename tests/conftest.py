import uuid
import pytest
import logging


@pytest.fixture
def random_string():
    def _gen():
        return uuid.uuid4().hex

    return _gen


@pytest.fixture
def random_vacancy_name():
    def _gen():
        return f"V_{uuid.uuid4().hex[:12]}"

    return _gen


@pytest.fixture
def random_id():
    def _gen():
        return uuid.uuid4().int % 1_000_000

    return _gen


@pytest.fixture
def mock_vacancy_data():
    return {
        "id": 123456,
        "name": "Python Developer",
        "employer": "Test Corp",
        "full_description": "Требуется Python, SQL, знание Linux.",
        "key_skills": "Python, SQL",
        "match_score": 85,
        "link": "https://hh.ru/vacancy/123456",
    }


@pytest.fixture
def temp_env(tmp_path, monkeypatch):
    """Изолирует файловую систему для тестов.
    Все пути из utils и logger перенаправляются во временную папку.
    """
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    monkeypatch.setattr("utils.DATA_DIR", str(data_dir))
    monkeypatch.setattr(
        "utils.VACANCIES_FILE", str(data_dir / "vacancies_detailed.json")
    )
    monkeypatch.setattr("utils.CONFIG_FILE", str(data_dir / "config.json"))
    monkeypatch.setattr("utils.STATE_FILE", str(data_dir / "state.json"))
    monkeypatch.setattr("utils.LEGACY_SETTINGS_FILE", str(data_dir / "settings.json"))
    monkeypatch.setattr(
        "utils.LEGACY_SETTINGS_ROOT", str(tmp_path / "settings_root.json")
    )
    monkeypatch.setattr("utils.RESUMES_DIR", str(data_dir / "resumes"))
    monkeypatch.setattr("utils.MATCHES_DIR", str(data_dir / "matches"))
    monkeypatch.setattr("utils.LETTERS_DIR", str(data_dir / "letters"))
    monkeypatch.setattr("utils.FIXED_LETTER_FILE", str(data_dir / "fixed_letter.txt"))

    monkeypatch.setattr("state_helper.STATE_FILE", str(data_dir / "state.json"))

    monkeypatch.setattr("logger.LOG_FILE", str(data_dir / "app.log"))
    logger = logging.getLogger("hh_assistant")
    logger.handlers.clear()

    return data_dir
