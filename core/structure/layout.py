"""The units of a ``.ddd`` file in the order the file stores them.

The parser's result lists (events, places, activities ...) merge what several
parts of the file say: a driver card keeps every EF twice (generation 1 and
generation 2 copies) and a vehicle unit spreads one day over several arrays.
This module describes the file the other way round, as it is laid out:

* a generation-2 vehicle unit download is a sequence of TREP sections
  (``76 21`` ... ``76 35``), each a list of RecordArrays (Annex 1C Appendix 7);
* a generation-1 vehicle unit download is a sequence of TREP messages
  (``76 01`` ... ``76 05``), each followed by its RSA signature (Annex 1B);
* a card download is a sequence of elementary files (EF), each a data element
  followed by its signature element (STAP ``tag dtype length``).

Every :class:`Unit` carries its offset and length, the signature verdict the
parser already reached for it, and a *decoder*: the unit's own bytes decoded on
their own, with the same decoders the parser uses, so what a unit shows is
exactly what it holds. Decoding is lazy and cached, and a decoder that fails
yields no content instead of raising: the bytes are still shown.

Nothing here changes the parse result; the layout is built from the bytes and
the result of :class:`app.engine.TachoParser`.
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Optional

from core.utils.logger import get_logger

_log = get_logger(__name__)

#: Bytes shown in a hex dump at most (16 per row).
HEX_DUMP_LIMIT = 64 * 1024

#: Result keys that are bookkeeping, never content of one unit.
_NOT_CONTENT = {"metadata", "raw_tags", "coverage", "sections", "generations",
                "signature_verification", "ef_signature_verification"}

_SECTION_TITLES = {
    "Overview": "Overview",
    "Activities": "Activities",
    "EventsFaults": "Events and faults",
    "DetailedSpeed": "Detailed speed",
    "TechnicalData": "Technical data",
    "CardDownload": "Card download",
    "SensorSpecialData": "Sensor data",
    "SensorTrailer": "Sensor data",
}

#: Card EF names as Annex 1B/1C write them, by file identifier.
_EF_NAMES = {
    0x0002: "EF_ICC", 0x0005: "EF_IC",
    0x0501: "Application Identification", 0x0502: "Events Data",
    0x0503: "Faults Data", 0x0504: "Driver Activity Data",
    0x0505: "Vehicles Used", 0x0506: "Places", 0x0507: "Current Usage",
    0x0508: "Control Activity Data", 0x0509: "Company Activity Data",
    0x050A: "Workshop Calibration Data", 0x050B: "Sensor Installation Data",
    0x050C: "Controller Activity Data", 0x050E: "Card Download",
    0x0520: "Identification", 0x0521: "Driving Licence Info",
    0x0522: "Specific Conditions", 0x0523: "Vehicle Units Used",
    0x0524: "GNSS Places", 0x0525: "Application Identification V2",
    0x0526: "Places Authentication", 0x0527: "GNSS Places Authentication",
    0x0528: "Border Crossings", 0x0529: "Load Unload Operations",
    0x0530: "Load Type Entries", 0x0531: "VU Configuration",
    0xC100: "Card Certificate", 0xC101: "Card Sign Certificate",
    0xC108: "CA Certificate", 0xC109: "Link Certificate",
}


@dataclass
class Unit:
    """One part of the file: a section, an array, an EF, a signature, a gap."""

    kind: str                   # section | array | ef | signature | group | gap | content
    title: str                  # English; the GUI translates it
    offset: int
    length: int
    tag: str = ""               # "TREP 0x32", "EF 0x0504", "RecordArray 0x01"
    detail: str = ""            # "90 × 2 B", a date, ...
    signature: Optional[bool] = None   # True verified, False failed, None not checked
    children: list = field(default_factory=list)
    decoder: Optional[Callable[[], dict]] = None
    _content: Optional[dict] = field(default=None, repr=False)

    @property
    def end(self) -> int:
        return self.offset + self.length

    def content(self) -> dict:
        """``{name: list-of-records | dict}`` this unit decodes to (cached)."""
        if self._content is None:
            content: dict = {}
            if self.decoder is not None:
                try:
                    content = self.decoder() or {}
                except Exception:   # the bytes are still shown
                    _log.debug("Layout decoder for %s at 0x%X failed",
                               self.title, self.offset, exc_info=True)
                    content = {}
            self._content = content
        return self._content

    def walk(self):
        yield self
        for child in self.children:
            yield from child.walk()


# ── helpers ──────────────────────────────────────────────────────────────────

def content_title(key: str) -> str:
    """English title of a content group (a parser result key)."""
    from core.utils.report_format import DICT_SECTIONS, EXPORT_SECTIONS
    for name, title in list(EXPORT_SECTIONS) + list(DICT_SECTIONS):
        if name == key:
            return title
    return {"driver": "Driver / Cardholder", "vehicle": "Vehicle",
            "record_arrays": "Record Arrays",
            "elementary_files": "Elementary Files"}.get(key, key)


def hex_rows(data: bytes, base: int = 0, limit: int = HEX_DUMP_LIMIT) -> list:
    """``[offset, hex, ascii]`` rows of 16 bytes, at most *limit* bytes."""
    rows = []
    for start in range(0, min(len(data), limit), 16):
        chunk = data[start:start + 16]
        text = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        rows.append([f"0x{base + start:08X}", chunk.hex(" "), text])
    return rows


def _fresh_results() -> dict:
    from core.registry.models import TachoResult
    return TachoResult().to_dict()


def _content_of(fresh: dict) -> dict:
    """What a decoder added to a fresh result dict."""
    template = _fresh_results()
    out = {}
    for key, value in fresh.items():
        if key in _NOT_CONTENT or str(key).startswith("_"):
            continue
        base = template.get(key)
        if isinstance(value, dict) and isinstance(base, dict):
            value = {k: v for k, v in value.items() if base.get(k) != v}
        if isinstance(value, set):
            value = sorted(value, key=str)
        if value in (None, "", [], {}) or value == base:
            continue
        out[key] = value
    return out


def _time_real(raw: bytes) -> str:
    if len(raw) < 4:
        return ""
    seconds = struct.unpack(">I", raw[:4])[0]
    if seconds in (0, 0xFFFFFFFF):
        return ""
    try:
        return datetime.fromtimestamp(seconds, tz=timezone.utc).strftime("%d/%m/%Y")
    except (OverflowError, OSError, ValueError):
        return ""


def _signature_list(results: dict) -> list:
    sig = results.get("signature_verification") or {}
    return [entry for entry in (sig.get("treps") or []) if isinstance(entry, dict)]


class _SignatureCursor:
    """Hand out the per-section verdicts in file order, matched by TREP."""

    def __init__(self, entries):
        self._entries = entries
        self._next = 0

    def take(self, trep: int) -> Optional[bool]:
        wanted = f"0x{trep:02X}"
        for index in range(self._next, len(self._entries)):
            if str(self._entries[index].get("trep", "")).upper() == wanted.upper():
                self._next = index + 1
                valid = self._entries[index].get("signature_valid")
                return valid if isinstance(valid, bool) else None
        return None


def _gaps(raw: bytes, units: list, start: int = 0, end: Optional[int] = None) -> list:
    """Units for the bytes between *units* (padding or unrecognised)."""
    end = len(raw) if end is None else end
    out = []
    cursor = start
    for unit in sorted(units, key=lambda u: u.offset):
        if unit.offset > cursor:
            out.append(_gap(raw, cursor, unit.offset))
        cursor = max(cursor, unit.end)
    if cursor < end:
        out.append(_gap(raw, cursor, end))
    return out


def _gap(raw: bytes, start: int, end: int) -> Unit:
    body = raw[start:end]
    padding = all(b in (0x00, 0xFF) for b in body)
    return Unit("gap", "Padding" if padding else "Unrecognised bytes", start, end - start)


# ── generation-2 vehicle unit ────────────────────────────────────────────────

def _vu_g2(raw: bytes, results: dict) -> list:
    from core.parser import vu_dispatcher as vd

    cursor = _SignatureCursor(_signature_list(results))
    units = []
    for sec in vd.iter_vu_sections(raw):
        trep = sec["trep"]
        marker = sec["marker"]
        tag = f"TREP 0x{trep:02X}"
        if sec.get("interface") is not None:
            body = bytes(sec["interface"])
            units.append(Unit("section", "Download interface version", marker,
                              2 + len(body), tag=tag, detail=body.hex(" ")))
            continue
        if sec.get("card_tlv"):
            info = sec["card_tlv"]
            start, size = info["offset"], int(info.get("bytes") or 0)
            section = Unit("section", "Card download", marker, 2 + size, tag=tag)
            section.children = _embedded_card(raw[start:start + size], start, results)
            units.append(section)
            continue
        name = vd.TREP_SECTIONS.get(trep, f"TREP_0x{trep:02X}")
        records = sec["records"]
        end = max((rec_end for (_p, _rt, _rs, _nr, rec_end) in records), default=marker + 2)
        section = Unit("section", _SECTION_TITLES.get(name, name), marker, end - marker,
                       tag=tag)
        version = vd.event_fault_version_for_trep(trep)
        for (pos, rt, rs, nr, rec_end) in records:
            section.children.append(_g2_array(raw, pos, rt, rs, nr, rec_end, trep, version))
            if name == "Activities" and rt == 0x06 and nr and not section.detail:
                section.detail = _time_real(raw[pos + 5:pos + 5 + rs])
        if any(rt == 0x08 for (_p, rt, _rs, _nr, _e) in records):
            section.signature = cursor.take(trep)
        section.decoder = _array_index(section)
        units.append(section)
    return units


def _g2_array(raw, pos, rt, rs, nr, rec_end, trep, version) -> Unit:
    from core.parser import vu_dispatcher as vd

    name = (vd.RECORD_TYPES.get(rt) or (f"RecordType 0x{rt:02X}",))[0]
    unit = Unit("array", name, pos, rec_end - pos, tag=f"RecordArray 0x{rt:02X}",
                detail=f"{nr} × {rs} B")

    def decode():
        records = []
        cursor = pos + 5
        for _index in range(nr):
            decoded = vd.decode_vu_record(rt, raw[cursor:cursor + rs], version=version,
                                          trep=trep)
            if isinstance(decoded, dict):
                records.append(decoded)
            cursor += rs
        return {name: records} if records else {}

    unit.decoder = decode
    return unit


def _array_index(section: Unit) -> Callable[[], dict]:
    """A section's own table: the RecordArrays it is made of."""
    def decode():
        rows = [{"record_array": child.title,
                 "record_type": child.tag.replace("RecordArray ", ""),
                 "records": child.detail,
                 "offset": f"0x{child.offset:08X}",
                 "length": child.length}
                for child in section.children]
        return {"record_arrays": rows} if rows else {}
    return decode


# ── generation-1 vehicle unit ────────────────────────────────────────────────

def _vu_g1(raw: bytes, results: dict) -> list:
    from core.parser import g1_walker

    cursor = _SignatureCursor(_signature_list(results))
    units = []
    for msg in g1_walker.iter_g1_vu_messages(raw):
        trep = msg["trep"]
        tag = f"TREP 0x{trep:02X}"
        name = g1_walker.TREP_NAMES.get(trep, f"TREP_0x{trep:02X}")
        section = Unit("section", _SECTION_TITLES.get(name, name), msg["pos"],
                       msg["end"] - msg["pos"], tag=tag)
        body_start, body_end = msg["body_start"], msg["body_end"]
        if msg.get("card_region"):
            section.title = "Card download"
            section.children = _embedded_card(raw[body_start:body_end], body_start, results)
            units.append(section)
            continue
        if trep == 0x02:
            section.detail = _time_real(raw[body_start:body_start + 4])
        section.decoder = _g1_decoder(trep, raw[body_start:body_end], msg["pos"])
        if msg["sig_len"]:
            section.signature = cursor.take(trep)
            section.children.append(Unit("signature", "Signature", body_end,
                                         msg["sig_len"], tag="RSA 1024",
                                         signature=section.signature))
        units.append(section)
    return units


def _g1_decoder(trep, body, offset):
    def decode():
        from core.parser.g1_walker import decode_g1_message
        fresh = _fresh_results()
        decode_g1_message(trep, body, fresh, message_offset=offset)
        return _content_of(fresh)
    return decode


# ── cards ────────────────────────────────────────────────────────────────────

def _ef_statuses(results: dict) -> dict:
    out: dict = {}
    for entry in ((results.get("ef_signature_verification") or {}).get("ef_results") or []):
        if not isinstance(entry, dict):
            continue
        try:
            tag = int(str(entry.get("tag")), 16)
        except ValueError:
            continue
        status = str(entry.get("status") or "").lower()
        verdict: Optional[bool]
        if status == "verified":
            verdict = True
        elif any(word in status for word in ("fail", "invalid", "mismatch")):
            verdict = False
        else:
            verdict = None
        out.setdefault((tag, str(entry.get("gen") or "")), verdict)
    return out


def _occurrences(raw_tags: dict) -> list:
    occ = []
    for key, entries in (raw_tags or {}).items():
        if key == "Unparsed Data":
            continue
        for entry in entries or []:
            try:
                occ.append({"offset": int(str(entry["offset"]), 16),
                            "tag": int(str(entry["tag_id"]), 16),
                            "dtype": str(entry.get("data_type") or ""),
                            "length": int(entry.get("length") or 0),
                            "depth": int(entry.get("depth") or 0),
                            "name": str(entry.get("tag_name") or "")})
            except (KeyError, TypeError, ValueError):
                continue
    occ.sort(key=lambda o: (o["offset"], o["depth"]))
    return occ


def _header_size(raw: bytes, occ: dict) -> int:
    """Bytes between the element start and its value."""
    if occ["dtype"].startswith("0x"):
        return 5    # STAP: tag(2) dtype(1) length(2)
    from core.parser.deterministic import DeterministicParser
    read = DeterministicParser()._try_read_ber_tlv(raw, occ["offset"], len(raw))
    return read[2] if read else 0


def _ef_title(tag: int, name: str) -> str:
    if tag in _EF_NAMES:
        return _EF_NAMES[tag]
    return re.sub(r"^(G1|G2|G22)_", "", name) or f"Tag 0x{tag:04X}"


def _card_units(raw: bytes, results: dict, raw_tags: dict, base: int = 0,
                generation_source: bytes = b"") -> list:
    """The EF elements of a card stream; *raw* is the card's own bytes."""
    statuses = _ef_statuses(results)
    elements = []
    for occ in _occurrences(raw_tags):
        hdr = _header_size(raw, occ)
        start = occ["offset"]
        dtype = int(occ["dtype"], 16) if occ["dtype"].startswith("0x") else None
        unit = Unit("ef", _ef_title(occ["tag"], occ["name"]), base + start,
                    hdr + occ["length"], tag=f"EF 0x{occ['tag']:04X}")
        payload = raw[start + hdr:start + hdr + occ["length"]]
        unit._depth = occ["depth"]           # type: ignore[attr-defined]
        if dtype in (0x01, 0x03):
            unit.kind = "signature"
            unit.title = "Signature"
            gen = "G1" if dtype == 0x01 else "G2"
            unit.signature = statuses.get((occ["tag"], gen))
        else:
            unit.decoder = _card_decoder(occ["tag"], payload, dtype,
                                         generation_source or raw, base + start)
        unit._dtype = dtype                  # type: ignore[attr-defined]
        unit._tag = occ["tag"]               # type: ignore[attr-defined]
        elements.append(unit)

    # Nest elements inside the container that holds them, and each signature
    # under the data element it signs (the element right before it, same tag).
    top: list = []
    stack: list = []
    for unit in elements:
        while stack and unit.offset >= stack[-1].end:
            stack.pop()
        depth = getattr(unit, "_depth", 0)
        if depth and stack:
            stack[-1].children.append(unit)
        else:
            siblings = top
            if (unit.kind == "signature" and siblings
                    and siblings[-1].kind == "ef"
                    and getattr(siblings[-1], "_tag", None) == getattr(unit, "_tag", None)):
                siblings[-1].children.append(unit)
                siblings[-1].signature = unit.signature
                continue
            top.append(unit)
        stack.append(unit)

    # The download holds the generation-1 application first and the
    # generation-2 one after it (dtype 00/01, then 02/03): one group each.
    groups: list = []
    for unit in top:
        dtype = getattr(unit, "_dtype", None)
        gen = "2" if dtype in (0x02, 0x03) else "1"
        if not groups or groups[-1][0] != gen:
            groups.append((gen, []))
        groups[-1][1].append(unit)
    if len(groups) <= 1 and all(getattr(u, "_dtype", None) is None for u in top):
        return top
    out = []
    for gen, members in groups:
        title = ("Tachograph application, generation 2" if gen == "2"
                 else "Tachograph application, generation 1")
        start = members[0].offset
        end = max(part.end for member in members for part in member.walk())
        group = Unit("group", title, start, end - start,
                     tag="DF Tachograph_G2" if gen == "2" else "DF Tachograph",
                     children=members)
        group.decoder = _ef_index(group)
        out.append(group)
    return out


def _ef_index(group: Unit) -> Callable[[], dict]:
    def decode():
        rows = []
        for child in group.children:
            sig = child.signature
            rows.append({"elementary_file": child.title,
                         "file_identifier": child.tag.replace("EF ", ""),
                         "offset": f"0x{child.offset:08X}",
                         "length": child.length,
                         "signature": ("verified" if sig is True else
                                       "not valid" if sig is False else
                                       "not checked" if any(c.kind == "signature"
                                                            for c in child.children)
                                       else "not signed")})
        return {"elementary_files": rows} if rows else {}
    return decode


def _card_decoder(tag, payload, dtype, generation_source, offset):
    def decode():
        from core.parser.deterministic import DeterministicParser
        dp = DeterministicParser()
        dp.results = _fresh_results()
        dp.is_vu = False
        dp.generation = dp._detect_generation(generation_source)
        dp._dispatch_decoder(tag, payload, dtype=dtype, offset=offset)
        dp._finalize_specific_conditions()
        return _content_of(dp.results)
    return decode


def _embedded_card(chunk: bytes, base: int, results: dict) -> list:
    """A card image carried inside a vehicle unit download (TREP 06)."""
    from core.parser.deterministic import DeterministicParser
    try:
        parsed = DeterministicParser().parse(chunk, is_vu=False)
    except Exception:
        _log.debug("Embedded card walk failed", exc_info=True)
        return []
    return _card_units(chunk, results, parsed.get("raw_tags") or {}, base=base)


# ── entry point ──────────────────────────────────────────────────────────────

def build_layout(raw: bytes, results: dict) -> list:
    """The file's units in file order, with gaps between them as units too.

    *raw* is the file's bytes and *results* what the parser made of them.
    Returns an empty list when the bytes do not match the result (a different
    file, or no bytes).
    """
    raw = bytes(raw or b"")
    if not raw or not isinstance(results, dict):
        return []
    meta = results.get("metadata") or {}
    generation = str(meta.get("generation") or "")
    try:
        if meta.get("is_vu"):
            if generation.startswith("G2"):
                units = _vu_g2(raw, results)
            else:
                units = _vu_g1(raw, results)
        else:
            units = _card_units(raw, results, results.get("raw_tags") or {})
    except Exception:
        _log.warning("File layout could not be built", exc_info=True)
        return []
    if not units:
        return []
    units = sorted(units + _gaps(raw, units), key=lambda u: u.offset)
    return units
