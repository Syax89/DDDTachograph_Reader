"""Validity and duplicate gates for records recovered by a scoped byte scan.

The scoped scan is a LAST resort: it runs on the bytes of a unit that the
normative decoder could not read, and it looks for message boundaries by
pattern. Two classes of false positive follow from that, both measured on real
downloads:

* a ``0x76 <TREP>`` byte pair inside the payload of another message is taken as
  a boundary and decoded as a message of its own (a phantom day of activities
  with no changes, inside a sensor payload);
* a scan that starts a few bytes off re-reads the message the normative pass
  already published, with the same identity but garbled details (the same
  driver published twice, the second time with a shifted card number).

So a candidate is published only when it passes the same field validity the
normative handler applies — something actually decoded — and when it is not a
near-duplicate of a record already published. Nothing here inspects or rewrites
normative records: the gate only decides what the scan may add.
"""

from typing import Any, Dict, List, Mapping, Sequence, Tuple

#: Fields that identify a record for the duplicate gate, per result list. A
#: candidate whose identity tuple equals an already published record's is the
#: same physical record read twice (or read worse), so it is dropped.
IDENTITY_FIELDS: Mapping[str, Tuple[str, ...]] = {
    "activities": ("date",),
    "inserted_drivers": ("surname", "firstname"),
    "places": ("timestamp_raw", "type_code"),
    "card_iw_records": ("insertion_time_raw", "holder_surname"),
    "specific_conditions": ("timestamp_raw", "type_code"),
    "events": ("begin_time_raw", "type_code"),
    "faults": ("begin_time_raw", "type_code"),
    "overspeeding_events": ("begin_time_raw",),
    "overspeeding_control": ("last_control_time_raw",),
    "calibrations": ("old_time_raw", "new_time_raw"),
    "time_adjustments": ("old_time_raw", "new_time_raw"),
    "vu_record_arrays": ("trep", "offset"),
}


def _identity(record: Any, fields: Sequence[str]) -> Tuple:
    if not isinstance(record, dict):
        return ()
    return tuple(record.get(field) for field in fields)


def _is_empty_driver(record: Mapping[str, Any]) -> bool:
    """A driver entry with no name decoded carries nothing (garbled re-read)."""
    if not isinstance(record, dict):
        return False
    if "card_number" not in record and "surname" not in record:
        return False
    return not (str(record.get("surname") or "").strip()
                or str(record.get("first_names") or "").strip()
                or str(record.get("firstname") or "").strip())


def _is_empty_day(record: Mapping[str, Any]) -> bool:
    """A day of activities with no decoded element carries nothing."""
    if not isinstance(record, dict):
        return False
    if "date" not in record:
        return False
    changes = record.get("changes") or []
    return (not changes and not record.get("inserted_drivers")
            and not record.get("invalid_changes_count"))


def prune_candidates(before: Mapping[str, int], results: Dict[str, Any],
                     added_drivers: Sequence[Any] = ()) -> List[str]:
    """Drop the records a scoped scan added that fail the re-read/validity gate.

    ``before`` maps each result list to its length before the scan, so only the
    records the scan appended are examined. Returns the list of dropped keys
    (``section:index``) for the log — never the records themselves.
    """
    dropped: List[str] = []
    seen: Dict[str, set] = {}
    for section, fields in IDENTITY_FIELDS.items():
        records = results.get(section)
        if not isinstance(records, list):
            continue
        kept = records[:before.get(section, 0)]
        identities = {_identity(record, fields) for record in kept}
        seen[section] = identities
    for section, fields in IDENTITY_FIELDS.items():
        records = results.get(section)
        if not isinstance(records, list) or len(records) <= before.get(section, 0):
            continue
        keep = records[:before.get(section, 0)]
        identities = seen[section]
        for index, record in enumerate(records[before.get(section, 0):]):
            identity = _identity(record, fields)
            empty = (_is_empty_day(record) if section == "activities"
                     else _is_empty_driver(record) if section == "inserted_drivers"
                     else False)
            if empty or (identity and identity in identities):
                dropped.append(f"{section}:{index}")
                continue
            identities.add(identity)
            keep.append(record)
        results[section] = keep
    # A day the scan added and the gate rejected takes its drivers with it: the
    # scan builds them from the same message, so a garble that invalidated the
    # day invalidates the drivers it carried (a re-read of a published message
    # otherwise shows up as a second driver with a shifted card number).
    dropped_days = any(item.startswith("activities:") for item in dropped)
    # A driver entry the scan added must not repeat a known driver either (the
    # scan adds them from the same IW records the day carries).
    drivers = results.get("inserted_drivers")
    if isinstance(drivers, list) and len(drivers) > before.get("inserted_drivers", 0):
        base = drivers[:before.get("inserted_drivers", 0)]
        known = {(d.get("surname"), d.get("firstname")) for d in base
                 if isinstance(d, dict)}
        keep = list(base)
        if dropped_days:
            results["inserted_drivers"] = keep
            return dropped
        for driver in drivers[before.get("inserted_drivers", 0):]:
            identity = _identity(driver, IDENTITY_FIELDS["inserted_drivers"])
            if (_is_empty_driver(driver) or identity == (None, None)
                    or identity in known):
                dropped.append("inserted_drivers:driver")
                continue
            if identity not in known:
                known.add(identity)
                keep.append(driver)
        results["inserted_drivers"] = keep
    return dropped
