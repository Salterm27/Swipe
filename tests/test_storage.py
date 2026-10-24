"""Project files, listing, the static page and the smaller endpoints."""

import json
import os
import sqlite3

import pytest

import app as swipe
from helpers import LIST, decide, ids_by_name, make


def test_formats_endpoint_lists_every_parser(client):
    ids = [f["id"] for f in client.get("/api/formats").get_json()]
    assert ids == list(swipe.parsers.FORMATS)


def test_index_is_served_uncached(client):
    r = client.get("/")
    assert r.status_code == 200 and b"<title>Swipe</title>" in r.data
    assert r.headers["Cache-Control"] == "no-cache"


def test_project_list_is_newest_first_and_trimmed(client, monkeypatch):
    stamps = iter(["2026-01-01T00:00:00+00:00", "2026-02-01T00:00:00+00:00"] + ["2026-03-01T00:00:00+00:00"] * 20)
    monkeypatch.setattr(swipe, "now", lambda: next(stamps))
    old = make(client)["id"]
    new = make(client)["id"]
    listed = client.get("/api/projects").get_json()
    assert [p["id"] for p in listed] == [new, old]
    assert "fields" not in listed[0] and "rounds" not in listed[0]


def test_each_project_file_is_self_contained(client):
    pid = make(client)["id"]
    con = sqlite3.connect(os.path.join(swipe.DATA_DIR, f"project-{pid}.db"))
    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"meta", "items", "rounds", "round_items", "decisions"} <= tables
    assert con.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 3
    con.close()


def test_failed_create_leaves_no_file_behind(client, monkeypatch):
    def boom(*_a, **_k):
        raise RuntimeError("disk full")
    monkeypatch.setattr(swipe, "import_records", boom)
    swipe.app.config["PROPAGATE_EXCEPTIONS"] = False
    try:
        r = client.post("/api/projects", json={"name": "x", "text": LIST})
    finally:
        swipe.app.config["PROPAGATE_EXCEPTIONS"] = None
    assert r.status_code == 500
    assert [f for f in os.listdir(swipe.DATA_DIR) if f.endswith(".db")] == []


def test_key_field_null_means_match_whole_record(client):
    p = make(client, text="id,name\n1,A\n1,A\n2,B", key_field=None)
    assert p["key_field"] is None and p["item_count"] == 2   # exact duplicate rows collapse
    p = make(client, text="id,name\n1,A\n2,B", key_field="ghost")
    assert p["key_field"] is None


def test_items_filter_by_choice_and_none(client):
    pid = make(client)["id"]
    ids = ids_by_name(client, pid)
    decide(client, pid, ids["Chair"], "right")
    get = lambda c: [i["data"]["name"] for i in client.get(f"/api/projects/{pid}/items?choice={c}").get_json()["items"]]  # noqa: E731
    assert get("right") == ["Chair"]
    assert get("none") == ["Table", "Lamp"]
    assert get("left") == []


def test_decisions_only_apply_to_the_current_round(client):
    pid = make(client)["id"]
    ids = ids_by_name(client, pid)
    decide(client, pid, ids["Chair"], "right")
    decide(client, pid, ids["Table"], "left")
    client.post(f"/api/projects/{pid}/rounds", json={"carry": ["right"]})
    r = client.post(f"/api/projects/{pid}/decisions", json={"item_id": ids["Table"], "choice": "right"})
    assert r.status_code == 404      # Table didn't make it into round 2


def test_round_note_and_round_list(client):
    pid = make(client)["id"]
    decide(client, pid, ids_by_name(client, pid)["Chair"], "right")
    p = client.post(f"/api/projects/{pid}/rounds", json={"note": "shortlist"}).get_json()["project"]
    assert [(r["number"], r["note"], r["total"]) for r in p["rounds"]] == [(1, "", 3), (2, "shortlist", 1)]


def test_past_round_items_show_history_only_from_before_them(client):
    pid = make(client)["id"]
    ids = ids_by_name(client, pid)
    decide(client, pid, ids["Chair"], "right")
    client.post(f"/api/projects/{pid}/rounds", json={"carry": ["right"]})
    decide(client, pid, ids["Chair"], "left")
    r1 = client.get(f"/api/projects/{pid}/items?round=1").get_json()["items"]
    chair = next(i for i in r1 if i["id"] == ids["Chair"])
    assert chair["choice"] == "right" and chair["history"] == []
    r2 = client.get(f"/api/projects/{pid}/items?round=2").get_json()["items"]
    assert r2[0]["history"] == [{"round": 1, "choice": "right"}] and r2[0]["choice"] == "left"


@pytest.mark.parametrize("name,slug", [("Viajes 2027!", "viajes-2027"), ("✨✨", "swipe")])
def test_export_filename_slug(client, name, slug):
    pid = client.post("/api/projects", json={"name": name, "text": "a"}).get_json()["id"]
    assert f'"{slug}.csv"' in client.get(f"/api/projects/{pid}/export").headers["Content-Disposition"]


def test_export_keeps_unicode_and_quotes(client):
    pid = make(client, text='name,note\n"Café, Paris","He said ""hi""\nthen left"')["id"]
    body = client.get(f"/api/projects/{pid}/export").get_data(as_text=True)
    assert body.startswith("﻿")              # BOM so Excel reads UTF-8
    assert '"Café, Paris"' in body and '"He said ""hi""\nthen left"' in body


def test_old_default_colours_follow_the_new_theme(client):
    pid = make(client)["id"]
    con = sqlite3.connect(os.path.join(swipe.DATA_DIR, f"project-{pid}.db"))
    old = {"left": {"label": "Nope", "icon": "✕", "color": "#e5484d"},
           "right": {"label": "Yes", "icon": "✓", "color": "#3ecf8e"},
           "unsure": {"label": "Hmm", "icon": "?", "color": "#123456"}}   # a colour someone picked
    with con:
        con.execute("UPDATE meta SET value = ? WHERE key = 'choices'", (json.dumps(old),))
    con.close()
    c = client.get(f"/api/projects/{pid}").get_json()["choices"]
    assert (c["left"]["color"], c["right"]["color"], c["unsure"]["color"]) == ("#b0604a", "#1f4a35", "#123456")
    assert c["left"]["label"] == "Nope"


def test_item_fields_keep_the_lists_order(client):
    pid = make(client, text="zeta,alpha,mid\n1,2,3")["id"]
    item = client.get(f"/api/projects/{pid}/items").get_json()["items"][0]
    assert list(item["data"]) == ["zeta", "alpha", "mid"]
