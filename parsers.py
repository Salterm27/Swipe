"""
List parsing and field guessing — stdlib only.

Swipe accepts "a list of things" in whatever shape it arrives: a JSON export,
a CSV, cells pasted from a spreadsheet, a markdown table, "key: value" notes,
or just one thing per line. Every format here turns text into the same thing:
a list of flat records ({field: str}) plus the ordered field names.

Adding a format = write `parse_x(text) -> list[dict] | None` (None means
"this isn't my format") and register it in FORMATS. Detection tries them in
order, most specific first; `lines` always succeeds, so it goes last.
"""

import csv
import hashlib
import io
import json
import re

MAX_RECORDS = 20000

FORMAT_LABELS = {
    "json": "JSON",
    "jsonl": "JSON lines",
    "markdown": "Markdown table",
    "tsv": "Tab-separated (spreadsheet paste)",
    "csv": "CSV",
    "keyvalue": "key: value blocks",
    "lines": "One item per line",
}

EXTENSION_HINTS = {
    ".json": "json", ".jsonl": "jsonl", ".ndjson": "jsonl", ".csv": "csv",
    ".tsv": "tsv", ".tab": "tsv", ".md": "markdown",
}


# ------------------------------------------------------------- normalizing

def _scalar(v):
    if v is None:
        return ""
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()


def _flatten(obj, prefix=""):
    """Nested JSON → one level of 'a.b' keys; lists of scalars → 'x, y'."""
    out = {}
    for k, v in obj.items():
        key = f"{prefix}{k}"
        if isinstance(v, dict):
            out.update(_flatten(v, key + "."))
        elif isinstance(v, list):
            if all(not isinstance(x, (dict, list)) for x in v):
                out[key] = ", ".join(_scalar(x) for x in v if _scalar(x))
            else:
                out[key] = json.dumps(v, ensure_ascii=False)
        else:
            out[key] = _scalar(v)
    return out


def _records_from_json_value(data):
    if isinstance(data, list):
        if not data:
            return []
        if all(isinstance(x, dict) for x in data):
            return [_flatten(x) for x in data]
        if all(not isinstance(x, (dict, list)) for x in data):
            return [{"item": _scalar(x)} for x in data]
        return None
    if isinstance(data, dict):
        # {"results": [...], "count": 3} — take the biggest list of records
        lists = [v for v in data.values() if isinstance(v, list) and v
                 and all(isinstance(x, dict) for x in v)]
        if lists:
            return [_flatten(x) for x in max(lists, key=len)]
        # {"id1": {...}, "id2": {...}}
        if data and all(isinstance(v, dict) for v in data.values()):
            return [{"key": k, **_flatten(v)} for k, v in data.items()]
        # {"apple": 3, "pear": 5}
        if data and all(not isinstance(v, (dict, list)) for v in data.values()):
            return [{"key": k, "value": _scalar(v)} for k, v in data.items()]
    return None


# ------------------------------------------------------------------ formats

def parse_json(text):
    try:
        data = json.loads(text)
    except ValueError:
        return None
    return _records_from_json_value(data)


def parse_jsonl(text):
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if len(lines) < 2:
        return None
    out = []
    for ln in lines:
        try:
            obj = json.loads(ln)
        except ValueError:
            return None
        if not isinstance(obj, dict):
            return None
        out.append(_flatten(obj))
    return out


_MD_SEP = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")


def parse_markdown(text):
    lines = [ln for ln in text.splitlines() if ln.strip()]
    start = next((i for i in range(len(lines) - 1)
                  if "|" in lines[i] and _MD_SEP.match(lines[i + 1])), None)
    if start is None:
        return None

    def cells(ln):
        ln = ln.strip()
        if ln.startswith("|"):
            ln = ln[1:]
        if ln.endswith("|"):
            ln = ln[:-1]
        return [c.strip() for c in ln.split("|")]

    header = _unique_headers(cells(lines[start]))
    out = []
    for ln in lines[start + 2:]:
        if "|" not in ln:
            break
        row = cells(ln)
        out.append({h: (row[i] if i < len(row) else "") for i, h in enumerate(header)})
    return out


def _looks_like_header(row, body):
    # blank cells are fine (pandas leaves the index column unnamed), but at
    # least half must be named and none may look like data
    named = [c for c in row if c.strip()]
    if len(named) * 2 < len(row):
        return False
    if any(_NUMBER.match(c) or _URL.match(c) for c in named):
        return False
    # a header row is usually shorter than the data under it
    if body:
        avg_head = sum(len(c) for c in row) / len(row)
        avg_body = sum(len(c) for r in body[:20] for c in r) / max(1, sum(len(r) for r in body[:20]))
        if avg_head > avg_body * 3 and avg_head > 30:
            return False
    return True


def _unique_headers(raw):
    seen, out = {}, []
    for i, h in enumerate(raw):
        h = h.strip() or f"column_{i + 1}"
        if h in seen:
            seen[h] += 1
            h = f"{h}_{seen[h]}"
        else:
            seen[h] = 1
        out.append(h)
    return out


def _parse_delimited(text, delimiter):
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if len(lines) < 2:
        return None
    rows = list(csv.reader(io.StringIO("\n".join(lines)), delimiter=delimiter))
    widths = [len(r) for r in rows]
    width = max(set(widths), key=widths.count)
    # needs real columns, and most rows agreeing on how many
    if width < 2 or widths.count(width) < 0.8 * len(rows):
        return None
    if _looks_like_header(rows[0], rows[1:]):
        header, body = _unique_headers(rows[0]), rows[1:]
    else:
        header, body = [f"column_{i + 1}" for i in range(width)], rows
    header = header + [f"column_{i + 1}" for i in range(len(header), width)]
    return [{h: (r[i].strip() if i < len(r) else "") for i, h in enumerate(header)}
            for r in body]


def parse_tsv(text):
    return _parse_delimited(text, "\t")


def parse_csv(text):
    sample = "\n".join(text.splitlines()[:50])
    try:
        delim = csv.Sniffer().sniff(sample, delimiters=",;|").delimiter
    except csv.Error:
        delim = ","
    return _parse_delimited(text, delim)


_KV = re.compile(r"^\s*(?:[-*]\s+)?([A-Za-z][\w .()/-]{0,39}?)\s*[:=]\s*(.*)$")


def parse_keyvalue(text):
    """Blocks of 'key: value' lines separated by blank lines (or YAML-ish
    '- key: value' list items)."""
    records, cur, kv_lines, total = [], {}, 0, 0
    for ln in text.splitlines():
        if not ln.strip():
            if cur:
                records.append(cur)
                cur = {}
            continue
        total += 1
        m = _KV.match(ln)
        if not m or _URL.match(ln.strip()):
            if cur and ln.startswith((" ", "\t")):
                last = list(cur)[-1]        # indented continuation line
                cur[last] = (cur[last] + " " + ln.strip()).strip()
                kv_lines += 1
            continue
        key, val = m.group(1).strip(), m.group(2).strip()
        if ln.lstrip().startswith(("- ", "* ")) and cur:
            records.append(cur)
            cur = {}
        if key in cur:                       # repeated key starts a new record
            records.append(cur)
            cur = {}
        cur[key] = val
        kv_lines += 1
    if cur:
        records.append(cur)
    if total == 0 or kv_lines < 0.8 * total or len(records) < 1:
        return None
    # one big block with no repeats is a single record — fine, but it must
    # look deliberate: at least two keys
    if len(records) == 1 and len(records[0]) < 2:
        return None
    return records


# task-list checkboxes first, or "- [x] a" would only lose its "- "
_BULLET = re.compile(r"^\s*(?:[-*+]\s+\[[ xX]\]\s+|\[[ xX]\]\s+|[-*•+]\s+|\d+[.)]\s+)")


def parse_lines(text):
    out = []
    for ln in text.splitlines():
        item = _BULLET.sub("", ln).strip()
        if item:
            out.append({"item": item})
    return out


FORMATS = {
    "json": parse_json,
    "jsonl": parse_jsonl,
    "markdown": parse_markdown,
    "tsv": parse_tsv,
    "csv": parse_csv,
    "keyvalue": parse_keyvalue,
    "lines": parse_lines,
}


def _try(fmt, text):
    try:
        recs = FORMATS[fmt](text)
    except (csv.Error, ValueError, RecursionError):
        return None
    if not recs:
        return None
    recs = [r for r in recs if any(v for v in r.values())]
    return recs or None


def read(text, fmt=None, filename=None):
    """Return (result, None) or (None, "what went wrong, for the user").

    result is {"format", "records", "fields", "truncated"}. `fmt` forces a
    format (the user picked one); otherwise a filename extension is tried
    first, then auto-detection. Errors are returned, not raised, so the
    message a user sees is always one written here — never the text of
    some unexpected internal exception.
    """
    text = (text or "").lstrip("\ufeff")
    if not text.strip():
        return None, "the list is empty"
    if fmt:
        if fmt not in FORMATS:
            return None, f"unknown format {fmt!r}"
        order = [fmt]
    else:
        order = list(FORMATS)
        if filename:
            ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
            hint = EXTENSION_HINTS.get(ext)
            if hint:
                order.remove(hint)
                order.insert(0, hint)
        # tabs on most lines means a spreadsheet paste, whatever else it has
        lines = [ln for ln in text.splitlines() if ln.strip()]
        if lines and sum("\t" in ln for ln in lines) < 0.8 * len(lines):
            order.remove("tsv")
    for f in order:
        recs = _try(f, text)
        if recs:
            truncated = len(recs) > MAX_RECORDS
            recs = recs[:MAX_RECORDS]
            return {"format": f, "records": recs, "fields": field_order(recs),
                    "truncated": truncated}, None
    return None, (f"could not read this as {FORMAT_LABELS[fmt]}" if fmt
                  else "could not find any items in this text")


def parse(text, fmt=None, filename=None):
    """read(), raising ValueError instead — handier for scripts and tests."""
    result, error = read(text, fmt, filename)
    if error:
        raise ValueError(error)
    return result


def field_order(records):
    seen = {}
    for r in records:
        for k in r:
            seen.setdefault(k, None)
    return list(seen)


# ------------------------------------------------------------ field guessing

_URL = re.compile(r"^https?://\S+$", re.I)
_IMAGE_URL = re.compile(r"^(https?://\S+\.(?:png|jpe?g|gif|webp|avif|svg)(?:\?\S*)?|data:image/\S+)$", re.I)
_NUMBER = re.compile(r"^[-+]?[$€£]?\d[\d.,]*%?$")

NAME_HINTS = {
    "title": r"^(title|name|label|item|heading|subject|product|term|word|question|task|idea)s?$",
    "image": r"(image|img|photo|picture|pic|poster|thumb|cover|avatar|logo|icon)",
    "link": r"^(url|link|href|website|web|homepage|permalink|source)s?$",
    "description": r"(desc|summary|notes?$|body|text|content|details|overview|bio|about|comment"
                   r"|synopsis|plot|abstract)",
    "subtitle": r"(subtitle|author|artist|category|type|brand|company|location|city|date|year|price"
                r"|genre|tag|role|status|email)",
    "key": r"^(id|key|uid|uuid|sku|isbn|slug|code|ref)$",
}

SLOTS = ("title", "subtitle", "image", "description", "link")


def field_stats(records, fields):
    stats = {}
    n = len(records) or 1
    for f in fields:
        vals = [r.get(f, "") for r in records]
        filled = [v for v in vals if v]
        k = len(filled) or 1
        stats[f] = {
            "fill": len(filled) / n,
            "unique": len(set(filled)) / k,
            "avg_len": sum(len(v) for v in filled) / k,
            "url": sum(bool(_URL.match(v)) for v in filled) / k,
            "image": sum(bool(_IMAGE_URL.match(v)) for v in filled) / k,
            "number": sum(bool(_NUMBER.match(v)) for v in filled) / k,
        }
    return stats


def _hint(slot, field):
    return re.search(NAME_HINTS[slot], field.strip().lower().replace(" ", "_")) is not None


def guess_mapping(records, fields=None):
    """Educated guess at which field goes in each card slot.

    Returns {"title", "subtitle", "image", "description", "link": field|None,
    "details": [remaining fields], "key": field|None}. Name hints win; the
    shape of the values breaks ties and fills gaps.
    """
    fields = fields or field_order(records)
    sample = records[:500]
    st = field_stats(sample, fields)
    used, m = set(), {}

    def take(slot, candidates):
        for f in candidates:
            if f not in used:
                used.add(f)
                m[slot] = f
                return
        m[slot] = None

    useful = [f for f in fields if st[f]["fill"] > 0]
    take("image", [f for f in useful if st[f]["image"] >= 0.5]
         + [f for f in useful if _hint("image", f) and st[f]["url"] >= 0.5])
    take("link", [f for f in useful if _hint("link", f) and st[f]["url"] >= 0.5]
         + [f for f in useful if st[f]["url"] >= 0.8 and st[f]["image"] < 0.5])
    text_fields = [f for f in useful if st[f]["url"] < 0.5]
    take("title", [f for f in text_fields if _hint("title", f)]
         + sorted((f for f in text_fields if st[f]["avg_len"] <= 120 and st[f]["number"] < 0.5
                   and not _hint("key", f)),
                  key=lambda f: (-round(st[f]["fill"], 1), -round(st[f]["unique"], 1), fields.index(f)))
         + text_fields)
    take("description", [f for f in text_fields if _hint("description", f)]
         + sorted((f for f in text_fields if st[f]["avg_len"] > 60),
                  key=lambda f: -st[f]["avg_len"]))
    take("subtitle", [f for f in text_fields if _hint("subtitle", f)]
         + [f for f in text_fields if st[f]["avg_len"] <= 60 and not _hint("key", f)])
    m["details"] = [f for f in useful if f not in used and not _hint("key", f)][:8]
    m["key"] = guess_key(sample if len(records) <= 500 else records, fields, m)
    return m


def guess_key(records, fields, mapping=None):
    """A field whose value identifies an item across imports, so a second
    list can add data to items you already decided. None → hash the record."""
    def unique(f):
        vals = [r.get(f, "") for r in records]
        return all(vals) and len(set(vals)) == len(vals)
    for f in fields:
        if _hint("key", f) and unique(f):
            return f
    mapping = mapping or {}
    for slot in ("link", "title"):
        f = mapping.get(slot)
        if f and unique(f):
            return f
    return None


def record_key(record, key_field):
    if key_field and record.get(key_field):
        return "k:" + record[key_field].strip().lower()
    blob = json.dumps(record, sort_keys=True, ensure_ascii=False)
    return "h:" + hashlib.sha1(blob.encode(), usedforsecurity=False).hexdigest()[:16]
