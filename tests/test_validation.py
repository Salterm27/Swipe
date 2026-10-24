"""Bad input must come back as a 400/404 with a JSON message, never a 500.
Every case here returned a 500 (a traceback in the journal) before."""

import pytest

from helpers import make


@pytest.fixture()
def pid(client):
    return make(client)["id"]


@pytest.mark.parametrize("method,path,body", [
    ("post", "/api/parse", [1, 2]),
    ("post", "/api/parse", {"text": 5}),
    ("post", "/api/parse", {"text": "a", "format": ["csv"]}),
    ("post", "/api/projects", {"name": "x", "text": "a", "choices": "red"}),
    ("post", "/api/projects", {"name": "x", "text": "a", "choices": {"left": "x"}}),
    ("post", "/api/projects", {"name": "x", "text": "a", "mapping": "title"}),
    ("post", "/api/projects", {"name": "x", "text": "a", "mapping": {"gallery": "name"}}),
    ("patch", "/api/projects/{pid}", {"mapping": ["a"]}),
    ("patch", "/api/projects/{pid}", {"choices": {"right": {"color": "green"}}}),
    ("patch", "/api/projects/{pid}", "just a string"),
    ("post", "/api/projects/{pid}/rounds", {"carry": "right"}),
    ("post", "/api/projects/{pid}/rounds", {"text": 5}),
    ("post", "/api/projects/{pid}/import", {"text": ["a"]}),
    ("post", "/api/projects/{pid}/decisions", {"item_id": "1x", "choice": "left"}),
    ("post", "/api/projects/{pid}/decisions", [1]),
])
def test_bad_input_is_a_json_400(client, pid, method, path, body):
    r = getattr(client, method)(path.format(pid=pid), json=body)
    assert r.status_code == 400, r.get_data(as_text=True)
    assert r.is_json and r.get_json()["error"]


def test_bad_limit_falls_back_to_default(client, pid):
    r = client.get(f"/api/projects/{pid}/queue?limit=abc")
    assert r.status_code == 200 and len(r.get_json()["items"]) == 3
    assert len(client.get(f"/api/projects/{pid}/queue?limit=0").get_json()["items"]) == 1
    assert len(client.get(f"/api/projects/{pid}/queue?limit=9999").get_json()["items"]) == 3


def test_api_404s_are_json_but_pages_are_not(client, pid):
    r = client.get("/api/nope")
    assert r.status_code == 404 and r.get_json() == {"error": "not found"}
    assert client.get(f"/api/projects/{pid}/items?round=7").status_code == 404
    r = client.get("/nope.html")
    assert r.status_code == 404 and not r.is_json


def test_wrong_method_is_json(client):
    r = client.delete("/api/parse")
    assert r.status_code == 405 and r.is_json


def test_empty_body_is_treated_as_empty_object(client, pid):
    assert client.post("/api/projects", data="").status_code == 400          # name required
    assert client.post(f"/api/projects/{pid}/rounds", data="").status_code == 400  # empty round


def test_internal_errors_never_leak_their_message(client, monkeypatch):
    import app as swipe

    def boom(*_a, **_k):
        raise ValueError("secret internal detail")
    monkeypatch.setattr(swipe.parsers, "guess_mapping", boom)
    swipe.app.config["PROPAGATE_EXCEPTIONS"] = False
    try:
        r = client.post("/api/projects", json={"name": "x", "text": "a\nb"})
    finally:
        swipe.app.config["PROPAGATE_EXCEPTIONS"] = None
    assert r.status_code == 500
    assert b"secret" not in r.data
