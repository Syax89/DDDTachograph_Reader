"""GNSS positions exported as GPX / KML (synthetic records, both decoder shapes)."""
import xml.etree.ElementTree as ET

from app.geo_export import collect_positions, export_positions, to_gpx, to_kml

GPX = "{http://www.topografix.com/GPX/1/1}"
KML = "{http://www.opengis.net/kml/2.2}"


def _vu_place(lat, lon, when, fix=True, status="valid", **extra):
    return {"timestamp": when, "odometer_km": 1000,
            "gnss_place": {"timestamp": when,
                           "geo": {"fix": fix, "position_status": status,
                                   "latitude_deg": lat, "longitude_deg": lon}},
            **extra}


RESULT = {
    "metadata": {"filename": "sample & test.ddd"},
    "gnss_ad_records": [
        _vu_place(45.5, 9.2, "2025-01-01T12:00:00+00:00"),
        _vu_place(45.0, 9.0, "2025-01-01T09:00:00+00:00"),
        _vu_place(10.0, 10.0, "2025-01-01T15:00:00+00:00", fix=False),
        _vu_place(10.0, 10.0, "2025-01-01T16:00:00+00:00", status="invalid"),
    ],
    "places": [
        # card shape: flat coordinates
        {"timestamp": "2025-01-01T08:00:00+00:00", "entry_type": "BEGIN",
         "entry_type_description": "Begin (card insertion time)",
         "latitude": 45.1, "longitude": 9.1, "odometer_km": 990},
        {"timestamp": "2025-01-01T08:00:00+00:00", "entry_type": "BEGIN",
         "latitude": 45.1, "longitude": 9.1},                     # duplicate
        {"timestamp": "2025-01-01T18:00:00+00:00", "latitude": 0.0, "longitude": 0.0},
        {"timestamp": "2025-01-01T19:00:00+00:00", "latitude": 95.0, "longitude": 9.0},
    ],
    "border_crossings": [
        _vu_place(46.0, 6.0, "2025-01-01T13:00:00+00:00",
                  country_left="I", country_entered="F"),
    ],
}


def test_collect_keeps_only_usable_fixes_and_sorts():
    points = collect_positions(RESULT)
    assert [p["kind"] for p in points] == ["track", "track", "place", "border"]
    assert [p["time"][11:16] for p in points[:2]] == ["09:00", "12:00"]
    assert "I → F" in points[-1]["description"]
    assert "Begin (card insertion time)" in points[2]["description"]


def test_gpx_is_well_formed_with_track_and_waypoints():
    root = ET.fromstring(to_gpx(collect_positions(RESULT), "sample & test.ddd"))
    assert len(root.findall(f"{GPX}wpt")) == 2
    trkpts = root.findall(f"{GPX}trk/{GPX}trkseg/{GPX}trkpt")
    assert [(t.get("lat"), t.get("lon")) for t in trkpts] == [
        ("45.000000", "9.000000"), ("45.500000", "9.200000")]
    assert trkpts[0].find(f"{GPX}time").text == "2025-01-01T09:00:00Z"
    assert root.find(f"{GPX}metadata/{GPX}name").text == "sample & test.ddd"


def test_kml_uses_lon_lat_order():
    root = ET.fromstring(to_kml(collect_positions(RESULT)))
    marks = root.findall(f"{KML}Document/{KML}Placemark")
    assert len(marks) == 3            # two waypoints + the route line
    point = marks[0].find(f"{KML}Point/{KML}coordinates").text
    assert point == "9.100000,45.100000"
    line = marks[-1].find(f"{KML}LineString/{KML}coordinates").text
    assert line == "9.000000,45.000000 9.200000,45.500000"


def test_no_positions_gives_an_empty_valid_document(tmp_path):
    path = tmp_path / "out.gpx"
    assert export_positions({"metadata": {}}, str(path)) == 0
    ET.parse(path)


def test_export_follows_the_extension(tmp_path):
    path = tmp_path / "out.kml"
    assert export_positions(RESULT, str(path)) == 4
    assert ET.parse(path).getroot().tag == f"{KML}kml"


def test_personal_identifiers_are_not_written():
    result = {"places": [{"timestamp": "2025-01-01T08:00:00+00:00",
                          "latitude": 45.0, "longitude": 9.0,
                          "card_driver": {"card_number": "X123456789"}}]}
    assert "X123456789" not in to_gpx(collect_positions(result))
