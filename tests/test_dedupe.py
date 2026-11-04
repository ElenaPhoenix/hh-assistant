from dedupe import dedupe_passed


def test_dedupe_random(random_string, random_id):
    id1, id2 = random_id(), random_id()
    e, n = random_string(), random_string()
    s = random_id()
    passed = [
        {"id": id1, "employer": e, "name": n, "match_score": s},
        {"id": id2, "employer": e, "name": n, "match_score": s},
    ]
    result = dedupe_passed(passed)
    assert len(result) == 1
    assert result[0]["id"] == id1


def test_dedupe_keeps_different(random_string, random_id):
    id1, id2 = random_id(), random_id()
    e1, e2 = random_string(), random_string()
    n, s = random_string(), random_id()
    passed = [
        {"id": id1, "employer": e1, "name": n, "match_score": s},
        {"id": id2, "employer": e2, "name": n, "match_score": s},
    ]
    result = dedupe_passed(passed)
    assert len(result) == 2
