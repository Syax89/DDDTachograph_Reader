import json


def _get_pandas():
    import pandas as pd
    return pd


def _flatten_dict(d, parent_key="", sep="_"):
    items = {}
    for k, v in d.items():
        new_key = f"{parent_key}{sep}{k}" if parent_key else k
        if isinstance(v, dict):
            items.update(_flatten_dict(v, new_key, sep))
        elif isinstance(v, list):
            items[new_key] = json.dumps(v, default=str)[:2000]
        elif isinstance(v, bytes):
            items[new_key] = v.hex()
        else:
            items[new_key] = v
    return items


def _flatten_records(records):
    if not records:
        return [], []
    flat = []
    all_keys = set()
    for rec in records:
        if isinstance(rec, dict):
            f = _flatten_dict(rec)
            all_keys.update(f.keys())
            flat.append(f)
    cols = sorted(all_keys)
    rows = [{c: d.get(c, "") for c in cols} for d in flat]
    return cols, rows


_EXCEL_MAX_ROWS = 50000


class ExportManager:
    @staticmethod
    def export_to_excel(data, filepath):
        pd = _get_pandas()
        meta = data.get("metadata", {})
        driver = data.get("driver", {})
        vehicle = data.get("vehicle", {})

        with pd.ExcelWriter(filepath, engine="openpyxl") as writer:
            metadata_rows = [
                {"Field": "Filename", "Value": meta.get("filename", "N/A")},
                {"Field": "Generation", "Value": meta.get("generation", "N/A")},
                {"Field": "File Size (bytes)", "Value": meta.get("file_size_bytes", 0)},
                {"Field": "Coverage (%)", "Value": meta.get("coverage_pct", 0)},
                {"Field": "Integrity", "Value": meta.get("integrity_check", "N/A")},
                {"Field": "Parsed At", "Value": meta.get("parsed_at", "")},
                {"Field": "Source", "Value": "Vehicle Unit (VU)" if meta.get("is_vu") else "Driver Card"},
                {"Field": "Decoder Failures", "Value": meta.get("decoder_failure_count", 0)},
            ]
            pd.DataFrame(metadata_rows).to_excel(writer, sheet_name="Summary", index=False)

            driver_rows = [{"Field": k, "Value": v} for k, v in driver.items()]
            pd.DataFrame(driver_rows).to_excel(writer, sheet_name="Driver", index=False)

            vehicle_rows = [{"Field": k, "Value": v} for k, v in vehicle.items()]
            pd.DataFrame(vehicle_rows).to_excel(writer, sheet_name="Vehicle", index=False)

            if data.get("signature_verification"):
                sv = data["signature_verification"]
                treps = sv.get("treps") or []
                sig_rows = [
                    {"Field": "Available", "Value": sv.get("available")},
                    {"Field": "MSCA to VU chain", "Value": sv.get("msca_to_vu")},
                    {"Field": "Root Anchored", "Value": sv.get("root_anchored")},
                    {"Field": "All TREPs valid", "Value": sv.get("all_treps_valid")},
                    {"Field": "Summary", "Value": sv.get("summary", "")},
                    {"Field": "TREPs verified", "Value": len(treps)},
                ]
                pd.DataFrame(sig_rows).to_excel(writer, sheet_name="Signatures", index=False)
                if treps:
                    cols, rows = _flatten_records(treps)
                    if rows:
                        pd.DataFrame(rows, columns=cols).to_excel(
                            writer, sheet_name="TREP Signatures", index=False)

            if data.get("vu_certificates"):
                cols, rows = _flatten_records(data["vu_certificates"])
                if rows:
                    pd.DataFrame(rows, columns=cols).to_excel(
                        writer, sheet_name="VU Certificates", index=False)

            _SECTIONS = [
                ("activities", "Daily Activities"),
                ("events", "Events"),
                ("faults", "Faults"),
                ("places", "Places"),
                ("calibrations", "Calibrations"),
                ("vehicle_sessions", "Vehicle Sessions"),
                ("locations", "GPS Locations"),
                ("gnss_ad_records", "GNSS Accumulated Driving"),
                ("gnss_places", "GNSS Places"),
                ("border_crossings", "Border Crossings"),
                ("load_unload_records", "Load Unload"),
                ("load_sensor_data", "Load Sensor Data"),
                ("trailer_registrations", "Trailer Registrations"),
                ("overspeeding_events", "Overspeeding Events"),
                ("overspeeding_control", "Overspeeding Control"),
                ("power_interruptions", "Power Interruptions"),
                ("company_locks", "Company Locks"),
                ("control_activities", "Control Activities"),
                ("specific_conditions", "Specific Conditions"),
                ("vu_identifications", "VU Identifications"),
                ("sensor_pairings", "Sensor Pairings"),
                ("card_iw_records", "Card Insertion Withdrawal"),
                ("time_adjustments", "Time Adjustments"),
                ("its_consents", "ITS Consents"),
                ("download_activities", "Download Activities"),
                ("card_downloads", "Card Downloads"),
                ("workshops", "Calibration Workshops"),
                ("inserted_drivers", "Inserted Drivers"),
                ("signed_daily_records", "Signed Daily Records"),
            ]

            for key, label in _SECTIONS:
                items = data.get(key) or []
                if not items:
                    continue
                if not isinstance(items, list):
                    items = [items]
                if key == "activities":
                    rows = ExportManager._expand_activities(items)
                    if rows:
                        pd.DataFrame(rows).to_excel(
                            writer, sheet_name=label[:31], index=False)
                else:
                    if len(items) > _EXCEL_MAX_ROWS:
                        import logging
                        logging.getLogger("export").warning(
                            "Truncating '%s' from %d to %d rows (Excel limit)", label, len(items), _EXCEL_MAX_ROWS)
                    cols, rows = _flatten_records(items[: _EXCEL_MAX_ROWS])
                    if rows:
                        pd.DataFrame(rows, columns=cols).to_excel(
                            writer, sheet_name=label[:31], index=False)

    @staticmethod
    def _expand_activities(activities):
        rows = []
        for day in activities:
            if not isinstance(day, dict):
                continue
            date_str = day.get("data", day.get("timestamp", "N/A"))
            km = day.get("km", 0)
            events = day.get("eventi", day.get("changes", []))
            if not isinstance(events, list) or not events:
                rows.append({
                    "Date": date_str, "Time": "", "Activity Type": "",
                    "km": km, "Source": day.get("source", ""),
                })
                continue
            for ev in events:
                if not isinstance(ev, dict):
                    continue
                rows.append({
                    "Date": date_str,
                    "Time": ev.get("ora", ev.get("time", ev.get("minute", ""))),
                    "Activity Type": ev.get("tipo", ev.get("type", ev.get("activity", ""))),
                    "km": km,
                    "Slot": ev.get("slot", ""),
                    "Crew": ev.get("crew", ""),
                    "Source": day.get("source", ev.get("source", "")),
                })
        return rows

    @staticmethod
    def export_to_csv(data, filepath):
        pd = _get_pandas()
        all_rows = []

        activities = data.get("activities", [])
        for row in ExportManager._expand_activities(activities):
            row["Section"] = "Activities"
            all_rows.append(row)

        _EXTRA_SECTIONS = [
            ("events", "Events"),
            ("faults", "Faults"),
            ("places", "Places"),
            ("calibrations", "Calibrations"),
            ("vehicle_sessions", "Vehicle Sessions"),
            ("locations", "GPS Locations"),
            ("gnss_ad_records", "GNSS Accumulated Driving"),
            ("gnss_places", "GNSS Places"),
            ("border_crossings", "Border Crossings"),
            ("overspeeding_events", "Overspeeding Events"),
            ("specific_conditions", "Specific Conditions"),
            ("card_downloads", "Card Downloads"),
        ]
        for key, label in _EXTRA_SECTIONS:
            items = data.get(key) or []
            if not isinstance(items, list):
                items = [items]
            for item in items:
                if isinstance(item, dict):
                    flat = {k: (v.hex() if isinstance(v, bytes) else str(v)) for k, v in item.items()}
                    flat["Section"] = label
                    all_rows.append(flat)

        if not all_rows:
            pd.DataFrame([{"Info": "No data found"}]).to_csv(
                filepath, index=False, sep=";", encoding="utf-8-sig")
            return

        driver = data.get("driver", {})
        vehicle = data.get("vehicle", {})
        driver_name = (
            f"{(driver.get('surname') or '')} {(driver.get('firstname') or '')}".strip()
        )
        card = driver.get("card_number") or "N/A"
        plate = vehicle.get("plate") or "N/A"

        for r in all_rows:
            r.setdefault("Driver", driver_name)
            r.setdefault("Card Number", card)
            r.setdefault("Vehicle Plate", plate)

        pd.DataFrame(all_rows).to_csv(filepath, index=False, sep=";", encoding="utf-8-sig")
