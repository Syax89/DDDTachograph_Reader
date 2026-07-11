"""Data models for tachograph parsing results. Defines TachoResult and related utilities used throughout the pipeline."""
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Set
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


def _occurrence_generation(generation: Any) -> Optional[str]:
    """Map parser and display generation labels to generation-tree keys."""
    if not isinstance(generation, str):
        return None
    labels = {
        "g1": "Generation 1",
        "g1 (digital)": "Generation 1",
        "generation 1": "Generation 1",
        "g2": "Generation 2",
        "g2 (smart)": "Generation 2",
        "generation 2": "Generation 2",
        "g2.2": "Generation 2.2",
        "g2.2 (smart v2)": "Generation 2.2",
        "generation 2.2": "Generation 2.2",
    }
    return labels.get(" ".join(generation.casefold().split()))


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
    # Card and VU sections shared by decoders, reports, and the GUI.
    card_application: Dict[str, Any] = field(default_factory=dict)
    control_activities: List[Dict[str, Any]] = field(default_factory=list)
    card_downloads: List[Dict[str, Any]] = field(default_factory=list)
    card_chip: Dict[str, Any] = field(default_factory=dict)
    company_info: Dict[str, Any] = field(default_factory=dict)
    vu_overview: Dict[str, Any] = field(default_factory=dict)
    vu_info: Dict[str, Any] = field(default_factory=dict)
    card_numbers: List[str] = field(default_factory=list)
    card_iw_records: List[Dict[str, Any]] = field(default_factory=list)
    company_locks: List[Dict[str, Any]] = field(default_factory=list)
    overspeeding_events: List[Dict[str, Any]] = field(default_factory=list)
    overspeeding_control: List[Dict[str, Any]] = field(default_factory=list)
    specific_conditions: List[Dict[str, Any]] = field(default_factory=list)
    time_adjustments: List[Dict[str, Any]] = field(default_factory=list)
    sensor_daily_records: List[Dict[str, Any]] = field(default_factory=list)
    sensor_info: Dict[str, Any] = field(default_factory=dict)
    previous_vehicle: Dict[str, Any] = field(default_factory=dict)
    inserted_drivers: List[Dict[str, Any]] = field(default_factory=list)
    workshops: List[str] = field(default_factory=list)
    calibration_vins: Set[str] = field(default_factory=set)
    speed_blocks: List[Dict[str, Any]] = field(default_factory=list)
    certificates: List[Dict[str, Any]] = field(default_factory=list)
    card_issuer: Dict[str, Any] = field(default_factory=dict)
    card_icc: Dict[str, Any] = field(default_factory=dict)
    company_holders: List[Dict[str, Any]] = field(default_factory=list)
    vehicle_units: List[Dict[str, Any]] = field(default_factory=list)
    vu_certificates: List[Dict[str, Any]] = field(default_factory=list)
    vu_identifications: List[Dict[str, Any]] = field(default_factory=list)
    card_records: List[Dict[str, Any]] = field(default_factory=list)
    download_activities: List[Dict[str, Any]] = field(default_factory=list)
    downloadable_periods: List[Dict[str, Any]] = field(default_factory=list)
    its_consents: List[Dict[str, Any]] = field(default_factory=list)
    power_interruptions: List[Dict[str, Any]] = field(default_factory=list)
    signature_verification: Dict[str, Any] = field(default_factory=dict)
    sensor_pairings: List[Dict[str, Any]] = field(default_factory=list)
    sensor_gnss_couplings: List[Dict[str, Any]] = field(default_factory=list)
    vu_record_arrays: List[Dict[str, Any]] = field(default_factory=list)
    gnss_auth: List[Dict[str, Any]] = field(default_factory=list)
    load_unload_auth: List[Dict[str, Any]] = field(default_factory=list)
    sensor_faults: List[Dict[str, Any]] = field(default_factory=list)
    vu_controller: List[Dict[str, Any]] = field(default_factory=list)
    time_adj_gnss: List[Dict[str, Any]] = field(default_factory=list)
    certificate_temporal_validity: Dict[str, Any] = field(default_factory=dict)
    ef_signature_verification: Dict[str, Any] = field(default_factory=dict)
    coverage: Dict[str, Any] = field(default_factory=dict)
    sections: Dict[str, Any] = field(default_factory=dict)
    generations: Dict[str, Any] = field(default_factory=dict)

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
            "signed_daily_records": self.signed_daily_records,
            "card_application": self.card_application,
            "control_activities": self.control_activities,
            "card_downloads": self.card_downloads,
            "card_chip": self.card_chip,
            "company_info": self.company_info,
            "vu_overview": self.vu_overview,
            "vu_info": self.vu_info,
            "card_numbers": self.card_numbers,
            "card_iw_records": self.card_iw_records,
            "company_locks": self.company_locks,
            "overspeeding_events": self.overspeeding_events,
            "overspeeding_control": self.overspeeding_control,
            "specific_conditions": self.specific_conditions,
            "time_adjustments": self.time_adjustments,
            "sensor_daily_records": self.sensor_daily_records,
            "sensor_info": self.sensor_info,
            "previous_vehicle": self.previous_vehicle,
            "inserted_drivers": self.inserted_drivers,
            "workshops": self.workshops,
            "calibration_vins": self.calibration_vins,
            "speed_blocks": self.speed_blocks,
            "certificates": self.certificates,
            "card_issuer": self.card_issuer,
            "card_icc": self.card_icc,
            "company_holders": self.company_holders,
            "vehicle_units": self.vehicle_units,
            "vu_certificates": self.vu_certificates,
            "vu_identifications": self.vu_identifications,
            "card_records": self.card_records,
            "download_activities": self.download_activities,
            "downloadable_periods": self.downloadable_periods,
            "its_consents": self.its_consents,
            "power_interruptions": self.power_interruptions,
            "signature_verification": self.signature_verification,
            "sensor_pairings": self.sensor_pairings,
            "sensor_gnss_couplings": self.sensor_gnss_couplings,
            "vu_record_arrays": self.vu_record_arrays,
            "gnss_auth": self.gnss_auth,
            "load_unload_auth": self.load_unload_auth,
            "sensor_faults": self.sensor_faults,
            "vu_controller": self.vu_controller,
            "time_adj_gnss": self.time_adj_gnss,
            "certificate_temporal_validity": self.certificate_temporal_validity,
            "ef_signature_verification": self.ef_signature_verification,
            "coverage": self.coverage,
            "sections": self.sections,
            "generations": self.generations,
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

    _add(0x0000, "Sensor Pairings", results.get("sensor_pairings"))
    _add(0x0000, "GNSS Sensor Couplings", results.get("sensor_gnss_couplings"))

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
        ("speed_blocks",          "Detailed Speed (0x052C)"),
        ("gnss_auth",             "GNSS Authentication"),
        ("load_unload_auth",      "Load/Unload Authentication"),
        ("sensor_faults",         "Sensor Faults"),
        ("vu_controller",         "VU Controller"),
        ("signed_daily_records",  "Signed Daily Records"),
    ]:
        _add(0x0000, display_name, results.get(src_key))

    _add(0x0000, "Sensor Pairings (G2.2)", results.get("sensor_pairings"))
    _add(0x0000, "GNSS Sensor Couplings (G2.2)", results.get("sensor_gnss_couplings"))

    return g


def _split_raw_tags(raw_tags: Dict[str, Any],
                    tags: Dict[int, str]) -> Dict[str, Dict[str, Any]]:
    """Partition raw tag occurrences by explicit generation or legacy prefix."""
    buckets: Dict[str, Dict[str, Any]] = {
        "Generation 1": {}, "Generation 2": {}, "Generation 2.2": {}}
    for key, occs in raw_tags.items():
        parts = key.split(" > ")
        leaf = parts[-1]
        fallback_gen = _tag_generation(leaf)
        clean = _clean_tag_name(leaf)
        for occurrence in occs:
            generation = (_occurrence_generation(occurrence.get("generation"))
                          if isinstance(occurrence, dict) else None)
            gen = generation or fallback_gen
            buckets[gen].setdefault(clean, []).append(occurrence)
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
