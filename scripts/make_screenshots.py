"""Drive the GUI and capture screenshots of the new v2.5 views.

Anonymizes real driver/company identities to English test data so the images
are safe to publish. macOS only (uses `screencapture -R`).

Usage: python scripts/make_screenshots.py DRIVER_CARD.ddd VEHICLE_UNIT.ddd
"""
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.engine import TachoParser  # noqa: E402
from app.gui import TachoExplorer  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "docs", "screenshots")
os.makedirs(OUT, exist_ok=True)

FAKE_DRIVERS = [
    ("SMITH", "JOHN"),
    ("BROWN", "MICHAEL"),
    ("TAYLOR", "DAVID"),
]
FAKE_COMPANY = "NORTHBRIDGE HAULAGE LTD"
FAKE_AUTHORITY = "DVLA SWANSEA"


def anonymize(data):
    """Replace real personal identifiers with English test values."""
    idx = {}

    def name_for(key):
        if key not in idx:
            idx[key] = FAKE_DRIVERS[len(idx) % len(FAKE_DRIVERS)]
        return idx[key]

    drv = data.get("driver")
    if isinstance(drv, dict) and drv.get("surname"):
        sur, first = name_for(drv.get("card_number", "d0"))
        drv["surname"], drv["firstname"] = sur, first
        drv["issuing_authority"] = FAKE_AUTHORITY
        if drv.get("licence_number"):
            drv["licence_number"] = "SMITH901234JD9AB"

    for iw in data.get("card_iw") or []:
        if isinstance(iw, dict) and iw.get("holder_surname"):
            sur, first = name_for(iw.get("card_number", iw.get("holder_surname")))
            iw["holder_surname"], iw["holder_first_names"] = sur, first

    for d in data.get("inserted_drivers") or []:
        if isinstance(d, dict) and d.get("surname"):
            sur, first = name_for(d.get("card_number", d.get("surname")))
            d["surname"], d["firstname"] = sur, first

    for lock in data.get("company_locks") or []:
        if isinstance(lock, dict):
            lock["company_name"] = FAKE_COMPANY
            lock["company_address"] = "12 DOCK ROAD, LIVERPOOL"

    vehicle = data.get("vehicle")
    if isinstance(vehicle, dict):
        vehicle["plate"] = "AB24 CDE"
        vehicle["vin"] = "TESTVIN00000000001"
    for session in data.get("vehicle_sessions") or []:
        if isinstance(session, dict):
            session["vehicle_plate"] = "AB24 CDE"
    return data


def add_demo_overspeed_event(data):
    """Add a synthetic marker that aligns with the anonymized speed sample day."""
    data["overspeeding_events"] = [{
        "begin": "2025-07-10T08:40:00+00:00",
        "end": "2025-07-10T08:41:00+00:00",
        "max_speed_kmh": 94,
        "average_speed_kmh": 92,
        "event_type_label": "Over speeding (synthetic demo)",
    }]


def find_node(tree, text, parent=""):
    for child in tree.get_children(parent):
        if tree.item(child, "text").strip() == text:
            return child
        found = find_node(tree, text, child)
        if found:
            return found
    return None


def find_node_contains(tree, needle, parent=""):
    for child in tree.get_children(parent):
        if needle in tree.item(child, "text"):
            return child
        found = find_node_contains(tree, needle, child)
        if found:
            return found
    return None


def first_day_under(tree, section_text):
    node = find_node(tree, section_text)
    if not node:
        return None
    tree.item(node, open=True)
    kids = tree.get_children(node)
    return kids[0] if kids else None


def speed_day_with_events(app):
    """Return the highest-event detailed-speed day for the screenshot."""
    section = find_node(app.tree, "Detailed Speed")
    if not section:
        return None
    candidates = []
    for child in app.tree.get_children(section):
        payload = app._payloads.get(child, ())
        events = payload[3] if len(payload) > 3 else []
        events = events or []
        candidates.append((len(events), child))
    return max(candidates, default=(0, first_day_under(app.tree, "Detailed Speed")))[1]


def capture(app, name):
    app.update_idletasks()
    app.update()
    time.sleep(0.6)
    app.update()
    x = app.winfo_rootx()
    y = app.winfo_rooty()
    w = app.winfo_width()
    h = app.winfo_height()
    path = os.path.join(OUT, name)
    subprocess.run(
        ["screencapture", "-x", "-R", f"{x},{y},{w},{h}", path], check=True)
    print("saved", path)


def select(app, iid):
    if iid and app.tree.exists(iid):
        app.tree.selection_set(iid)
        app.tree.see(iid)
        app.tree.focus(iid)
        app._on_tree_select(None)
        app.update()
        time.sleep(0.4)
        app.update()
    return iid


def load(app, path, display_path, speed_demo=False):
    data = anonymize(TachoParser(path).parse())
    if speed_demo:
        add_demo_overspeed_event(data)
    data["metadata"]["filename"] = os.path.basename(display_path)
    app._parse_done(data, display_path)
    app.update()
    time.sleep(0.8)
    app.update()


def main():
    if len(sys.argv) != 3:
        raise SystemExit(
            "Usage: python scripts/make_screenshots.py DRIVER_CARD.ddd "
            "VEHICLE_UNIT.ddd")
    driver, vu = sys.argv[1:]

    app = TachoExplorer()
    app.geometry("1360x820+40+40")
    app.update()

    # 1+2: driver card — activity dashboard + a day timeline w/ vehicle
    load(app, driver, "samples/DRIVER_SMITH_JOHN_TEST_DATA.ddd")
    select(app, find_node(app.tree, "Daily Activities"))
    capture(app, "01_activity_dashboard.png")

    day = first_day_under(app.tree, "Daily Activities")
    select(app, day)
    capture(app, "02_activity_timeline.png")

    # 3: VU file — speed dashboard + graph
    load(app, vu, "samples/VU_NORTHBRIDGE_TEST_VEHICLE.ddd", speed_demo=True)
    sp = find_node(app.tree, "Detailed Speed")
    if sp:
        select(app, sp)
        capture(app, "03_speed_dashboard.png")
        day = speed_day_with_events(app)
        select(app, day)
        capture(app, "04_speed_graph.png")

    app.destroy()


if __name__ == "__main__":
    main()
