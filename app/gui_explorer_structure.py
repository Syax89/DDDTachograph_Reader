"""``TachoExplorer`` — the file-structure tree: the file's units in file order.

Each node is one part of the file as it is stored (a TREP section, a
RecordArray, a card EF, a signature, padding), built by
:func:`core.structure.build_layout`. Selecting a node decodes that unit's own
bytes and shows the records; the *Bytes* switch of the table shows the same
unit as a hex dump.
"""
from app.gui_base import (  # noqa: F401
    HIDDEN_KEYS,
    _,
    _icon,
    _kv_rows,
    _log,
    _rows_for,
    fmt_val,
    load_trace,
    tk,
    ui_text,
)
from app.gui_text import Columns
from core.structure import build_layout, content_title, hex_rows
from core.utils.activity_stats import compute_activity_totals, recorded_until_seconds

#: Tree rows inserted between two pumps of the event loop.
_PUMP_EVERY = 200


def _signature_text(verdict):
    if verdict is True:
        return _("Signature verified")
    if verdict is False:
        return _("Signature not valid")
    return _("Signature not checked")


def _signature_words(state):
    return {"verified": _("Signature verified"),
            "not valid": _("Signature not valid"),
            "not checked": _("Signature not checked"),
            "not signed": _("Not signed")}.get(state, state)


def _flat(record):
    """A record with its nested dicts opened one level (``activity`` → its fields)."""
    if not any(isinstance(v, dict) for v in record.values()):
        return record
    out = {}
    for key, value in record.items():
        if isinstance(value, dict):
            for inner, inner_value in value.items():
                free = inner == key or (inner not in record and inner not in out)
                name = inner if free else f"{key}_{inner}"
                out[name] = inner_value
        else:
            out[key] = value
    return out


def _hm(minutes):
    return f"{int(minutes) // 60}:{int(minutes) % 60:02d}"


def _day_totals(record, cuts, one_driver=True):
    """A day record with its activity changes summed up instead of listed.

    The changes themselves are in the day's chart (Daily Activities); here the
    row says how many there are and what they add up to. The last day of a
    download ends where the recording ends (*cuts*: the parser's
    ``recorded_until`` by date), exactly as in every other view.
    """
    changes = record.get("changes")
    if not isinstance(changes, list):
        return record
    cut = cuts.get(record.get("date"))
    totals = compute_activity_totals(changes, cut, one_driver=one_driver)
    out = {k: v for k, v in record.items() if k != "changes"}
    out["changes_count"] = len(changes)
    for activity in ("DRIVE", "WORK", "AVAILABLE", "REST", "UNKNOWN"):
        out[activity.lower()] = _hm(totals.get(activity, 0))
    return out


#: Words that say nothing on their own in a one-line summary.
_FILLER = {"", "yes", "no", "n/a", "none", "0"}


def _first_cells(record, limit=3):
    """The first few readable values of a record, for a one-line summary."""
    cols, rows = _rows_for([_flat(record)], None)
    technical = getattr(cols, "technical", frozenset())
    out = []
    for col, cell in zip(cols, rows[0] if rows else [], strict=False):
        text = str(cell).strip()
        if col in technical or text.lower() in _FILLER:
            continue
        out.append(text)
        if len(out) == limit:
            break
    return "  ·  ".join(out)


def _activity_line(changes, one_driver):
    totals = compute_activity_totals(changes, one_driver=one_driver)
    parts = [f"{ui_text.label(name.title())} {_hm(totals.get(name, 0))}"
             for name in ("DRIVE", "WORK", "AVAILABLE", "REST", "UNKNOWN")
             if totals.get(name)]
    return "  ·  ".join(parts)


def _days_line(days, one_driver):
    """One day: its odometer and hours; several: how many and which period."""
    if len(days) == 1:
        day = days[0]
        odometer = day.get("odometer_km") or day.get("odometer_midnight")
        parts = [f"{fmt_val(odometer, key='odometer_km')} km"] if isinstance(odometer, (int, float)) else []
        parts.append(_activity_line(day.get("changes") or [], one_driver))
        return "  \u00b7  ".join(part for part in parts if part)
    dates = sorted((str(d.get("date")) for d in days if d.get("date")),
                   key=lambda text: text[6:10] + text[3:5] + text[0:2])
    period = f"  \u00b7  {dates[0]} \u2013 {dates[-1]}" if dates else ""
    return _("{count} days").format(count=len(days)) + period


def _card_session(record):
    """``SURNAME First  03:49 → 15:50`` for a card insertion/withdrawal."""
    flat = _flat(record)
    name = " ".join(str(flat.get(k) or "").strip()
                    for k in ("holder_surname", "holder_first_names")).strip()
    begin = fmt_val(flat.get("insertion_time"), key="insertion_time")
    end = fmt_val(flat.get("withdrawal_time"), key="withdrawal_time")
    times = f"{begin} → {end}" if end else begin
    return f"{name}  {times}".strip()


def group_summary(value, key=None, one_driver=True):
    """One line that says what a content group holds, in words."""
    if isinstance(value, set):
        value = sorted(value, key=str)
    if isinstance(value, dict):
        return _first_cells(value)
    if not isinstance(value, (list, tuple)) or not value:
        return _("None")
    records = [item for item in value if isinstance(item, dict)]
    if key == "activities" and records:
        return _days_line(records, one_driver)
    if key in ("card_iw_records", "VuCardIWRecord") and records:
        return ";  ".join(_card_session(r) for r in records[:3]) + (
            "  …" if len(records) > 3 else "")
    if len(value) == 1 and records:
        return _first_cells(records[0])
    return _("{count} records").format(count=len(value))


def array_summary(array, signature=None, one_driver=False):
    """What one RecordArray of a vehicle-unit section says, in one line."""
    rt = int(array.tag.rsplit("0x", 1)[-1], 16) if "0x" in array.tag else -1
    if rt == 0x08:
        return _signature_text(signature)
    records = next(iter(array.content().values()), [])
    if not records:
        return _("None")
    if rt in (0x01, 0x29):
        changes = [r.get("activity") for r in records if isinstance(r.get("activity"), dict)]
        return f"{len(records)}  ·  {_activity_line(changes, one_driver)}"
    if rt == 0x0D:
        return group_summary(records, "card_iw_records")
    special = _ARRAY_LINES.get(rt)
    if special is not None:
        try:
            return _DOT.join(special(r) for r in records[:3]) + (
                "  \u2026" if len(records) > 3 else "")
        except (AttributeError, KeyError, TypeError, ValueError):
            pass                         # an odd record: the generic line below
    return group_summary(records)


_DOT = "  \u00b7  "


def _date_only(value):
    return fmt_val(value, key="date").split(" ")[0]


def _time_real_hex(value):
    """A certificate date ('642e0b80', TimeReal in hex) as dd/mm/yyyy."""
    from datetime import datetime, timezone
    seconds = int(str(value), 16)
    return datetime.fromtimestamp(seconds, tz=timezone.utc).strftime("%d/%m/%Y")


def _certificate_line(r):
    return (f"{r.get('chr')} \u2190 {r.get('car')}{_DOT}"
            f"{_time_real_hex(r.get('effective_date'))} \u2013 "
            f"{_time_real_hex(r.get('expiration_date'))}")


def _slots_line(r):
    slots = r.get("slots") or {}
    return (f"{fmt_val(0, key='card_slot')}: {ui_text.data_text(slots.get('driver_slot'))}{_DOT}"
            f"{fmt_val(1, key='card_slot')}: {ui_text.data_text(slots.get('codriver_slot'))}")


def _plate_line(r):
    nation = fmt_val(r.get("nation"), key="nation") if r.get("nation") else ""
    return f"{r.get('plate')} ({nation})" if nation else str(r.get("plate"))


def _download_line(r):
    card = r.get("card") or {}
    return _DOT.join(str(part) for part in (
        fmt_val(r.get("downloading_time"), key="downloading_time"),
        r.get("company_or_workshop_name"), card.get("card_number")) if part)


def _place_line(r):
    return " ".join(str(part) for part in (
        ui_text.data_text(str(r.get("entry_type") or "").title()),
        fmt_val(r.get("timestamp"), key="timestamp"),
        fmt_val(r.get("nation"), key="nation") if r.get("nation") else "") if part)


#: One-line readers of the record types whose generic line says too little.
_ARRAY_LINES = {
    0x02: _slots_line,
    0x04: _certificate_line, 0x0F: _certificate_line,
    0x05: lambda r: f"{fmt_val(r['odometer_km'], key='odometer_km')} km",
    0x06: lambda r: _date_only(r["time"]),
    0x0B: _plate_line, 0x24: _plate_line,
    0x14: _download_line,
    0x1C: _place_line,
}


#: Content groups whose first column names a part of the file.
_NAMED_PARTS = {"record_arrays": "record_array", "elementary_files": "elementary_file"}


def content_rows(value, key=None, cuts=None, one_driver=True):
    """``(columns, rows)`` for one content group of a unit."""
    if isinstance(value, set):
        value = sorted(value, key=str)
    if isinstance(value, dict):
        shown = {k: v for k, v in value.items()
                 if k not in HIDDEN_KEYS and not str(k).startswith("_")}
        return _kv_rows(shown)
    if isinstance(value, (list, tuple)):
        if value and all(isinstance(item, dict) for item in value):
            records = [_day_totals(_flat(item), cuts or {}, one_driver)
                       for item in value]
            part = _NAMED_PARTS.get(key)
            if part:
                records = [dict(r, **{part: ui_text.label(r.get(part))}) for r in records]
            if key == "elementary_files":
                records = [dict(r, signature=_signature_words(r.get("signature")))
                           for r in records]
            return _rows_for(records, None)
        return [_("Value")], [[fmt_val(item)] for item in value]
    return [_("Value")], [[fmt_val(value)]]


#: What an empty part says instead of a bare hex dump (the bytes stay one
#: switch away). Functions, so the text follows the interface language.
_EMPTY_WORDS = {
    "array": lambda: _("No records: this array is empty and holds only its header."),
    "blank": lambda: _("No records: every slot of this file is blank (never written)."),
    "terminator": lambda: _("No data: this part only marks the end of the sensor download."),
}


class StructureMixin:
    """The file-structure tree and the views of its units."""

    def _file_layout(self, data):
        """The units of the open file, or ``[]`` when its bytes are not at hand.

        The file is read again (the parse result keeps no bytes) and must be the
        size the parser saw, so a file changed on disk since is never shown as
        the structure of the result on screen.
        """
        self._layout_bytes = b""
        path = getattr(self, "current_file", None)
        if not path:
            return []
        try:
            with open(path, "rb") as handle:
                raw = handle.read()
        except OSError:
            return []
        size = (data.get("metadata") or {}).get("file_size_bytes")
        if isinstance(size, int) and size and size != len(raw):
            return []
        with load_trace.span("build_layout", size=len(raw)):
            units = build_layout(raw, data)
        if units:
            self._layout_bytes = raw
        return units

    def _populate_structure(self, units):
        """Add the *File Structure* node and one child per unit, in file order."""
        root = self.tree.insert("", tk.END, text=_("File Structure"),
                                image=_icon("raw-data", 16, self.tree) or "")
        self._payloads[root] = ("__unit_index__", units)
        self._structure_rows = 0
        for unit in units:
            self._add_unit(root, unit)
        return root

    def _unit_text(self, unit):
        """Tree text: the part's name only (an Activities section keeps its day).

        Identifiers, counts, offsets and sizes are in the table of the part,
        not in the tree.
        """
        title = ui_text.label(unit.title)
        return f"{title} {unit.detail}" if unit.detail and unit.kind == "section" else title

    @staticmethod
    def _unit_icon_name(unit):
        """An icon only where something is wrong: a signature that did not
        verify, or bytes no part of the file explains. A verified part is
        drawn plain (its verdict is in the table header)."""
        if unit.signature is False:
            return "status-error"
        if unit.kind == "gap" and unit.title != "Padding":
            return "status-warning"
        return None

    def _add_unit(self, parent, unit):
        icon = self._unit_icon_name(unit)
        iid = self.tree.insert(parent, tk.END, text=self._unit_text(unit),
                               image=(_icon(icon, 16, self.tree) if icon else "") or "")
        self._payloads[iid] = ("__unit__", unit, None)
        self._structure_rows = getattr(self, "_structure_rows", 0) + 1
        if self._structure_rows % _PUMP_EVERY == 0:
            self._pump_render()
        # A unit that holds several kinds of records (a generation-1 message,
        # a card EF that fills two result lists) gets one child per kind, so
        # every list has its own table.
        if unit.kind in ("section", "ef") and unit.decoder is not None:
            groups = unit.content()
            if len(groups) > 1:
                for key in groups:
                    child = self.tree.insert(
                        iid, tk.END, text=ui_text.label(content_title(key)))
                    self._payloads[child] = ("__unit__", unit, key)
        for child in unit.children:
            self._add_unit(iid, child)
        return iid

    def _unit_meta(self, unit):
        parts = [_("Offset {offset} · {length} bytes").format(
            offset=f"0x{unit.offset:08X}", length=unit.length)]
        if unit.tag:
            parts.append(unit.tag)
        if unit.spec:
            parts.append(f"{unit.spec} ({unit.detail})" if unit.detail else unit.spec)
        if unit.kind in ("section", "ef", "signature") and (
                unit.signature is not None or unit.kind == "signature"
                or any(c.kind == "signature" for c in unit.children)):
            parts.append(_signature_text(unit.signature))
        return "  ·  ".join(parts)

    def _unit_bytes(self, unit):
        raw = getattr(self, "_layout_bytes", b"") or b""
        rows = hex_rows(raw[unit.offset:unit.end], base=unit.offset)
        return [_("Offset"), _("Hex"), _("Text")], rows

    def _show_unit(self, unit, key=None):
        """Show a unit: its records, or its bytes when it decodes to nothing."""
        groups = unit.content()
        cuts = {day.get("date"): recorded_until_seconds(day)
                for day in ((getattr(self, "_opened_data", None) or {}).get("activities") or [])
                if isinstance(day, dict) and recorded_until_seconds(day) is not None}
        one_driver = not ((getattr(self, "_opened_data", None) or {})
                          .get("metadata") or {}).get("is_vu")
        title = self._unit_text(unit)
        meta = self._unit_meta(unit)
        byte_view = self._unit_bytes(unit)
        if key is None and unit.children and all(c.kind == "array" for c in unit.children):
            cols, rows = self._section_overview(unit)
        elif key is None and unit.kind == "group":
            cols, rows = self._group_overview(unit, one_driver)
        elif key is not None and key in groups:
            title = f"{title} — {ui_text.label(content_title(key))}"
            cols, rows = content_rows(groups[key], key, cuts, one_driver)
        elif len(groups) == 1:
            only = next(iter(groups))
            cols, rows = content_rows(groups[only], only, cuts, one_driver)
        elif groups:
            cols = [_("Content"), _("Value")]
            rows = [[ui_text.label(content_title(k)), group_summary(v, k, one_driver)]
                    for k, v in groups.items()]
        elif unit.empty in _EMPTY_WORDS:
            cols, rows = [_("Content")], [[_EMPTY_WORDS[unit.empty]()]]
        else:
            cols, rows = byte_view
            byte_view = None
        self._show_table(title, cols, rows, meta, alternate=byte_view)

    def _show_unit_index(self, units):
        cols = [_("Unit"), _("Tag"), _("Offset"), _("Length"), _("Signature")]
        rows = []
        for unit in units:
            signed = unit.signature is not None or any(
                c.kind == "signature" for c in unit.children)
            rows.append([ui_text.label(unit.title) + (f" {unit.detail}" if unit.detail else ""),
                         unit.tag, f"0x{unit.offset:08X}", unit.length,
                         _signature_text(unit.signature) if signed else ""])
        total = sum(unit.length for unit in units)
        self._show_table(_("File Structure"), cols, rows,
                         _("{count} units · {length} bytes").format(
                             count=len(units), length=total))

    def _section_overview(self, section):
        """A vehicle-unit section in words: one row per RecordArray.

        *Content* names what the array holds and *Value* says it (the day, the
        odometer, who inserted a card and when, the activity totals...). The
        regulation's name, the record count and size, the offset and length
        are technical columns.
        """
        tech = [_("Record type"), _("Records"), _("Offset"), _("Length")]
        cols = Columns([_("Content"), _("Value")] + tech, technical=tech)
        rows = []
        for array in section.children:
            rows.append([ui_text.label(array.title),
                         array_summary(array, section.signature),
                         array.spec, array.detail,
                         f"0x{array.offset:08X}", array.length])
        return cols, rows

    def _group_overview(self, group, one_driver):
        """A card application in words: one row per elementary file."""
        tech = [_("Tag"), _("Offset"), _("Length")]
        cols = Columns([_("Content"), _("Value"), _("Signature")] + tech, technical=tech)
        rows = []
        for ef in group.children:
            content = ef.content() if ef.decoder is not None else {}
            if len(content) == 1:
                key, value = next(iter(content.items()))
                value_text = group_summary(value, key, one_driver)
            elif content:
                value_text = "  \u00b7  ".join(
                    f"{ui_text.label(content_title(k))}: {group_summary(v, k, one_driver)}"
                    for k, v in content.items())
            else:
                value_text = _("None")
            signed = any(c.kind == "signature" for c in ef.children)
            rows.append([ui_text.label(ef.title), value_text,
                         _signature_text(ef.signature) if signed else _("Not signed"),
                         ef.tag, f"0x{ef.offset:08X}", ef.length])
        return cols, rows
