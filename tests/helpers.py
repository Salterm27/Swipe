"""Shared helpers for the API tests."""

LIST = "id,name,price\n1,Chair,40\n2,Table,90\n3,Lamp,15"


def make(client, text=LIST, **kw):
    r = client.post("/api/projects", json={"name": "Furniture", "text": text, **kw})
    assert r.status_code == 201, r.get_json()
    return r.get_json()


def queue(client, pid, limit=10):
    return client.get(f"/api/projects/{pid}/queue?limit={limit}").get_json()


def decide(client, pid, item_id, choice):
    r = client.post(f"/api/projects/{pid}/decisions", json={"item_id": item_id, "choice": choice})
    assert r.status_code == 200, r.get_json()
    return r.get_json()["stats"]


def ids_by_name(client, pid):
    return {i["data"]["name"]: i["id"] for i in client.get(f"/api/projects/{pid}/items").get_json()["items"]}
