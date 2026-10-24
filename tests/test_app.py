"""API tests: run with  python -m pytest tests/ -v  (needs requirements-dev.txt)."""

import csv
import io
import json
import os

import app as swipe
from helpers import LIST, decide, ids_by_name, make, queue


def test_health(client):
    assert client.get("/api/health").get_json() == {"ok": True}


def test_parse_preview_is_stateless(client):
    r = client.post("/api/parse", json={"text": LIST}).get_json()
    assert r["format"] == "csv" and r["count"] == 3
    assert r["mapping"]["title"] == "name" and r["key_field"] == "id"
    assert client.get("/api/projects").get_json() == []
    assert client.post("/api/parse", json={"text": ""}).status_code == 400


def test_create_project_writes_its_own_db_file(client):
    p = make(client)
    assert os.path.exists(os.path.join(swipe.DATA_DIR, f"project-{p['id']}.db"))
    assert p["item_count"] == 3 and p["key_field"] == "id"
    assert p["round"]["number"] == 1 and p["round"]["total"] == 3
    assert p["choices"]["right"] == {"label": "Yes", "icon": "✓", "color": "#1f4a35"}
    assert p["mapping"]["title"] == "name"


def test_custom_choices_and_validation(client):
    p = make(client, choices={"right": {"label": "Keep", "icon": "❤️", "color": "#FF0000"}})
    assert p["choices"]["right"] == {"label": "Keep", "icon": "❤️", "color": "#ff0000"}
    assert p["choices"]["left"]["label"] == "No"
    bad = client.post("/api/projects", json={"name": "x", "text": "a", "choices": {"left": {"color": "red"}}})
    assert bad.status_code == 400
    assert client.post("/api/projects", json={"text": "a"}).status_code == 400


def test_explicit_mapping_drops_unknown_fields(client):
    p = make(client, mapping={"title": "price", "subtitle": "nope", "image": "id", "gallery": ["name", "ghost", "id"]})
    assert p["mapping"]["title"] == "price" and p["mapping"]["subtitle"] is None
    assert p["mapping"]["gallery"] == ["name"]   # unknown dropped, and the main image isn't repeated
    assert p["mapping"]["highlight"] is None


def test_projects_listing_ignores_backup_snapshots(client):
    p = make(client)
    src = os.path.join(swipe.DATA_DIR, f"project-{p['id']}.db")
    with open(src, "rb") as f, open(os.path.join(swipe.DATA_DIR, f"project-{p['id']}.bak.db"), "wb") as out:
        out.write(f.read())
    assert [x["id"] for x in client.get("/api/projects").get_json()] == [p["id"]]


def test_unknown_project_is_404(client):
    assert client.get("/api/projects/000000000000").status_code == 404
    assert client.get("/api/projects/../../etc").status_code == 404


def test_swipe_through_a_round(client):
    pid = make(client)["id"]
    q = queue(client, pid)
    assert [i["data"]["name"] for i in q["items"]] == ["Chair", "Table", "Lamp"]
    decide(client, pid, q["items"][0]["id"], "right")
    stats = decide(client, pid, q["items"][1]["id"], "left")
    assert stats["decided"] == 2 and stats["remaining"] == 1
    assert [i["data"]["name"] for i in queue(client, pid)["items"]] == ["Lamp"]
    stats = decide(client, pid, q["items"][2]["id"], "unsure")
    assert stats["counts"] == {"left": 1, "right": 1, "unsure": 1}
    assert queue(client, pid)["items"] == []


def test_decision_validation(client):
    pid = make(client)["id"]
    item = queue(client, pid)["items"][0]["id"]
    assert client.post(f"/api/projects/{pid}/decisions", json={"item_id": item, "choice": "maybe"}).status_code == 400
    assert client.post(f"/api/projects/{pid}/decisions", json={"choice": "left"}).status_code == 400
    assert client.post(f"/api/projects/{pid}/decisions", json={"item_id": 999, "choice": "left"}).status_code == 404


def test_changing_a_decision_replaces_it(client):
    pid = make(client)["id"]
    item = queue(client, pid)["items"][0]["id"]
    decide(client, pid, item, "left")
    stats = decide(client, pid, item, "right")
    assert stats["decided"] == 1 and stats["counts"]["right"] == 1


def test_undo_takes_back_the_latest_decision(client):
    pid = make(client)["id"]
    ids = ids_by_name(client, pid)
    decide(client, pid, ids["Chair"], "right")
    decide(client, pid, ids["Table"], "left")
    decide(client, pid, ids["Chair"], "unsure")      # re-deciding counts as the latest action
    r = client.post(f"/api/projects/{pid}/undo").get_json()
    assert r["item"]["data"]["name"] == "Chair" and r["stats"]["decided"] == 1
    r = client.post(f"/api/projects/{pid}/undo").get_json()
    assert r["item"]["data"]["name"] == "Table"
    assert client.post(f"/api/projects/{pid}/undo").status_code == 404


def test_next_round_carries_chosen_piles_and_keeps_history(client):
    pid = make(client)["id"]
    ids = ids_by_name(client, pid)
    decide(client, pid, ids["Chair"], "right")
    decide(client, pid, ids["Table"], "left")
    decide(client, pid, ids["Lamp"], "unsure")
    r = client.post(f"/api/projects/{pid}/rounds", json={})
    assert r.status_code == 201
    assert r.get_json()["project"]["round"]["number"] == 2
    q = queue(client, pid)
    assert q["round"] == 2
    assert {i["data"]["name"]: i["history"] for i in q["items"]} == {
        "Chair": [{"round": 1, "choice": "right"}],
        "Lamp": [{"round": 1, "choice": "unsure"}],
    }
    # round 1's record is untouched by round 2's decisions
    decide(client, pid, ids["Chair"], "left")
    r1 = client.get(f"/api/projects/{pid}/items?round=1").get_json()["items"]
    assert {i["data"]["name"]: i["choice"] for i in r1}["Chair"] == "right"


def test_next_round_with_undecided_and_empty_guard(client):
    pid = make(client)["id"]
    ids = ids_by_name(client, pid)
    decide(client, pid, ids["Chair"], "left")
    r = client.post(f"/api/projects/{pid}/rounds", json={"carry": ["right"]})
    assert r.status_code == 400   # would be empty
    assert client.get(f"/api/projects/{pid}").get_json()["round"]["number"] == 1
    r = client.post(f"/api/projects/{pid}/rounds", json={"carry": ["none"]})
    assert r.get_json()["project"]["round"]["total"] == 2
    assert client.post(f"/api/projects/{pid}/rounds", json={"carry": ["bogus"]}).status_code == 400


def test_next_round_can_add_data_merged_by_key(client):
    pid = make(client)["id"]
    ids = ids_by_name(client, pid)
    for n in ("Chair", "Table", "Lamp"):
        decide(client, pid, ids[n], "right" if n != "Table" else "left")
    more = "id,name,stock\n1,,5\n4,Sofa,2"
    r = client.post(f"/api/projects/{pid}/rounds", json={"carry": ["right"], "text": more}).get_json()
    assert (r["added"], r["updated"]) == (1, 1)
    assert r["project"]["fields"] == ["id", "name", "price", "stock"]
    items = {i["data"]["name"]: i["data"] for i in queue(client, pid)["items"]}
    assert set(items) == {"Chair", "Lamp", "Sofa"}
    assert items["Chair"] == {"id": "1", "name": "Chair", "price": "40", "stock": "5"}  # blank name didn't erase


def test_import_into_current_round(client):
    pid = make(client)["id"]
    r = client.post(f"/api/projects/{pid}/import", json={"text": "id,name\n3,Lamp\n9,Rug"}).get_json()
    assert (r["added"], r["updated"]) == (1, 1)
    assert r["project"]["round"]["total"] == 4
    assert client.post(f"/api/projects/{pid}/import", json={"text": ""}).status_code == 400


def test_patch_project(client):
    pid = make(client)["id"]
    r = client.patch(f"/api/projects/{pid}", json={
        "name": "Renamed", "choices": {"left": {"label": "Nope"}}, "mapping": {"title": "price"}})
    p = r.get_json()
    assert p["name"] == "Renamed" and p["choices"]["left"]["label"] == "Nope"
    assert p["mapping"]["title"] == "price"
    assert client.patch(f"/api/projects/{pid}", json={"name": " "}).status_code == 400


def test_delete_is_a_rename(client):
    pid = make(client)["id"]
    assert client.delete(f"/api/projects/{pid}").status_code == 200
    assert client.get("/api/projects").get_json() == []
    assert any(f.startswith(f"deleted-{pid}-") for f in os.listdir(swipe.DATA_DIR))


def test_export_csv_and_json(client):
    pid = make(client, choices={"right": {"label": "Keep"}})["id"]
    ids = ids_by_name(client, pid)
    decide(client, pid, ids["Chair"], "right")
    decide(client, pid, ids["Table"], "left")
    decide(client, pid, ids["Lamp"], "unsure")
    client.post(f"/api/projects/{pid}/rounds", json={})
    decide(client, pid, ids["Lamp"], "right")

    r = client.get(f"/api/projects/{pid}/export")
    assert r.mimetype == "text/csv" and "furniture.csv" in r.headers["Content-Disposition"]
    rows = list(csv.DictReader(io.StringIO(r.get_data(as_text=True).lstrip("﻿"))))
    by = {row["name"]: row for row in rows}
    assert list(rows[0]) == ["id", "name", "price", "round_1", "round_2", "final"]
    assert (by["Lamp"]["round_1"], by["Lamp"]["round_2"], by["Lamp"]["final"]) == ("Not sure", "Keep", "Keep")
    assert (by["Chair"]["round_2"], by["Chair"]["final"]) == ("", "Keep")   # undecided in R2 → keeps R1
    assert by["Table"]["final"] == "No"

    keep = client.get(f"/api/projects/{pid}/export?choice=right").get_data(as_text=True)
    assert "Chair" in keep and "Lamp" in keep and "Table" not in keep

    data = json.loads(client.get(f"/api/projects/{pid}/export?format=json").get_data(as_text=True))
    lamp = next(d for d in data if d["data"]["name"] == "Lamp")
    assert lamp["rounds"] == {"1": "unsure", "2": "right"} and lamp["final_label"] == "Keep"

    r2 = client.get(f"/api/projects/{pid}/export?round=2").get_data(as_text=True)
    assert "Table" not in r2
