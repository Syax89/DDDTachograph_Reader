"""GNSS positions of a parsed download, exported as GPX or KML.

G2/G2.2 tachographs record positions in four places:

* ``gnss_ad_records`` — the position every 3 h of accumulated driving
  (VuGNSSADRecord / GNSSAccumulatedDriving): the route, drawn as a track;
* ``places`` — begin/end of each daily work period;
* ``border_crossings`` — the country left and entered (G2.2);
* ``load_unload_records`` — load/unload operations (G2.2).

The last three are waypoints. The decoders give a position in two shapes: a
vehicle-unit record nests it as ``gnss_place.geo.latitude_deg`` (with a
``fix``/``position_status``), a driver-card record carries flat ``latitude``/
``longitude``. A position without a fix, with an invalid status or outside the
WGS-84 range is left out rather than drawn at (0, 0). G1 files record no
positions, so their export is an empty (valid) document.

The output carries no personal data beyond what the positions themselves are:
no driver name or card number is written, only the record kind, time,
odometer and, for a border crossing, the two country codes.
"""

from __future__ import annotations

from typing import Any, Iterable
from xml.sax.saxutils import escape

#: (results key, point kind) in drawing order; ``track`` points form the route.
SOURCES = (
    ("gnss_ad_records", "track"),
    ("places", "place"),
    ("border_crossings", "border"),
    ("load_unload_records", "load_unload"),
)

_KIND_LABELS = {
    "track": "Accumulated driving position",
    "place": "Daily work period",
    "border": "Border crossing",
    "load_unload": "Load/unload",
}


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _coordinates(record: dict) -> tuple[float, float, str] | None:
    """``(lat, lon, timestamp)`` of a record, or ``None`` when it has no usable fix."""
    place = record.get("gnss_place")
    if isinstance(place, dict):
        raw_geo = place.get("geo")
        geo: dict = raw_geo if isinstance(raw_geo, dict) else {}
        if geo.get("fix") is False:
            return None
        status = geo.get("position_status")
        if status is not None and status != "valid":
            return None
        lat, lon = _number(geo.get("latitude_deg")), _number(geo.get("longitude_deg"))
        when = place.get("timestamp") or record.get("timestamp") or ""
    else:
        lat, lon = _number(record.get("latitude")), _number(record.get("longitude"))
        when = record.get("timestamp") or ""
    if lat is None or lon is None:
        return None
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        return None
    if lat == 0.0 and lon == 0.0:
        return None
    return lat, lon, str(when)


def _describe(kind: str, record: dict) -> str:
    parts = [_KIND_LABELS[kind]]
    if kind == "place" and record.get("entry_type"):
        parts.append(str(record.get("entry_type_description") or record["entry_type"]))
    if kind == "border":
        left, entered = record.get("country_left"), record.get("country_entered")
        if left or entered:
            parts.append(f"{left or '?'} → {entered or '?'}")
    if kind == "load_unload":
        op = record.get("operation_type_label") or record.get("operation_type")
        if op not in (None, ""):
            parts.append(str(op))
    odometer = record.get("odometer_km")
    if isinstance(odometer, (int, float)) and not isinstance(odometer, bool):
        parts.append(f"{int(odometer)} km")
    return " · ".join(parts)


def collect_positions(result: dict) -> list[dict]:
    """Every usable position in ``result``, sorted by time within each kind.

    Each point: ``{"kind", "lat", "lon", "time", "description"}``. Duplicates
    (same kind, time and coordinates — the card and VU copies of one record in a
    merged download) are kept once.
    """
    points: list[dict] = []
    seen = set()
    for key, kind in SOURCES:
        records = result.get(key) or []
        if not isinstance(records, list):
            continue
        for record in records:
            if not isinstance(record, dict):
                continue
            coords = _coordinates(record)
            if coords is None:
                continue
            lat, lon, when = coords
            identity = (kind, when, round(lat, 6), round(lon, 6))
            if identity in seen:
                continue
            seen.add(identity)
            points.append({"kind": kind, "lat": lat, "lon": lon, "time": when,
                           "description": _describe(kind, record)})
    order = {kind: index for index, (_key, kind) in enumerate(SOURCES)}
    points.sort(key=lambda p: (order[p["kind"]], p["time"]))
    return points


def _gpx_time(value: str) -> str:
    # GPX wants xsd:dateTime; the decoders emit ISO 8601 with "+00:00".
    return value.replace("+00:00", "Z") if value else ""


def to_gpx(points: Iterable[dict], name: str = "Tachograph positions") -> str:
    """A GPX 1.1 document: waypoints for places/borders/loads, a track for the route."""
    points = list(points)
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<gpx version="1.1" creator="TachoReader" '
           'xmlns="http://www.topografix.com/GPX/1/1">',
           f"  <metadata><name>{escape(name)}</name></metadata>"]
    for p in points:
        if p["kind"] == "track":
            continue
        out.append(f'  <wpt lat="{p["lat"]:.6f}" lon="{p["lon"]:.6f}">')
        if p["time"]:
            out.append(f"    <time>{escape(_gpx_time(p['time']))}</time>")
        out.append(f"    <name>{escape(p['description'])}</name>")
        out.append(f"    <type>{escape(p['kind'])}</type>")
        out.append("  </wpt>")
    track = [p for p in points if p["kind"] == "track"]
    if track:
        out.append(f"  <trk><name>{escape(_KIND_LABELS['track'])}</name><trkseg>")
        for p in track:
            time = f"<time>{escape(_gpx_time(p['time']))}</time>" if p["time"] else ""
            out.append(f'    <trkpt lat="{p["lat"]:.6f}" lon="{p["lon"]:.6f}">{time}</trkpt>')
        out.append("  </trkseg></trk>")
    out.append("</gpx>")
    return "\n".join(out) + "\n"


def to_kml(points: Iterable[dict], name: str = "Tachograph positions") -> str:
    """A KML 2.2 document: one placemark per waypoint, a line for the route."""
    points = list(points)
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<kml xmlns="http://www.opengis.net/kml/2.2"><Document>',
           f"  <name>{escape(name)}</name>"]
    for p in points:
        if p["kind"] == "track":
            continue
        out.append("  <Placemark>")
        out.append(f"    <name>{escape(p['description'])}</name>")
        if p["time"]:
            out.append(f"    <TimeStamp><when>{escape(_gpx_time(p['time']))}</when></TimeStamp>")
        out.append(f"    <Point><coordinates>{p['lon']:.6f},{p['lat']:.6f}</coordinates></Point>")
        out.append("  </Placemark>")
    track = [p for p in points if p["kind"] == "track"]
    if track:
        coords = " ".join(f"{p['lon']:.6f},{p['lat']:.6f}" for p in track)
        out.append("  <Placemark>")
        out.append(f"    <name>{escape(_KIND_LABELS['track'])}</name>")
        out.append(f"    <LineString><coordinates>{coords}</coordinates></LineString>")
        out.append("  </Placemark>")
    out.append("</Document></kml>")
    return "\n".join(out) + "\n"


def export_positions(result: dict, path: str, fmt: str | None = None) -> int:
    """Write ``result``'s positions to ``path`` as GPX or KML; return the point count.

    ``fmt`` is ``"gpx"`` or ``"kml"``; when omitted it follows the extension.
    """
    fmt = (fmt or path.rsplit(".", 1)[-1]).lower()
    if fmt not in ("gpx", "kml"):
        raise ValueError(f"unsupported position format: {fmt}")
    points = collect_positions(result)
    name = str((result.get("metadata") or {}).get("filename") or "Tachograph positions")
    text = to_gpx(points, name) if fmt == "gpx" else to_kml(points, name)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)
    return len(points)
