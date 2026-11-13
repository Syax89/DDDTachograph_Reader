"""The file-structure view: a file's units in file order, each decoded on its own.

The units must tile the file (every byte in exactly one top-level unit), carry
the signature verdict the parser reached, and decode to what their own bytes
hold. The explorer shows them under *File Structure* in place of the
generation groups, with a *Bytes* switch for the hex view.
"""
from pathlib import Path

import struct

import pytest

from app.engine import TachoParser
from core.structure import build_layout, hex_rows
from tests.integration import generate_mock_ddd as mock
from tests.unit.real_data import real_ddd_files


def _layout(path):
    raw = Path(path).read_bytes()
    return raw, build_layout(raw, TachoParser(str(path)).parse())


def _tiles(raw, units):
    cursor = 0
    for unit in units:
        assert unit.offset == cursor, f"{unit.title} starts at 0x{unit.offset:X}"
        cursor = unit.end
    assert cursor == len(raw)


def _stap(tag, dtype, payload):
    return struct.pack(">HBH", tag, dtype, len(payload)) + payload


def _text(value, size):
    return value.encode("latin-1").ljust(size, b" ")[:size]


#: CardIdentification + DriverCardHolderIdentification (Annex 1C §2.24/2.62),
#: 143 bytes, made-up values.
IDENTIFICATION = (b"\x1a" + _text("X100000000000001", 16) + b"\x01"
                  + _text("AUTHORITY", 35) + struct.pack(">III", 1_600_000_000,
                                                        1_600_000_000, 1_900_000_000)
                  + b"\x01" + _text("DOE", 35) + b"\x01" + _text("JANE", 35)
                  + bytes.fromhex("19800101") + b"en")


def _card_stream():
    """EF_ICC, then EF Identification with its signature, in both applications."""
    icc = bytes(25)
    return (_stap(0x0002, 0x00, icc)
            + _stap(0x0520, 0x00, IDENTIFICATION) + _stap(0x0520, 0x01, bytes(128))
            + _stap(0x0002, 0x02, icc)
            + _stap(0x0520, 0x02, IDENTIFICATION) + _stap(0x0520, 0x03, bytes(64)))


def _array(rt, records):
    size = len(records[0]) if records else 2
    return struct.pack(">BHH", rt, size, len(records)) + b"".join(records)


def _activities(day, changes):
    return (b"\x76\x32" + _array(0x06, [struct.pack(">I", day)])
            + _array(0x05, [b"\x00\x10\x00"])
            + _array(0x01, [struct.pack(">H", c) for c in changes])
            + _array(0x08, [bytes(64)]))


def _vu_stream():
    return (_activities(1_700_006_400, [0x0000, 0x0960, 0x1A40])
            + _activities(1_700_092_800, [0x0000]))


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    folder = tmp_path_factory.mktemp("built")
    out = {"card": folder / "card.ddd", "vu": folder / "vu.ddd"}
    out["card"].write_bytes(_card_stream())
    out["vu"].write_bytes(_vu_stream())
    return out


@pytest.fixture(scope="module")
def mocks(tmp_path_factory):
    folder = tmp_path_factory.mktemp("mocks")
    out = {}
    for name, make in (("g1_card", mock.generate_g1_card),
                       ("g2_card", mock.generate_g2_card),
                       ("g2_vu", mock.generate_g2_vu),
                       ("g22_vu", mock.generate_g22_vu)):
        path = folder / f"{name}.ddd"
        make(str(path))
        out[name] = path
    return out


# ── the layout ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("name", ["g1_card", "g2_card", "g2_vu", "g22_vu"])
def test_units_tile_the_file(mocks, name):
    raw, units = _layout(mocks[name])
    assert units
    _tiles(raw, units)


def test_a_card_is_two_applications_of_elementary_files(built):
    raw, units = _layout(built["card"])
    _tiles(raw, units)
    groups = [u for u in units if u.kind == "group"]
    assert [g.title for g in groups] == ["Tachograph application, generation 1",
                                        "Tachograph application, generation 2"]
    for group in groups:
        assert all(child.kind == "ef" for child in group.children)
        index = group.content()["elementary_files"]
        assert [row["file_identifier"] for row in index] == [
            child.tag.replace("EF ", "") for child in group.children]
    # each signature element sits under the EF it signs
    signed = [ef for g in groups for ef in g.children if ef.children]
    assert [ef.tag for ef in signed] == ["EF 0x0520", "EF 0x0520"]
    assert [ef.children[0].length for ef in signed] == [5 + 128, 5 + 64]
    assert all(ef.children[0].kind == "signature" for ef in signed)
    assert all(ef.children[0].offset == ef.end for ef in signed)


def test_an_ef_decodes_its_own_bytes(built):
    raw, units = _layout(built["card"])
    identification = next(u for u in units[0].walk() if u.tag == "EF 0x0520")
    content = identification.content()
    assert content["driver"]["surname"] == "DOE"
    # and nothing it does not hold
    assert "events" not in content and "activities" not in content


def test_a_vu_is_sections_of_record_arrays(built):
    raw, units = _layout(built["vu"])
    _tiles(raw, units)
    sections = [u for u in units if u.kind == "section"]
    assert [(u.title, u.detail, u.tag) for u in sections] == [
        ("Activities", "15/11/2023", "TREP 0x32"),
        ("Activities", "16/11/2023", "TREP 0x32")]
    for section in sections:
        arrays = section.children
        assert arrays and all(a.kind == "array" for a in arrays)
        # the arrays follow each other inside the section
        assert arrays[0].offset == section.offset + 2
        for left, right in zip(arrays, arrays[1:], strict=False):
            assert left.end == right.offset
        assert arrays[-1].end == section.end
        index = section.content()["record_arrays"]
        assert len(index) == len(arrays)


def test_an_array_decodes_one_record_per_declared_record(built):
    raw, units = _layout(built["vu"])
    arrays = [u for top in units for u in top.walk() if u.kind == "array"]
    for array in arrays:
        declared = int(array.detail.split(" ")[0])
        records = next(iter(array.content().values()), [])
        assert len(records) == declared, array.title
    changes = next(a for a in arrays if a.tag == "RecordArray 0x01").content()
    assert len(next(iter(changes.values()))) == 3


def test_g1_vu_messages_with_their_signature():
    body = b"A" * 491 + b"\x00\x00"
    signature = bytes(range(128))
    raw = b"\x76\x01" + body + signature
    results = {"metadata": {"is_vu": True, "generation": "G1 (Digital)"},
               "signature_verification": {"treps": [
                   {"trep": "0x01", "signature_valid": False}]}}
    units = build_layout(raw, results)
    assert [u.title for u in units] == ["Overview"]
    overview = units[0]
    assert (overview.offset, overview.length) == (0, len(raw))
    assert overview.signature is False
    assert [(c.kind, c.offset, c.length) for c in overview.children] == [
        ("signature", 2 + len(body), 128)]


def test_bytes_no_unit_explains_are_shown_as_a_gap():
    raw = b"\x76\x32\x06\x00\x04\x00\x01\x63\x00\x00\x00" + b"\x13\x37" + b"\xff" * 4
    results = {"metadata": {"is_vu": True, "generation": "G2 (Smart)"}}
    units = build_layout(raw, results)
    _tiles(raw, units)
    assert units[0].detail          # an Activities section names its day
    assert units[-1].kind == "gap"


def test_a_failing_decoder_leaves_the_bytes():
    raw = b"\x76\x32\x06\x00\x04\x00\x01\x63\x00\x00\x00"
    unit = build_layout(raw, {"metadata": {"is_vu": True, "generation": "G2"}})[0]

    def broken():
        raise RuntimeError("decoder bug")

    unit._content = None
    unit.decoder = broken
    assert unit.content() == {}


def test_no_bytes_no_layout():
    assert build_layout(b"", {"metadata": {}}) == []
    assert build_layout(b"\x00", None) == []


def test_certificates_are_not_called_driver_card_certificates():
    from core.structure import content_title
    assert content_title("certificates") == "Certificates"
    assert content_title("events") == "Events"


def test_a_day_row_sums_its_changes_up():
    from app.gui_explorer_structure import content_rows
    day = {"date": "01/05/2025", "changes": [
        {"activity": "REST", "time": "00:00", "slot": "First"},
        {"activity": "DRIVE", "time": "06:00", "slot": "First"},
        {"activity": "REST", "time": "10:30", "slot": "First"}]}
    cols, rows = content_rows([day], "activities")
    shown = dict(zip(cols, rows[0], strict=True))
    assert not any("items" in str(v) for v in rows[0])
    assert shown["Drive"] == "4:30"
    assert shown["Rest"] == "19:30"
    assert shown["Unknown"] == "0:00"
    # the last day of a download ends where the recording ends
    cols, rows = content_rows([day], "activities", {"01/05/2025": 12 * 3600})
    assert dict(zip(cols, rows[0], strict=True))["Rest"] == "7:30"     # 0-6 and 10:30-12


def test_hex_rows():
    rows = hex_rows(bytes(range(20)) + b"AB", base=0x10)
    assert rows[0][0] == "0x00000010"
    assert rows[1] == ["0x00000020", "10 11 12 13 41 42", "....AB"]
    assert len(hex_rows(b"\x00" * 100, limit=32)) == 2


@pytest.mark.parametrize("path", real_ddd_files() or [None])
def test_every_real_file_is_tiled_and_its_signatures_matched(path):
    if path is None:
        pytest.skip("no private DDD samples")
    raw = Path(path).read_bytes()
    result = TachoParser(path).parse()
    units = build_layout(raw, result)
    assert units
    _tiles(raw, units)
    verdicts = [u.signature for u in units if u.kind == "section" and u.signature is not None]
    treps = (result.get("signature_verification") or {}).get("treps") or []
    expected = [t["signature_valid"] for t in treps
                if isinstance(t.get("signature_valid"), bool)]
    if result["metadata"].get("is_vu"):
        assert verdicts == expected


# ── the explorer ─────────────────────────────────────────────────────────────

@pytest.fixture
def explorer(monkeypatch):
    from tests.unit.test_empty_state import close, new_explorer
    app = new_explorer(monkeypatch)
    try:
        yield app
    finally:
        close(app)


def _open(app, path):
    app._parse_done(TachoParser(str(path)).parse(), str(path))
    app.update()


def _nodes(tree, parent=""):
    for iid in tree.get_children(parent):
        yield iid
        yield from _nodes(tree, iid)


def test_the_structure_replaces_the_generation_groups(explorer, mocks):
    from app import gui
    _open(explorer, mocks["g2_card"])
    top = [explorer.tree.item(i, "text") for i in explorer.tree.get_children("")]
    assert gui._("File Structure") in top
    assert not any(text.startswith("Generation") for text in top)
    assert gui._("Daily Activities") in top           # the views stay on top
    assert top.index(gui._("Daily Activities")) < top.index(gui._("File Structure"))


def test_selecting_a_unit_shows_its_records_and_its_bytes(explorer, built):
    from app import gui
    _open(explorer, built["card"])
    tree = explorer.tree
    node = next(i for i in _nodes(tree) if tree.item(i, "text").endswith("0x0520"))
    tree.selection_set(node)
    explorer._on_tree_select_impl(None)
    explorer.update()
    table = explorer.table
    assert table.bytes_check.winfo_manager()
    assert "EF 0x0520" in table.count_lbl.cget("text")
    assert gui._("Hex") not in table._cols

    table.bytes_var.set(True)
    table._toggle_bytes()
    assert table._cols == [gui._("Offset"), gui._("Hex"), gui._("Text")]
    first = table.tv.item(table.tv.get_children()[0], "values")
    unit = explorer._payloads[node][1]
    assert first[0] == f"0x{unit.offset:08X}"
    table.bytes_var.set(False)
    table._toggle_bytes()


def test_without_the_file_the_generation_groups_remain(explorer, mocks, tmp_path):
    path = tmp_path / "gone.ddd"
    path.write_bytes(Path(mocks["g2_card"]).read_bytes())
    data = TachoParser(str(path)).parse()
    path.unlink()
    explorer._parse_done(data, str(path))
    explorer.update()
    top = [explorer.tree.item(i, "text") for i in explorer.tree.get_children("")]
    assert any(text.startswith("Generation") for text in top)


def test_only_problems_carry_an_icon():
    from app.gui_explorer_structure import StructureMixin
    from core.structure import Unit
    icon = StructureMixin._unit_icon_name
    assert icon(Unit("section", "Overview", 0, 10, signature=True)) is None
    assert icon(Unit("section", "Overview", 0, 10)) is None
    assert icon(Unit("gap", "Padding", 0, 10)) is None
    assert icon(Unit("section", "Overview", 0, 10, signature=False)) == "status-error"
    assert icon(Unit("gap", "Unrecognised bytes", 0, 10)) == "status-warning"


def test_a_section_reads_in_words(built):
    from app.gui_explorer_structure import StructureMixin
    raw, units = _layout(built["vu"])
    section = units[0]
    assert [a.title for a in section.children] == [
        "Day", "Odometer at midnight", "Activity changes", "Signature"]
    assert section.children[2].spec == "VuActivityDailyRecord"
    cols, rows = StructureMixin._section_overview(None, section)
    shown = {row[0]: row[1] for row in rows}
    assert shown["Day"] == "15/11/2023"
    assert shown["Odometer at midnight"] == "4096 km"
    assert shown["Activity changes"].startswith("3  ·  ")
    # where it is in the file is there, behind the technical switch
    assert cols.technical >= {"Offset", "Length", "Record type"}


def test_a_day_line_and_a_period_line():
    from app.gui_explorer_structure import group_summary
    day = {"date": "01/05/2025", "odometer_km": 1000, "changes": [
        {"activity": "REST", "time": "00:00", "slot": "First"},
        {"activity": "DRIVE", "time": "06:00", "slot": "First"},
        {"activity": "REST", "time": "10:30", "slot": "First"}]}
    assert group_summary([day], "activities") == "1000 km  ·  Drive 4:30  ·  Rest 19:30"
    later = dict(day, date="03/05/2025")
    assert group_summary([later, day], "activities") == "2 days  ·  01/05/2025 – 03/05/2025"
    assert group_summary([]) == "None"
