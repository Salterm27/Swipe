"""Format detection and card-layout guessing."""

import json

import pytest

import parsers


def detect(text, **kw):
    r = parsers.parse(text, **kw)
    return r["format"], r["records"]


def test_plain_lines_strip_bullets_and_numbers():
    fmt, recs = detect("- Buy milk\n* Call mom\n3. Fix bike\n4) Taxes\n[ ] Gym\n\n")
    assert fmt == "lines"
    assert [r["item"] for r in recs] == ["Buy milk", "Call mom", "Fix bike", "Taxes", "Gym"]


def test_csv_with_header():
    fmt, recs = detect("name,price\nChair,40\nTable,90")
    assert fmt == "csv"
    assert recs == [{"name": "Chair", "price": "40"}, {"name": "Table", "price": "90"}]


def test_semicolon_csv():
    fmt, recs = detect("name;city\nAna;Rosario\nLeo;Madrid")
    assert fmt == "csv" and recs[1] == {"name": "Leo", "city": "Madrid"}


def test_spreadsheet_paste_is_tsv_even_with_commas_in_cells():
    fmt, recs = detect("Title\tNotes\nAlien\tscary, great\nHeat\tlong, tense")
    assert fmt == "tsv"
    assert recs[0] == {"Title": "Alien", "Notes": "scary, great"}


def test_headerless_rows_get_column_names():
    fmt, recs = detect("Paris\t2.1\nRome\t2.8")
    assert fmt == "tsv"
    assert recs[0] == {"column_1": "Paris", "column_2": "2.1"}


def test_duplicate_headers_are_made_unique():
    _, recs = detect("tag,tag,name\na,b,c\nd,e,f")
    assert list(recs[0]) == ["tag", "tag_2", "name"]


def test_json_array_of_objects_is_flattened():
    text = json.dumps([{"id": 1, "meta": {"genre": "x"}, "tags": ["a", "b"], "ok": True, "n": 2.0}])
    fmt, recs = detect(text)
    assert fmt == "json"
    assert recs == [{"id": "1", "meta.genre": "x", "tags": "a, b", "ok": "yes", "n": "2"}]


def test_json_wrapper_object_uses_biggest_list():
    text = json.dumps({"count": 2, "results": [{"t": "a"}, {"t": "b"}], "other": [{"x": 1}]})
    assert detect(text)[1] == [{"t": "a"}, {"t": "b"}]


def test_json_dict_of_dicts_and_scalars():
    assert detect(json.dumps({"a": {"x": 1}, "b": {"x": 2}}))[1] == [{"key": "a", "x": "1"}, {"key": "b", "x": "2"}]
    assert detect(json.dumps({"apple": 3}))[1] == [{"key": "apple", "value": "3"}]


def test_json_array_of_strings():
    assert detect('["a", "b"]')[1] == [{"item": "a"}, {"item": "b"}]


def test_jsonl():
    fmt, recs = detect('{"name":"a"}\n{"name":"b","x":1}\n')
    assert fmt == "jsonl" and recs[1] == {"name": "b", "x": "1"}


def test_markdown_table():
    fmt, recs = detect("Some notes\n\n| Name | Rating |\n|:---|---:|\n| Foo | 5 |\n| Bar | 3 |\n\nafter")
    assert fmt == "markdown"
    assert recs == [{"Name": "Foo", "Rating": "5"}, {"Name": "Bar", "Rating": "3"}]


def test_key_value_blocks_with_continuation():
    fmt, recs = detect("Name: Alice\nRole: Engineer\n\nName: Bob\nBio: likes\n  long walks")
    assert fmt == "keyvalue"
    assert recs == [{"Name": "Alice", "Role": "Engineer"}, {"Name": "Bob", "Bio": "likes long walks"}]


def test_yaml_ish_list():
    fmt, recs = detect("- name: a\n  city: X\n- name: b\n  city: Y")
    assert fmt == "keyvalue" and recs == [{"name": "a", "city": "X"}, {"name": "b", "city": "Y"}]


def test_urls_alone_are_lines_not_key_value():
    fmt, recs = detect("https://a.com/x\nhttps://b.com/y")
    assert fmt == "lines" and recs[0] == {"item": "https://a.com/x"}


def test_bom_and_filename_hint():
    fmt, _ = detect("﻿a,b\n1,2", filename="x.CSV")
    assert fmt == "csv"


def test_forced_format_and_errors():
    assert detect("a,b\n1,2", fmt="lines")[1] == [{"item": "a,b"}, {"item": "1,2"}]
    with pytest.raises(ValueError):
        parsers.parse("not json", fmt="json")
    with pytest.raises(ValueError):
        parsers.parse("   \n ")
    with pytest.raises(ValueError):
        parsers.parse("x", fmt="nope")


def test_guess_mapping_by_names():
    recs = [{"id": str(i), "name": f"Chair {i}", "price": "40", "photo": f"https://x.com/{i}.jpg",
             "url": f"https://shop.com/{i}", "description": "A comfy chair " * 8, "color": "red"}
            for i in range(5)]
    m = parsers.guess_mapping(recs)
    assert m["title"] == "name"
    assert m["image"] == "photo"
    assert m["link"] == "url"
    assert m["description"] == "description"
    assert m["subtitle"] == "price"
    assert m["details"] == ["color"]
    assert m["key"] == "id"


def test_guess_mapping_by_value_shape():
    recs = [{"a": f"https://cdn.x/{i}.png", "b": f"Thing {i}", "c": "long text " * 12} for i in range(4)]
    m = parsers.guess_mapping(recs)
    assert (m["image"], m["title"], m["description"]) == ("a", "b", "c")
    assert m["key"] == "b"   # unique title doubles as the match key


def test_key_falls_back_to_hash_when_nothing_unique():
    recs = [{"item": "x"}, {"item": "x"}]
    assert parsers.guess_mapping(recs)["key"] is None
    assert parsers.record_key(recs[0], None) == parsers.record_key({"item": "x"}, None)
    assert parsers.record_key({"id": " A1 "}, "id") == parsers.record_key({"id": "a1"}, "id")
