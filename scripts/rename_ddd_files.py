"""Safely rename DDD files from parsed identity and integrity metadata.

Run without arguments to preview. Pass ``--apply`` to rename files in place.
"""
import argparse
import hashlib
import logging
import re
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.engine import TachoParser


def _component(value: object, fallback: str) -> str:
    if str(value or "").strip().upper() in {"", "N/A", "UNKNOWN", "NONE"}:
        return fallback
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = text.encode("ascii", "ignore").decode("ascii").upper()
    text = re.sub(r"[^A-Z0-9]+", "_", text).strip("_")
    return text[:48] or fallback


def _integrity_status(result: dict) -> str:
    metadata = result.get("metadata") or {}
    integrity = str(metadata.get("integrity_check") or "")
    if metadata.get("parse_error") or integrity.startswith("Error") or integrity.startswith("Invalid"):
        return "CORRUPT"
    if float(metadata.get("coverage_pct") or 0) < 100:
        return "PARTIAL"
    if integrity.startswith("Verified"):
        return "VERIFIED"
    return "UNVERIFIED"


def _target_name(source: Path, result: dict) -> str:
    metadata = result.get("metadata") or {}
    status = _integrity_status(result)
    file_id = hashlib.sha256(source.read_bytes()).hexdigest()[:10].upper()
    if metadata.get("is_vu"):
        vehicle = result.get("vehicle") or {}
        return "_".join((
            "VU",
            _component(vehicle.get("plate"), "NO_PLATE"),
            _component(vehicle.get("vin"), "NO_VIN"),
            status,
            file_id,
        )) + source.suffix.lower()

    driver = result.get("driver") or {}
    return "_".join((
        "DRIVER",
        _component(driver.get("surname"), "NO_SURNAME"),
        _component(driver.get("firstname"), "NO_FIRSTNAME"),
        _component(driver.get("card_number"), "NO_CARD"),
        status,
        file_id,
    )) + source.suffix.lower()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", nargs="?", default="DDD", type=Path)
    parser.add_argument("--apply", action="store_true", help="Rename files after validation")
    args = parser.parse_args()
    logging.disable(logging.INFO)

    files = sorted(path for path in args.directory.iterdir()
                   if path.is_file() and path.suffix.lower() == ".ddd")
    plan = []
    for source in files:
        result = TachoParser(str(source)).parse()
        plan.append((source, source.with_name(_target_name(source, result)), _integrity_status(result)))

    targets = [target for _source, target, _status in plan]
    if len(targets) != len(set(targets)):
        raise SystemExit("Aborted: duplicate target filenames in rename plan")
    conflicts = [target for source, target, _status in plan if target != source and target.exists()]
    if conflicts:
        raise SystemExit(f"Aborted: {len(conflicts)} target filename(s) already exist")

    for source, target, status in plan:
        print(f"{status:10} {source.name} -> {target.name}")
    if args.apply:
        for source, target, _status in plan:
            if source != target:
                source.rename(target)


if __name__ == "__main__":
    main()
