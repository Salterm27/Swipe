#!/usr/bin/env python3
"""
Swipe — turn any list into a Tinder-style deck, decide, export, repeat.

Every project is its OWN SQLite file (data/project-<id>.db): its settings,
items, rounds and decisions all live inside it, so a project can be copied,
backed up, inspected with the sqlite3 CLI or deleted without touching any
other. There is no central database; the project list is the directory.

Designed like WatchPi: Flask + SQLite, no other dependencies, and the server
never makes an outbound request.
"""

import csv
import io
import json
import os
import re
import secrets
import sqlite3
from datetime import UTC, datetime

from flask import Flask, Response, abort, g, jsonify, request
from werkzeug.exceptions import HTTPException

import parsers

DATA_DIR = os.environ.get("SWIPE_DATA", os.path.join(os.path.dirname(os.path.abspath(__file__)), "data"))
MAX_UPLOAD = 20 * 1024 * 1024

app = Flask(__name__, static_folder="static", static_url_path="")
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD
app.json.sort_keys = False   # keep each item's fields in the list's own order

CHOICES = ("left", "right", "unsure")
DEFAULT_CHOICES = {
    "left": {"label": "No", "icon": "✕", "color": "#b0604a"},       # dusty terracotta
    "right": {"label": "Yes", "icon": "✓", "color": "#1f4a35"},     # forest
    "unsure": {"label": "Not sure", "icon": "?", "color": "#a8802a"},  # soft ochre
}
# The defaults of the original dark theme. Projects that kept them get the
# current defaults instead, so old projects pick up the new look; a colour
# someone actually chose is left alone.
LEGACY_DEFAULT_COLORS = {"#e5484d": "#b0604a", "#3ecf8e": "#1f4a35", "#8b93a7": "#a8802a"}


def current_choices(meta):
    choices = meta.get("choices", DEFAULT_CHOICES)
    return {c: {**v, "color": LEGACY_DEFAULT_COLORS.get(v.get("color"), v.get("color"))}
            for c, v in choices.items()}

# Strict on purpose: the backup script writes project-<id>.bak.db snapshots
# next to the real files, and those must never show up as projects.
PROJECT_FILE = re.compile(r"^project-([0-9a-f]{12})\.db$")
PROJECT_ID = re.compile(r"^[0-9a-f]{12}$")

SCHEMA = """
-- Project settings as JSON values: name, created_at, choices, mapping,
-- key_field, fields, source_format.
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- One row per thing being decided. `key` identifies it across imports (a
-- chosen id-like field, or a hash of the record) so a second list can add
-- data to items you already swiped. `data` is the flat record as JSON.
CREATE TABLE IF NOT EXISTS items (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    key        TEXT    NOT NULL UNIQUE,
    data       TEXT    NOT NULL,
    position   INTEGER NOT NULL,
    created_at TEXT    NOT NULL,
    updated_at TEXT    NOT NULL
);

-- Round 1 holds every item; each later round holds the items you carried
-- over (e.g. the yes + not-sure pile) plus anything newly imported.
CREATE TABLE IF NOT EXISTS rounds (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    number     INTEGER NOT NULL UNIQUE,
    note       TEXT    NOT NULL DEFAULT '',
    created_at TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS round_items (
    round_id INTEGER NOT NULL REFERENCES rounds(id) ON DELETE CASCADE,
    item_id  INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    PRIMARY KEY (round_id, item_id)
);

-- The memory: one decision per item per round, never overwritten by a
-- later round, so the history of how you got to the final pile survives.
CREATE TABLE IF NOT EXISTS decisions (
    round_id   INTEGER NOT NULL REFERENCES rounds(id) ON DELETE CASCADE,
    item_id    INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    choice     TEXT    NOT NULL CHECK (choice IN ('left', 'right', 'unsure')),
    decided_at TEXT    NOT NULL,
    PRIMARY KEY (round_id, item_id)
);
"""


def now():
    return datetime.now(UTC).isoformat(timespec="seconds")


def err(msg, code=400):
    return jsonify(error=msg), code


# ---------------------------------------------------------------- storage

def project_path(pid):
    return os.path.join(DATA_DIR, f"project-{pid}.db")


def connect(path):
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


def open_project(pid):
    """Connection for an existing project, cached for the request."""
    if not PROJECT_ID.match(pid or "") or not os.path.exists(project_path(pid)):
        abort(404)
    cons = g.setdefault("cons", {})
    if pid not in cons:
        cons[pid] = connect(project_path(pid))
        cons[pid].executescript(SCHEMA)   # cheap; lets old files pick up new tables
    return cons[pid]


@app.teardown_appcontext
def close_dbs(_exc):
    for con in g.pop("cons", {}).values():
        con.close()


@app.errorhandler(HTTPException)
def http_error(e):
    """API errors are always JSON, so the UI can show the message."""
    if request.path.startswith("/api/"):
        msg = "not found" if e.code == 404 else e.description
        return err(msg, e.code)
    return e


def json_body():
    """The request's JSON object; missing body = {}, anything else = 400."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        abort(400, "expected a JSON object")
    return data


def get_meta(con):
    return {r["key"]: json.loads(r["value"]) for r in con.execute("SELECT key, value FROM meta")}


def set_meta(con, **values):
    con.executemany(
        "INSERT INTO meta (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        [(k, json.dumps(v, ensure_ascii=False)) for k, v in values.items()],
    )


def current_round(con):
    return con.execute("SELECT * FROM rounds ORDER BY number DESC LIMIT 1").fetchone()


def round_stats(con, round_id):
    total = con.execute("SELECT COUNT(*) FROM round_items WHERE round_id = ?", (round_id,)).fetchone()[0]
    counts = dict.fromkeys(CHOICES, 0)
    for r in con.execute("SELECT choice, COUNT(*) n FROM decisions WHERE round_id = ? GROUP BY choice", (round_id,)):
        counts[r["choice"]] = r["n"]
    decided = sum(counts.values())
    return {"total": total, "decided": decided, "remaining": total - decided, "counts": counts}


def project_summary(pid, con):
    meta = get_meta(con)
    rnd = current_round(con)
    rounds = [
        {"id": r["id"], "number": r["number"], "note": r["note"], "created_at": r["created_at"],
         **round_stats(con, r["id"])}
        for r in con.execute("SELECT * FROM rounds ORDER BY number")
    ]
    items = con.execute("SELECT COUNT(*) FROM items").fetchone()[0]
    return {
        "id": pid,
        "name": meta.get("name", "Untitled"),
        "created_at": meta.get("created_at"),
        "choices": current_choices(meta),
        "mapping": meta.get("mapping", {}),
        "key_field": meta.get("key_field"),
        "fields": meta.get("fields", []),
        "source_format": meta.get("source_format"),
        "item_count": items,
        "round": rounds[-1] if rnd else None,
        "rounds": rounds,
    }


def import_records(con, records, key_field, round_id):
    """Upsert records by key. Existing items get the new fields merged in
    (blank values never erase what you had); new items are appended. Every
    imported item is put in `round_id`. Returns (added, updated)."""
    ts = now()
    pos = con.execute("SELECT COALESCE(MAX(position), 0) FROM items").fetchone()[0]
    added = updated = 0
    for rec in records:
        key = parsers.record_key(rec, key_field)
        row = con.execute("SELECT id, data FROM items WHERE key = ?", (key,)).fetchone()
        if row:
            data = json.loads(row["data"])
            data.update({k: v for k, v in rec.items() if v})
            con.execute("UPDATE items SET data = ?, updated_at = ? WHERE id = ?",
                        (json.dumps(data, ensure_ascii=False), ts, row["id"]))
            item_id = row["id"]
            updated += 1
        else:
            pos += 1
            item_id = con.execute(
                "INSERT INTO items (key, data, position, created_at, updated_at) VALUES (?,?,?,?,?)",
                (key, json.dumps(rec, ensure_ascii=False), pos, ts, ts),
            ).lastrowid
            added += 1
        con.execute("INSERT OR IGNORE INTO round_items (round_id, item_id) VALUES (?,?)", (round_id, item_id))
    return added, updated


def merge_fields(old, records):
    seen = dict.fromkeys(old)
    for f in parsers.field_order(records):
        seen.setdefault(f, None)
    return list(seen)


# Validators return (value, None) or (None, message). They don't raise:
# what reaches the client is always a message written here, never the text
# of an exception (CodeQL py/stack-trace-exposure).

def clean_choices(raw):
    out = {}
    raw = raw or {}
    if not isinstance(raw, dict):
        return None, "choices must be an object"
    for c in CHOICES:
        d, given = DEFAULT_CHOICES[c], raw.get(c) or {}
        if not isinstance(given, dict):
            return None, f"choices.{c} must be an object"
        color = str(given.get("color") or d["color"]).strip()
        if not re.match(r"^#[0-9a-fA-F]{6}$", color):
            return None, f"{c}: color must look like #3ecf8e"
        out[c] = {
            "label": (str(given.get("label") or "").strip() or d["label"])[:40],
            "icon": (str(given.get("icon") or "").strip() or d["icon"])[:8],
            "color": color.lower(),
        }
    return out, None


def clean_mapping(raw, fields):
    raw = raw or {}
    if not isinstance(raw, dict) or not isinstance(raw.get("gallery") or [], list):
        return None, "mapping must be an object with a gallery list"
    out = {}
    for slot in parsers.SLOTS:
        f = raw.get(slot)
        out[slot] = f if f in fields else None
    out["gallery"] = [f for f in (raw.get("gallery") or []) if f in fields and f != out["image"]]
    return out, None


def parse_body(data):
    text, fmt, filename = data.get("text", ""), data.get("format") or None, data.get("filename")
    if not isinstance(text, str):
        return None, "text must be a string"
    if not isinstance(fmt, (str, type(None))) or not isinstance(filename, (str, type(None))):
        return None, "format and filename must be strings"
    return parsers.read(text, fmt=fmt, filename=filename)


def item_dict(row, history=None, choice=None):
    return {"id": row["id"], "data": json.loads(row["data"]), "position": row["position"],
            "choice": choice, "history": history or []}


def histories(con, item_ids, before_round=None):
    """{item_id: [{round, choice}, ...]} of decisions in earlier rounds."""
    out = {i: [] for i in item_ids}
    if not item_ids:
        return out
    q = ",".join("?" * len(item_ids))
    # only "?" placeholders are interpolated; values stay bound parameters
    sql = (f"SELECT d.item_id, r.number, d.choice FROM decisions d JOIN rounds r ON r.id = d.round_id "  # noqa: S608
           f"WHERE d.item_id IN ({q})")
    args = list(item_ids)
    if before_round is not None:
        sql += " AND r.number < ?"
        args.append(before_round)
    for r in con.execute(sql + " ORDER BY r.number", args):
        out[r["item_id"]].append({"round": r["number"], "choice": r["choice"]})
    return out


# -------------------------------------------------------------------- api

@app.route("/")
def index():
    resp = app.send_static_file("index.html")
    resp.headers["Cache-Control"] = "no-cache"
    return resp


@app.get("/api/health")
def health():
    return jsonify(ok=True)


@app.get("/api/formats")
def formats():
    return jsonify([{"id": k, "label": v} for k, v in parsers.FORMAT_LABELS.items()])


@app.post("/api/parse")
def parse_preview():
    """Stateless dry run: what Swipe makes of this text, plus a guessed card
    layout. Nothing is stored until POST /api/projects."""
    data = json_body()
    res, problem = parse_body(data)
    if problem:
        return err(problem)
    recs = res["records"]
    mapping = parsers.guess_mapping(recs, res["fields"])
    return jsonify(
        format=res["format"], count=len(recs), truncated=res["truncated"],
        fields=res["fields"], mapping=mapping, key_field=mapping.pop("key"),
        sample=recs[:25],
    )


@app.get("/api/projects")
def list_projects():
    os.makedirs(DATA_DIR, exist_ok=True)
    out = []
    for name in os.listdir(DATA_DIR):
        m = PROJECT_FILE.match(name)
        if m:
            s = project_summary(m.group(1), open_project(m.group(1)))
            for k in ("fields", "mapping", "rounds"):
                s.pop(k)
            out.append(s)
    out.sort(key=lambda p: p["created_at"] or "", reverse=True)
    return jsonify(out)


@app.post("/api/projects")
def create_project():
    data = json_body()
    name = str(data.get("name", "")).strip()[:120]
    if not name:
        return err("name is required")
    choices, problem = clean_choices(data.get("choices"))
    if problem:
        return err(problem)
    res, problem = parse_body(data)
    if problem:
        return err(problem)
    fields = res["fields"]
    guess = parsers.guess_mapping(res["records"], fields)
    mapping, problem = clean_mapping(data.get("mapping") or guess, fields)
    if problem:
        return err(problem)
    # key_field: absent → use the guess; null → match on the whole record
    key_field = data["key_field"] if "key_field" in data else guess["key"]
    if key_field not in fields:
        key_field = None

    os.makedirs(DATA_DIR, exist_ok=True)
    pid = secrets.token_hex(6)
    path = project_path(pid)
    con = connect(path)
    try:
        con.executescript(SCHEMA)
        with con:
            set_meta(con, name=name, created_at=now(), choices=choices, mapping=mapping,
                     key_field=key_field, fields=fields, source_format=res["format"])
            rid = con.execute("INSERT INTO rounds (number, created_at) VALUES (1, ?)", (now(),)).lastrowid
            import_records(con, res["records"], key_field, rid)
    except Exception:
        con.close()
        os.remove(path)
        raise
    con.close()
    return jsonify(project_summary(pid, open_project(pid))), 201


@app.get("/api/projects/<pid>")
def get_project(pid):
    return jsonify(project_summary(pid, open_project(pid)))


@app.patch("/api/projects/<pid>")
def update_project(pid):
    con = open_project(pid)
    data = json_body()
    meta = get_meta(con)
    updates = {}
    if "name" in data:
        name = str(data["name"]).strip()[:120]
        if not name:
            return err("name can't be empty")
        updates["name"] = name
    if "choices" in data:
        updates["choices"], problem = clean_choices(data["choices"])
        if problem:
            return err(problem)
    if "mapping" in data:
        updates["mapping"], problem = clean_mapping(data["mapping"], meta.get("fields", []))
        if problem:
            return err(problem)
    with con:
        set_meta(con, **updates)
    return jsonify(project_summary(pid, con))


@app.delete("/api/projects/<pid>")
def delete_project(pid):
    """Soft delete: the file is renamed out of the project list, not erased,
    so a slip of the thumb is recoverable by renaming it back."""
    open_project(pid)
    g.pop("cons", {}).pop(pid).close()
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    os.replace(project_path(pid), os.path.join(DATA_DIR, f"deleted-{pid}-{stamp}.db"))
    return jsonify(ok=True)


@app.get("/api/projects/<pid>/queue")
def queue(pid):
    """Next undecided items of the current round, in list order."""
    con = open_project(pid)
    rnd = current_round(con)
    limit = max(1, min(request.args.get("limit", 10, type=int), 100))
    rows = con.execute(
        """SELECT i.* FROM round_items ri JOIN items i ON i.id = ri.item_id
           WHERE ri.round_id = ? AND NOT EXISTS
             (SELECT 1 FROM decisions d WHERE d.round_id = ri.round_id AND d.item_id = ri.item_id)
           ORDER BY i.position LIMIT ?""",
        (rnd["id"], limit),
    ).fetchall()
    hist = histories(con, [r["id"] for r in rows], before_round=rnd["number"])
    return jsonify(round=rnd["number"], stats=round_stats(con, rnd["id"]),
                   items=[item_dict(r, hist[r["id"]]) for r in rows])


@app.post("/api/projects/<pid>/decisions")
def decide(pid):
    """Record (or change) the current round's decision for an item."""
    con = open_project(pid)
    data = json_body()
    choice = data.get("choice")
    if choice not in CHOICES:
        return err("choice must be left, right or unsure")
    rnd = current_round(con)
    try:
        item_id = int(data.get("item_id"))
    except (TypeError, ValueError):
        return err("item_id is required")
    if not con.execute("SELECT 1 FROM round_items WHERE round_id = ? AND item_id = ?",
                       (rnd["id"], item_id)).fetchone():
        return err("item is not in the current round", 404)
    with con:
        # delete + insert rather than upsert: a changed decision gets a fresh
        # rowid, which is what undo uses to find "the last thing I did"
        con.execute("DELETE FROM decisions WHERE round_id = ? AND item_id = ?", (rnd["id"], item_id))
        con.execute("INSERT INTO decisions (round_id, item_id, choice, decided_at) VALUES (?,?,?,?)",
                    (rnd["id"], item_id, choice, now()))
    return jsonify(stats=round_stats(con, rnd["id"]))


@app.post("/api/projects/<pid>/undo")
def undo(pid):
    """Take back the most recent decision of the current round."""
    con = open_project(pid)
    rnd = current_round(con)
    last = con.execute(
        "SELECT item_id FROM decisions WHERE round_id = ? ORDER BY rowid DESC LIMIT 1",
        (rnd["id"],),
    ).fetchone()
    if not last:
        return err("nothing to undo", 404)
    with con:
        con.execute("DELETE FROM decisions WHERE round_id = ? AND item_id = ?", (rnd["id"], last["item_id"]))
    row = con.execute("SELECT * FROM items WHERE id = ?", (last["item_id"],)).fetchone()
    hist = histories(con, [row["id"]], before_round=rnd["number"])
    return jsonify(item=item_dict(row, hist[row["id"]]), stats=round_stats(con, rnd["id"]))


@app.get("/api/projects/<pid>/items")
def list_items(pid):
    """Items of a round (default: current) with their decision there and
    their earlier history. ?choice=left|right|unsure|none filters."""
    con = open_project(pid)
    number = request.args.get("round", type=int)
    rnd = con.execute("SELECT * FROM rounds WHERE number = ?", (number,)).fetchone() if number \
        else current_round(con)
    if not rnd:
        return err("no such round", 404)
    rows = con.execute(
        """SELECT i.*, d.choice FROM round_items ri JOIN items i ON i.id = ri.item_id
           LEFT JOIN decisions d ON d.round_id = ri.round_id AND d.item_id = ri.item_id
           WHERE ri.round_id = ? ORDER BY i.position""",
        (rnd["id"],),
    ).fetchall()
    want = request.args.get("choice")
    if want:
        rows = [r for r in rows if (r["choice"] or "none") == want]
    hist = histories(con, [r["id"] for r in rows], before_round=rnd["number"])
    return jsonify(round=rnd["number"], items=[item_dict(r, hist[r["id"]], r["choice"]) for r in rows])


@app.post("/api/projects/<pid>/import")
def import_more(pid):
    """Add more data to the current round. Items whose key matches existing
    ones gain the new fields; the rest are added to the deck."""
    con = open_project(pid)
    data = json_body()
    res, problem = parse_body(data)
    if problem:
        return err(problem)
    meta = get_meta(con)
    rnd = current_round(con)
    with con:
        added, updated = import_records(con, res["records"], meta.get("key_field"), rnd["id"])
        set_meta(con, fields=merge_fields(meta.get("fields", []), res["records"]))
    return jsonify(added=added, updated=updated, project=project_summary(pid, con))


@app.post("/api/projects/<pid>/rounds")
def next_round(pid):
    """Start the next round with the items whose decision this round is in
    `carry` (default: right + unsure). Optional `text` imports more data
    into the new round in the same step."""
    con = open_project(pid)
    data = json_body()
    carry = data.get("carry") or ["right", "unsure"]
    if not isinstance(carry, list) or any(c not in (*CHOICES, "none") for c in carry):
        return err("carry must be a list of left/right/unsure/none")
    res = None
    if str(data.get("text", "")).strip():
        res, problem = parse_body(data)
        if problem:
            return err(problem)
    meta = get_meta(con)
    prev = current_round(con)
    added = updated = 0
    with con:
        rid = con.execute("INSERT INTO rounds (number, note, created_at) VALUES (?,?,?)",
                          (prev["number"] + 1, str(data.get("note", ""))[:200], now())).lastrowid
        for choice in set(carry) - {"none"}:
            con.execute(
                "INSERT INTO round_items (round_id, item_id) "
                "SELECT ?, item_id FROM decisions WHERE round_id = ? AND choice = ?",
                (rid, prev["id"], choice),
            )
        if "none" in carry:
            con.execute(
                """INSERT OR IGNORE INTO round_items (round_id, item_id)
                   SELECT ?, ri.item_id FROM round_items ri WHERE ri.round_id = ? AND NOT EXISTS
                     (SELECT 1 FROM decisions d WHERE d.round_id = ri.round_id AND d.item_id = ri.item_id)""",
                (rid, prev["id"]),
            )
        if res:
            added, updated = import_records(con, res["records"], meta.get("key_field"), rid)
            set_meta(con, fields=merge_fields(meta.get("fields", []), res["records"]))
        if not round_stats(con, rid)["total"]:
            con.rollback()
            return err("that round would be empty — carry over another pile or add data")
    return jsonify(added=added, updated=updated, project=project_summary(pid, con)), 201


@app.get("/api/projects/<pid>/export")
def export(pid):
    """Every item with its decision in each round and the latest verdict.
    ?format=csv (default) or json; ?round=N limits to that round's items;
    ?choice=right keeps only items whose latest verdict is that choice."""
    con = open_project(pid)
    meta = get_meta(con)
    labels = {c: v["label"] for c, v in meta.get("choices", DEFAULT_CHOICES).items()}
    rounds = con.execute("SELECT * FROM rounds ORDER BY number").fetchall()
    number = request.args.get("round", type=int)
    if number:
        rows = con.execute(
            """SELECT i.* FROM items i JOIN round_items ri ON ri.item_id = i.id
               JOIN rounds r ON r.id = ri.round_id WHERE r.number = ? ORDER BY i.position""",
            (number,),
        ).fetchall()
    else:
        rows = con.execute("SELECT * FROM items ORDER BY position").fetchall()
    hist = histories(con, [r["id"] for r in rows])
    want = request.args.get("choice")

    records = []
    for r in rows:
        by_round = {h["round"]: h["choice"] for h in hist[r["id"]]}
        final = by_round[max(by_round)] if by_round else None
        if want and (final or "none") != want:
            continue
        records.append((json.loads(r["data"]), by_round, final))

    slug = re.sub(r"[^a-z0-9]+", "-", meta.get("name", "swipe").lower()).strip("-") or "swipe"
    if request.args.get("format") == "json":
        body = json.dumps([
            {"data": d, "final": f, "final_label": labels.get(f),
             "rounds": {str(n): c for n, c in br.items()}}
            for d, br, f in records
        ], ensure_ascii=False, indent=2)
        return Response(body, mimetype="application/json",
                        headers={"Content-Disposition": f'attachment; filename="{slug}.json"'})

    fields = meta.get("fields", [])
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(fields + [f"round_{r['number']}" for r in rounds] + ["final"])
    for d, br, f in records:
        w.writerow([d.get(x, "") for x in fields]
                   + [labels.get(br.get(r["number"]), "") for r in rounds]
                   + [labels.get(f, "")])
    return Response("﻿" + buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{slug}.csv"'})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("SWIPE_PORT", 8002)))
