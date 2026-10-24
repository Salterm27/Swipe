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


# ---------------------------------------------------------------- edge cases

def test_windows_line_endings():
    assert detect("name,qty\r\nA,1\r\nB,2\r\n")[1] == [{"name": "A", "qty": "1"}, {"name": "B", "qty": "2"}]
    assert detect("one\r\ntwo")[1] == [{"item": "one"}, {"item": "two"}]


def test_quoted_csv_fields_with_commas():
    _, recs = detect('title,notes\n"Dune","long, slow, great"\n"Heat","tense"')
    assert recs[0] == {"title": "Dune", "notes": "long, slow, great"}


def test_ragged_rows_are_padded_and_mostly_ragged_is_not_csv():
    _, recs = detect("a,b,c\n1,2,3\n4,5\n6,7,8\n9,10,11")
    assert recs[1] == {"a": "4", "b": "5", "c": ""}
    assert detect("a,b\nno commas here\nnor here\nor here")[0] == "lines"


def test_header_heuristics():
    # numbers or urls in the first row mean it's data, not a header
    assert detect("1,2\n3,4")[1][0] == {"column_1": "1", "column_2": "2"}
    assert detect("https://a.com,x\nhttps://b.com,y")[1][0]["column_2"] == "x"
    # a first row far longer than the data under it is a data row
    long = "This is a very long sentence that nobody would use as a column header"
    assert detect(f"{long},{long}\nab,cd\nef,gh")[1][0]["column_1"] == long
    # blank header cells get a name
    assert list(detect("a,,c\n1,2,3\n4,5,6")[1][0]) == ["a", "column_2", "c"]


def test_empty_rows_are_dropped():
    assert detect("name,x\nA,1\n,\nB,2")[1] == [{"name": "A", "x": "1"}, {"name": "B", "x": "2"}]


def test_unicode_and_emoji_survive():
    assert detect("- 🍕 Pizza\n- Ñoquis")[1] == [{"item": "🍕 Pizza"}, {"item": "Ñoquis"}]


def test_json_edge_shapes():
    assert parsers.parse_json("[]") == []
    assert parsers.parse_json('[1, {"a": 1}]') is None                  # mixed list
    assert parsers.parse_json('{"a": [1], "b": {"c": 1}}') is None       # nothing record-like
    assert parsers.parse_json("3") is None
    _, recs = detect(json.dumps([{"x": None, "y": [{"z": 1}]}]))
    assert recs == [{"x": "", "y": '[{"z": 1}]'}]                        # nested records stay JSON


def test_jsonl_needs_objects_on_every_line():
    assert parsers.parse_jsonl('{"a":1}') is None
    assert parsers.parse_jsonl('{"a":1}\n[1]') is None
    assert parsers.parse_jsonl('{"a":1}\nnope') is None


def test_markdown_table_stops_at_first_non_row_and_pads():
    recs = parsers.parse_markdown("| a | b |\n|---|---|\n| 1 |\nend\n| 9 | 9 |")
    assert recs == [{"a": "1", "b": ""}]
    assert parsers.parse_markdown("| just | pipes |") is None


def test_key_value_rejections():
    assert parsers.parse_keyvalue("Note: one thing") is None              # single lone key
    assert parsers.parse_keyvalue("a: 1\nplain\nplain\nplain") is None    # mostly not key: value
    assert parsers.parse_keyvalue("name: a\nname: b") == [{"name": "a"}, {"name": "b"}]


def test_lines_strip_all_bullet_styles():
    text = "+ a\n• b\n- [x] c\n* [ ] d\n10) e"
    assert [r["item"] for r in parsers.parse_lines(text)] == ["a", "b", "c", "d", "e"]


def test_records_are_capped(monkeypatch):
    monkeypatch.setattr(parsers, "MAX_RECORDS", 3)
    r = parsers.parse("a\nb\nc\nd\ne")
    assert r["truncated"] and len(r["records"]) == 3
    assert not parsers.parse("a\nb")["truncated"]


def test_filename_hint_without_extension_is_ignored():
    assert parsers.parse("a,b\n1,2", filename="README")["format"] == "csv"
    assert parsers.parse('{"a":1}\n{"a":2}', filename="dump.ndjson")["format"] == "jsonl"


def test_field_order_is_first_seen():
    assert parsers.field_order([{"b": 1}, {"a": 1, "b": 2}, {"c": 3}]) == ["b", "a", "c"]


def test_field_stats_shapes():
    st = parsers.field_stats([{"u": "https://a.com/x.png", "n": "12"}, {"u": "", "n": "$3,50"}], ["u", "n"])
    assert st["u"]["fill"] == 0.5 and st["u"]["image"] == 1 and st["u"]["url"] == 1
    assert st["n"]["number"] == 1 and st["n"]["unique"] == 1


def test_guess_mapping_with_no_usable_fields():
    m = parsers.guess_mapping([{"a": ""}, {"a": ""}])
    assert all(m[s] is None for s in parsers.SLOTS) and m["details"] == []


def test_link_is_not_mistaken_for_image_and_vice_versa():
    recs = [{"page": f"https://site.com/p/{i}", "pic": f"https://cdn.com/{i}.webp?w=300"} for i in range(3)]
    m = parsers.guess_mapping(recs)
    assert (m["image"], m["link"]) == ("pic", "page")


def test_details_skip_id_fields_and_cap_at_eight():
    recs = [{"title": "x", "id": "1", **{f"f{i}": "v" for i in range(12)}}]
    m = parsers.guess_mapping(recs)
    assert "id" not in m["details"] and len(m["details"]) == 8


def test_pandas_export_with_unnamed_index_column():
    _, recs = detect(",name,price\n0,Chair,40\n1,Table,90")
    assert recs[0] == {"column_1": "0", "name": "Chair", "price": "40"}
