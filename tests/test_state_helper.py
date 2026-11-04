from state_helper import (
    load_state,
    save_state,
    get_resume_state,
    add_applied_id,
    add_denied_id,
    add_needs_test,
    mark_denied,
    reset_processed,
    reset_applied,
    reset_denied,
    reset_needs_test,
    reset_all,
)


def test_state_operations(temp_env):
    state = load_state()
    rid = "test_resume"

    rs = get_resume_state(state, rid)
    assert rs["phase"] == "not_started"

    add_applied_id(state, rid, 100)
    add_denied_id(state, rid, 200)
    add_needs_test(state, rid, {"id": 300, "name": "Test"})
    save_state(state)

    state = load_state()
    rs = get_resume_state(state, rid)
    assert 100 in rs["applied_vacancy_ids"]
    assert 200 in rs["denied_vacancy_ids"]
    assert len(rs["needs_test"]) == 1

    # mark_denied должен убрать из needs_test
    mark_denied(state, rid, 300)
    rs = get_resume_state(state, rid)
    assert 300 in rs["denied_vacancy_ids"]
    assert len(rs["needs_test"]) == 0


def test_reset_functions(temp_env):
    state = load_state()
    rid = "test_resume"

    add_applied_id(state, rid, 100)
    add_denied_id(state, rid, 200)
    add_needs_test(state, rid, {"id": 300, "name": "Test"})

    rs = get_resume_state(state, rid)
    rs["processed_vacancy_ids"]["q1"] = [400, 500]
    save_state(state)

    # Проверка reset_processed
    reset_processed(state, rid, "q1")
    rs = get_resume_state(state, rid)
    assert len(rs["processed_vacancy_ids"]["q1"]) == 0

    # Проверка reset_applied
    reset_applied(state, rid)
    rs = get_resume_state(state, rid)
    assert len(rs["applied_vacancy_ids"]) == 0

    # Проверка reset_denied
    reset_denied(state, rid)
    rs = get_resume_state(state, rid)
    assert len(rs["denied_vacancy_ids"]) == 0

    # Проверка reset_needs_test
    reset_needs_test(state, rid)
    rs = get_resume_state(state, rid)
    assert len(rs["needs_test"]) == 0

    # Проверка reset_all
    rs["processed_vacancy_ids"]["q1"] = [400]
    add_applied_id(state, rid, 100)
    add_denied_id(state, rid, 200)
    add_needs_test(state, rid, {"id": 300})
    reset_all(state, rid)
    rs = get_resume_state(state, rid)
    assert len(rs["processed_vacancy_ids"]) == 0
    assert len(rs["applied_vacancy_ids"]) == 0
    assert len(rs["denied_vacancy_ids"]) == 0
    assert len(rs["needs_test"]) == 0
