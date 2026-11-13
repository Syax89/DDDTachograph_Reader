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
from core.structure import build_layout, content_title, hex_rows
from core.utils.activity_stats import compute_activity_totals, recorded_until_seconds

#: Tree rows inserted between two pumps of the event loop.
_PUMP_EVERY = 200


def _size_text(length):
    if length >= 10 * 1024:
        return f"{length / 1024:.1f} kB"
    return f"{length} B"


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


def _records_count(value):
    if isinstance(value, (list, tuple, set)):
        return len(value)
    return 1


def _flat(record):
    """A record with its nested dicts opened one level (``activity`` → its fields)."""
    if not any(isinstance(v, dict) for v in record.values()):
        return record
    out = {}
    for key, value in record.items():
        if isinstance(value, dict):
            for inner, inner_value in value.items():
                name = inner if inner not in record and inner not in out else f"{key}_{inner}"
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
        """Tree text: the name, then what tells two siblings apart.

        A section or EF reads ``Activities 07/07/2025 · TREP 0x32``, an array
        ``VU Activity Daily Record · 90 × 2 B``, a signature or a gap its size.
        Offsets and lengths are in the table header of every unit.
        """
        title = ui_text.label(unit.title)
        if unit.kind == "array":
            return f"{title}  \u00b7  {unit.detail}" if unit.detail else title
        if unit.detail:
            title = f"{title} {unit.detail}"
        if unit.kind == "group":
            return title
        if unit.kind in ("signature", "gap"):
            return f"{title}  \u00b7  {_size_text(unit.length)}"
        # The identifier without its kind ("0x0504", "0x32"): the kind is the
        # level of the tree, and the full tag is in the table header.
        code = unit.tag.rsplit(" ", 1)[-1] if unit.tag else ""
        return f"{title}  \u00b7  {code}" if code else title

    @staticmethod
    def _unit_icon_name(unit):
        if unit.signature is True:
            return "status-ok"
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
                for key, value in groups.items():
                    child = self.tree.insert(
                        iid, tk.END,
                        text=f"{ui_text.label(content_title(key))}  ·  "
                             f"{_records_count(value)}")
                    self._payloads[child] = ("__unit__", unit, key)
        for child in unit.children:
            self._add_unit(iid, child)
        return iid

    def _unit_meta(self, unit):
        parts = [_("Offset {offset} · {length} bytes").format(
            offset=f"0x{unit.offset:08X}", length=unit.length)]
        if unit.tag:
            parts.append(unit.tag)
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
        title = ui_text.label(unit.title) + (f" {unit.detail}" if unit.detail else "")
        meta = self._unit_meta(unit)
        byte_view = self._unit_bytes(unit)
        if key is not None and key in groups:
            title = f"{title} — {ui_text.label(content_title(key))}"
            cols, rows = content_rows(groups[key], key, cuts, one_driver)
        elif len(groups) == 1:
            only = next(iter(groups))
            cols, rows = content_rows(groups[only], only, cuts, one_driver)
        elif groups:
            cols = [_("Content"), _("Records")]
            rows = [[ui_text.label(content_title(k)), _records_count(v)]
                    for k, v in groups.items()]
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
