"""Pin the exact output of BOTH nested-value renderers for every defined case.

The two renderers are:

* the GUI renderer ``app.gui.fmt_val`` (dict input → ``_fmt_dict``), whose
  generic fallback is a raw ``key=fmt_val(value)`` for *every* key;
* the report/export renderer ``core.utils.report_format.fmt_value`` (dict input
  → ``_fmt_dict``), whose generic fallback is ``Humanized Key: fmt_value(value)``
  and hides ``HIDDEN_KEYS`` plus underscore-prefixed keys.

They share the known-structure branches (absent slot, GNSS coordinates nested or
direct, ``card_number``, ``plate``/``nation``) through
``core.utils.report_format.fmt_known_structure``; only the generic fallback
differs, on purpose. Every expectation below is a literal written from that
specification — never recomputed by calling the code under test.
"""
import pytest

pytest.importorskip("tkinter")

from app.gui import fmt_val  # noqa: E402
from core.utils.report_format import fmt_known_structure, fmt_value  # noqa: E402

DASH = "\u2014"      # em dash: "no information"
ELLIPSIS = "\u2026"  # truncation marker


# ── Known structures: rendered identically by BOTH renderers ────────────────

KNOWN_STRUCTURE_CASES = [
    # absent card slot
    ({"present": False}, DASH),
    # nested geo (gnss_place) — both / only latitude / only longitude / neither
    ({"geo": {"latitude_deg": 41.90278, "longitude_deg": 12.49637}},
     "41.90278, 12.49637"),
    ({"geo": {"latitude_deg": 41.90278}}, ""),
    ({"geo": {"longitude_deg": 12.49637}}, ""),
    ({"geo": {"latitude_deg": None, "longitude_deg": None}}, ""),
    # direct coordinates — both / one missing
    ({"latitude_deg": 48.85661, "longitude_deg": 2.35222}, "48.85661, 2.35222"),
    ({"latitude_deg": 48.85661}, ""),
    # card_number (FullCardNumber) — normal / blank / lowercase / int
    ({"card_number": "IT1234567890"}, "IT1234567890"),
    ({"card_number": ""}, DASH),
    ({"card_number": "abcd1234"}, "abcd1234"),
    ({"card_number": 1234567890}, "1234567890"),
    # plate normal — nation absent / None / "No information" / "I"
    ({"plate": "AB123CD"}, "AB123CD"),
    ({"plate": "AB123CD", "nation": None}, "AB123CD"),
    ({"plate": "AB123CD", "nation": "No information"}, "AB123CD"),
    ({"plate": "AB123CD", "nation": "I"}, "I AB123CD"),
    # plate blank "" — crossed with every nation
    ({"plate": ""}, DASH),
    ({"plate": "", "nation": None}, DASH),
    ({"plate": "", "nation": "No information"}, DASH),
    ({"plate": "", "nation": "I"}, DASH),
    # plate "   " — crossed with every nation
    ({"plate": "   "}, DASH),
    ({"plate": "   ", "nation": None}, DASH),
    ({"plate": "   ", "nation": "No information"}, DASH),
    ({"plate": "   ", "nation": "I"}, DASH),
    # plate "????" (all-unknown) — crossed with every nation
    ({"plate": "????"}, DASH),
    ({"plate": "????", "nation": None}, DASH),
    ({"plate": "????", "nation": "No information"}, DASH),
    ({"plate": "????", "nation": "I"}, DASH),
]


@pytest.mark.parametrize("d,expected", KNOWN_STRUCTURE_CASES,
                         ids=[repr(c[0]) for c in KNOWN_STRUCTURE_CASES])
def test_known_structures_render_identically_in_both_renderers(d, expected):
    assert fmt_val(d) == expected
    assert fmt_value(d) == expected


# ── Generic fallback: the two renderers differ deliberately ──────────────────

# (input dict, GUI expected, report expected)
GENERIC_FALLBACK_CASES = [
    # HIDDEN_KEYS member: GUI shows it, report hides it
    ({"source": "x"}, "source=x", ""),
    # mixing hidden and visible keys
    ({"name": "rec", "size": 12, "speed": 5}, "name=rec, size=12, speed=5",
     "Speed: 5"),
    # underscore-prefixed key: GUI shows it, report hides it
    ({"_key": "v"}, "_key=v", ""),
    # ISO timestamp: GUI shortens it, report shortens it too
    ({"t": "2024-01-23T08:37:00+00:00"}, "t=2024-01-23 08:37",
     "T: 2024-01-23 08:37"),
    # 0xFFFFFF sentinel + float
    ({"big": 16777215, "f": 1.5}, "big=N/A, f=1.5", "Big: N/A, F: 1.5"),
    # bool
    ({"flag": True}, "flag=Yes", "Flag: Yes"),
    # nested dict flattened by each renderer's own convention
    ({"outer": {"a": 1}}, "outer=a=1", "Outer: A: 1"),
    # list
    ({"xs": [1, 2]}, "xs=1, 2", "Xs: 1, 2"),
    # empty geo dict → falls through to the generic fallback
    ({"geo": {}}, "geo=", "Geo: "),
]


@pytest.mark.parametrize("d,gui_expected,report_expected", GENERIC_FALLBACK_CASES,
                         ids=[repr(c[0]) for c in GENERIC_FALLBACK_CASES])
def test_generic_fallback_differs_by_design(d, gui_expected, report_expected):
    assert fmt_val(d) == gui_expected
    assert fmt_value(d) == report_expected


# ── 120-character cap + ellipsis in BOTH renderers ──────────────────────────

_CROSSING_KEYS = [f"k{i:02d}" for i in range(10)]
_CROSSING_INPUT = {k: "0123456789ab" for k in _CROSSING_KEYS}  # 12-char values

# GUI: "key=value" (16 chars) joined with ", " → 178 chars, cut at 120 + "…"
_GUI_CROSSING = (
    "k00=0123456789ab, k01=0123456789ab, k02=0123456789ab, k03=0123456789ab, "
    "k04=0123456789ab, k05=0123456789ab, k06=01234567\u2026"
)
# Report: "Humanized Key: value" (17 chars) joined with ", " → 188, cut at 120 + "…"
_REPORT_CROSSING = (
    "K00: 0123456789ab, K01: 0123456789ab, K02: 0123456789ab, K03: 0123456789ab, "
    "K04: 0123456789ab, K05: 0123456789ab, K06: 0\u2026"
)


def test_generic_fallback_caps_at_120_plus_ellipsis_in_both_renderers():
    gui = fmt_val(_CROSSING_INPUT)
    report = fmt_value(_CROSSING_INPUT)

    # both rendered strings exceed the 120-char bound and are cut + ellipsised
    assert gui == _GUI_CROSSING
    assert report == _REPORT_CROSSING
    assert len(gui) == 121 and gui.endswith(ELLIPSIS)
    assert len(report) == 121 and report.endswith(ELLIPSIS)


# ── The shared known-structure helper's public contract ─────────────────────

def test_fmt_known_structure_returns_rendering_or_none():
    """C2: one public function owns the shared branches; ``None`` means
    'not a known structure, caller supplies its own fallback'."""
    assert fmt_known_structure({"present": False}) == DASH
    assert fmt_known_structure({"card_number": "IT1"}) == "IT1"
    assert fmt_known_structure({"latitude_deg": 1.0, "longitude_deg": 2.0}) == (
        "1.00000, 2.00000")
    assert fmt_known_structure({"speed": 5}) is None
    assert fmt_known_structure({}) is None
