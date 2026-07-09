"""Data models for tachograph parsing results. Defines TachoResult and related utilities used throughout the pipeline."""
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from datetime import datetime

def _clean_tag_name(name: str) -> str:
    """Strip generation and protocol prefixes: G22_Foo → Foo, G2_Bar → Bar, VU_Baz → Baz."""
    for prefix in ("G22_", "G2_", "G1_", "VU_", "EF_"):
        if name.startswith(prefix):
            return name[len(prefix):]
    return name

def _tag_generation(name: str) -> str:
    """Classify tag by generation prefix."""
    if name.startswith("G22_"):
        return "Generation 2.2"
    elif name.startswith("G2_"):
        return "Generation 2"
    elif name.startswith("G1_"):
        return "Generation 1"
    # Unprefixed tags: classify by tag ID range
    return "Generation 1"

@dataclass
class TachoResult:
    metadata: Dict[str, Any] = field(default_factory=lambda: {
        "filename": "N/A",
        "generation": "Unknown",
        "parsed_at": datetime.now().isoformat(),
        "integrity_check": "Pending",
        "file_size_bytes": 0,
        "coverage_pct": 0.0
    })
    driver: Dict[str, Any] = field(default_factory=lambda: {
        "card_number": "N/A",
        "surname": "N/A",
        "firstname": "N/A",
        "birth_date": "N/A",
        "expiry_date": "N/A",
        "issuing_nation": "N/A",
        "preferred_language": "N/A",
        "licence_number": "N/A",
        "licence_issuing_nation": "N/A"
    })
    vehicle: Dict[str, Any] = field(default_factory=lambda: {
        "vin": "N/A", 
        "plate": "N/A",
        "registration_nation": "N/A"
    })
    activities: List[Dict[str, Any]] = field(default_factory=list)
    vehicle_sessions: List[Dict[str, Any]] = field(default_factory=list)
    events: List[Dict[str, Any]] = field(default_factory=list)
    faults: List[Dict[str, Any]] = field(default_factory=list)
    locations: List[Dict[str, Any]] = field(default_factory=list)
    places: List[Dict[str, Any]] = field(default_factory=list)
    calibrations: List[Dict[str, Any]] = field(default_factory=list)
    raw_tags: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)
    # Gen 2.2 specific
    gnss_ad_records: List[Dict[str, Any]] = field(default_factory=list)
    load_unload_records: List[Dict[str, Any]] = field(default_factory=list)
    trailer_registrations: List[Dict[str, Any]] = field(default_factory=list)
    gnss_places: List[Dict[str, Any]] = field(default_factory=list)
    load_sensor_data: List[Dict[str, Any]] = field(default_factory=list)
    border_crossings: List[Dict[str, Any]] = field(default_factory=list)
    signed_daily_records: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self, tags: Optional[Dict[int, str]] = None) -> Dict[str, Any]:
        """Convert the result to a dictionary, with optional hierarchical generations tree."""
        result = {
            "metadata": self.metadata,
            "driver": self.driver,
            "vehicle": self.vehicle,
            "activities": self.activities,
            "vehicle_sessions": self.vehicle_sessions,
            "events": self.events,
            "faults": self.faults,
            "locations": self.locations,
            "places": self.places,
            "calibrations": self.calibrations,
            "raw_tags": self.raw_tags,
            "gnss_ad_records": self.gnss_ad_records,
            "load_unload_records": self.load_unload_records,
            "trailer_registrations": self.trailer_registrations,
            "gnss_places": self.gnss_places,
            "load_sensor_data": self.load_sensor_data,
            "border_crossings": self.border_crossings,
            "signed_daily_records": self.signed_daily_records
        }
        if tags:
            result["generations"] = build_generations_tree(result, tags)
        return result


def _tag_name(tag_id: int, tags: Dict[int, str], fallback: str) -> str:
    """Look up a clean display name for *tag_id*, falling back to *fallback*."""
    return _clean_tag_name(tags.get(tag_id, fallback))


def _driver_card_id(driver: Dict[str, Any]) -> Dict[str, Any]:
    """G1 Identification (0x0520) fields from driver dict."""
    return {
        "issuing_nation": driver.get("issuing_nation", "N/A"),
        "card_number": driver.get("card_number", "N/A"),
        "expiry_date": driver.get("expiry_date", "N/A"),
        "surname": driver.get("surname", "N/A"),
        "firstname": driver.get("firstname", "N/A"),
        "birth_date": driver.get("birth_date", "N/A"),
        "preferred_language": driver.get("preferred_language", "N/A"),
    }


def _driver_licence(driver: Dict[str, Any]) -> Dict[str, Any]:
    """G1 DrivingLicenceInfo (0x0521) fields from driver dict."""
    return {
        "licence_number": driver.get("licence_number", "N/A"),
        "licence_issuing_nation": driver.get("licence_issuing_nation", "N/A"),
    }


def _g2_card_id(driver: Dict[str, Any]) -> Dict[str, Any]:
    """G2 CardIdentification (0x0102) fields from driver dict."""
    return {
        "card_number": driver.get("card_number", "N/A"),
        "issuing_nation": driver.get("issuing_nation", "N/A"),
        "expiry_date": driver.get("expiry_date", "N/A"),
    }


def _g2_driver_holder(driver: Dict[str, Any]) -> Dict[str, Any]:
    """G2 DriverCardHolderIdentification (0x0201) fields from driver dict."""
    return {
        "surname": driver.get("surname", "N/A"),
        "firstname": driver.get("firstname", "N/A"),
        "birth_date": driver.get("birth_date", "N/A"),
        "preferred_language": driver.get("preferred_language", "N/A"),
    }


def _vehicle_id(vehicle: Dict[str, Any]) -> Dict[str, Any]:
    """VehicleIdentification (0x0001) fields."""
    return {
        "vin": vehicle.get("vin", "N/A"),
        "plate": vehicle.get("plate", "N/A"),
        "registration_nation": vehicle.get("registration_nation", "N/A"),
    }


def _current_usage(vehicle: Dict[str, Any]) -> list:
    """CurrentUsage (0x0507) as a single-entry list for table rendering."""
    return [{
        "plate": vehicle.get("plate", "N/A"),
        "registration_nation": vehicle.get("registration_nation", "N/A"),
    }]


def _clean_drivers(drivers: list) -> list:
    """Strip internal `_` keys from inserted driver records."""
    return [{k: v for k, v in d.items() if not k.startswith("_")} for d in drivers]


def _non_empty(val) -> bool:
    """True when *val* is a non-empty dict or non-empty list."""
    if isinstance(val, dict):
        return len(val) > 0
    if isinstance(val, (list, tuple, set)):
        return len(val) > 0
    return bool(val)


def _is_valid(vehicle: Dict[str, Any], field: str) -> bool:
    """True when *vehicle*[*field*] is present and not the 'N/A' sentinel."""
    return vehicle.get(field, "N/A") != "N/A"


def _build_gen1(results: Dict[str, Any], driver: Dict[str, Any],
                vehicle: Dict[str, Any], tags: Dict[int, str]) -> Dict[str, Any]:
    """Generation 1 (Annex 1B) — legacy EFs present in all tachograph files."""
    g: Dict[str, Any] = {}

    def _add(tag_id: int, fallback: str, value):
        if _non_empty(value):
            g[_tag_name(tag_id, tags, fallback)] = value

    _add(0x0501, "ApplicationIdentification", results.get("card_application"))
    _add(0x0502, "EventsData",               results.get("events"))
    _add(0x0503, "FaultsData",               results.get("faults"))
    _add(0x0504, "DriverActivityData",       results.get("activities"))
    _add(0x0505, "VehiclesUsed",             results.get("vehicle_sessions"))
    _add(0x0506, "Places",                   results.get("places"))
    _add(0x0508, "ControlActivityData",      results.get("control_activities"))
    _add(0x050C, "CalibrationData",          results.get("calibrations"))
    _add(0x050E, "CardDownload",             results.get("card_downloads"))

    if _is_valid(driver, "card_number"):
        _add(0x0520, "Identification", _driver_card_id(driver))
    if _is_valid(driver, "licence_number"):
        _add(0x0521, "DrivingLicenceInfo", _driver_licence(driver))
    if _is_valid(vehicle, "plate"):
        _add(0x0507, "CurrentUsage", _current_usage(vehicle))
    if _is_valid(vehicle, "vin") or _is_valid(vehicle, "plate"):
        _add(0x0001, "VehicleIdentification", _vehicle_id(vehicle))

    _add(0x0000, "ICC_ChipIdentification", results.get("card_chip"))

    # VU Overview fields
    for src_key, display_name in [
        ("company_info",         "CompanyInfo"),
        ("vu_info",              "VU_TechnicalInfo"),
        ("card_numbers",         "InsertedCardNumbers"),
        ("card_iw_records",      "CardIWRecords"),
        ("company_locks",        "CompanyLocks"),
        ("overspeeding_events",  "OverspeedingEvents"),
        ("overspeeding_control", "OverspeedingControl"),
        ("specific_conditions",  "SpecificConditions"),
        ("time_adjustments",     "TimeAdjustments"),
        ("sensor_daily_records", "SensorDailyRecords"),
        ("sensor_info",          "SensorInfo"),
        ("previous_vehicle",     "PreviousVehicle"),
    ]:
        _add(0x0000, display_name, results.get(src_key))

    # Inserted drivers (strip internal keys)
    inserted = results.get("inserted_drivers")
    if inserted:
        g["InsertedDrivers"] = _clean_drivers(inserted)

    # Calibration workshops
    workshops = results.get("workshops")
    if workshops:
        g["CalibrationWorkshops"] = workshops

    # Calibration VINs (sorted set)
    cal_vins = sorted(results.get("calibration_vins", set()))
    if cal_vins:
        g["CalibrationVINs"] = cal_vins

    # Speed blocks (detailed speed from VU TREP 04 / RecordArray)
    _add(0x0000, "DetailedSpeed", results.get("speed_blocks"))

    # Signed daily records (G1 TREP 02 daily records + signatures)
    _add(0x0000, "SignedDailyRecords", results.get("signed_daily_records"))

    # Card download records from VU side
    card_dls = results.get("card_downloads")
    if card_dls:
        g["CardDownloadRecords"] = card_dls

    # Decoded certificates
    _add(0x0000, "Certificates", results.get("certificates"))

    return g


def _build_gen2(results: Dict[str, Any], driver: Dict[str, Any],
                vehicle: Dict[str, Any], tags: Dict[int, str]) -> Dict[str, Any]:
    """Generation 2 (Annex 1C) — Smart Tacho V1 fields (G2 and G2.2 files)."""
    g: Dict[str, Any] = {}

    def _add(tag_id: int, fallback: str, value):
        if _non_empty(value):
            g[_tag_name(tag_id, tags, fallback)] = value

    # ── G2 card-side EFs ──
    _add(0x0100, "CardIssuerIdentification",       results.get("card_issuer"))
    _add(0x0101, "CardIccIdentification",           results.get("card_icc"))
    _add(0x0201, "DriverCardHolderIdentification",  _g2_driver_holder(driver)
         if _is_valid(driver, "surname") else None)
    _add(0x0102, "CardIdentification",              _g2_card_id(driver)
         if _is_valid(driver, "card_number") else None)
    _add(0x2020, "CompanyHolderData",               results.get("company_holders"))
    _add(0x0523, "VehicleUnitsUsed",                results.get("vehicle_units"))

    # VehiclesUsed duplicate (G2 appendix copy)
    _add(0x0505, "VehiclesUsed", results.get("vehicle_sessions"))

    # ── G2 VU-specific records ──
    for src_key, display_name in [
        ("vu_certificates",             "VU Certificates (CVC)"),
        ("vu_identifications",          "VU Identifications"),
        ("card_records",                "Card Records"),
        ("download_activities",         "Download Activities"),
        ("downloadable_periods",        "Downloadable Periods"),
        ("its_consents",                "ITS Consents"),
        ("power_interruptions",         "Power Interruptions"),
        ("signature_verification",      "ECDSA Signature Verification"),
    ]:
        _add(0x0000, display_name, results.get(src_key))

    # Certificate temporal validity (nested inside signature_verification)
    sv = results.get("signature_verification") or {}
    ctv = sv.get("certificate_temporal_validity")
    if isinstance(ctv, dict) and ctv:
        _STATUS_LABELS = {
            "not_checked": "Not checked",
            "valid": "Valid",
            "expired": "Expired",
            "not_yet_valid": "Not yet valid",
            "unavailable": "Unavailable",
        }
        flat = {}
        for cert_name, cert_info in ctv.items():
            prefix = cert_name.upper()
            for field, value in cert_info.items():
                label = _STATUS_LABELS.get(str(value), str(value)) if field == "status" else str(value)
                flat[f"{prefix} {field}"] = label
        g["Certificate Temporal Validity"] = flat

    # Sensor pairings (two possible keys)
    for key in ("sensor_pairings", "sensor_paired"):
        val = results.get(key)
        if _non_empty(val):
            g["Sensor Pairings"] = val
            break

    # GNSS sensor couplings (two possible keys)
    for key in ("sensor_gnss_couplings", "sensor_gnss_coupled"):
        val = results.get(key)
        if _non_empty(val):
            g["GNSS Sensor Couplings"] = val
            break

    # VU RecordArray structural summary
    _add(0x0000, "VU RecordArray Summary", results.get("vu_record_arrays"))

    # GNSS Accumulated Driving (can come from G2 card EF 0x0524 or G2.2 EF 0x0525)
    _add(0x0525, "GNSSAccumulatedDriving", results.get("gnss_ad_records"))

    # Places duplicated here — G2 extends with GNSS coordinates
    _add(0x0506, "Places", results.get("places"))

    # Events / Faults / Activities — same structure, G2 context
    _add(0x0502, "EventsData",         results.get("events"))
    _add(0x0503, "FaultsData",         results.get("faults"))
    _add(0x0504, "DriverActivityData", results.get("activities"))
    _add(0x050C, "CalibrationData",    results.get("calibrations"))
    _add(0x0508, "ControlActivityData", results.get("control_activities"))

    # Speed blocks (G2 VU RecordArray / TREP 04)
    _add(0x0000, "DetailedSpeed", results.get("speed_blocks"))

    return g


def _build_gen22(results: Dict[str, Any], driver: Dict[str, Any],
                 vehicle: Dict[str, Any], tags: Dict[int, str]) -> Dict[str, Any]:
    """Generation 2.2 (Reg. 2023/980) — Smart Tacho V2 fields only."""
    g: Dict[str, Any] = {}

    def _add(tag_id: int, fallback: str, value):
        if _non_empty(value):
            g[_tag_name(tag_id, tags, fallback)] = value

    _add(0x0525, "GNSSAccumulatedDriving",  results.get("gnss_ad_records"))
    _add(0x0526, "LoadUnloadOperations",    results.get("load_unload_records"))
    _add(0x0527, "TrailerRegistrations",    results.get("trailer_registrations"))
    _add(0x0528, "GNSSEnhancedPlaces",      results.get("gnss_places"))
    _add(0x0529, "LoadSensorData",          results.get("load_sensor_data"))
    _add(0x052A, "BorderCrossings",         results.get("border_crossings"))

    # G2.2-specific additional decoded keys
    for src_key, display_name in [
        ("detailed_speed",        "Detailed Speed (0x052C)"),
        ("gnss_auth",             "GNSS Authentication"),
        ("load_unload_auth",      "Load/Unload Authentication"),
        ("sensor_faults",         "Sensor Faults"),
        ("vu_controller",         "VU Controller"),
        ("signed_daily_records",  "Signed Daily Records"),
    ]:
        _add(0x0000, display_name, results.get(src_key))

    # G2.2 sensor pairings variant
    for key in ("sensor_paired_g22",):
        val = results.get(key)
        if _non_empty(val):
            g["Sensor Pairings (G2.2)"] = val
            break

    # G2.2 GNSS sensor couplings variant
    for key in ("sensor_gnss_coupled_g22",):
        val = results.get(key)
        if _non_empty(val):
            g["GNSS Sensor Couplings (G2.2)"] = val
            break

    return g


def _split_raw_tags(raw_tags: Dict[str, Any],
                    tags: Dict[int, str]) -> Dict[str, Dict[str, Any]]:
    """Partition raw_tags occurrences into per-generation buckets."""
    buckets: Dict[str, Dict[str, Any]] = {
        "Generation 1": {}, "Generation 2": {}, "Generation 2.2": {}}
    for key, occs in raw_tags.items():
        parts = key.split(" > ")
        leaf = parts[-1]
        gen = _tag_generation(leaf)
        clean = _clean_tag_name(leaf)
        buckets[gen].setdefault(clean, []).extend(occs)
    return {k: v for k, v in buckets.items() if v}


def build_generations_tree(results: Dict[str, Any], tags: Dict[int, str]) -> Dict[str, Any]:
    """Build hierarchical view of decoded data grouped by generation.

    Each generation section contains every decoded data key applicable to
    that generation.  Shared legacy keys (activities, events, places …) appear
    in Gen1 and are repeated in Gen2/Gen2.2 where the regulation extends or
    reuses them.
    """
    driver = results.get("driver", {})
    vehicle = results.get("vehicle", {})

    gen1  = _build_gen1(results, driver, vehicle, tags)
    gen2  = _build_gen2(results, driver, vehicle, tags)
    gen22 = _build_gen22(results, driver, vehicle, tags)

    raw_by_gen = _split_raw_tags(results.get("raw_tags", {}), tags)

    tree: Dict[str, Any] = {}
    if gen1:
        tree["Generation 1"] = {**gen1, "_RawTags": raw_by_gen.get("Generation 1", {})}
    if gen2:
        tree["Generation 2"] = {**gen2, "_RawTags": raw_by_gen.get("Generation 2", {})}
    if gen22:
        tree["Generation 2.2"] = {**gen22, "_RawTags": raw_by_gen.get("Generation 2.2", {})}

    # ── Security section (EF data-integrity verification) ──
    efv = results.get("ef_signature_verification")
    if isinstance(efv, dict) and efv:
        tree["Security"] = {"EF Signature Verification": efv}

    return tree
