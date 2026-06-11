"""Data models for tachograph parsing results. Defines TachoResult and related utilities used throughout the pipeline."""
from dataclasses import dataclass, field
from typing import List, Dict, Any
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
    signatures: List[Dict[str, Any]] = field(default_factory=list)
    # Gen 2.2 specific
    gnss_ad_records: List[Dict[str, Any]] = field(default_factory=list)
    load_unload_records: List[Dict[str, Any]] = field(default_factory=list)
    trailer_registrations: List[Dict[str, Any]] = field(default_factory=list)
    gnss_places: List[Dict[str, Any]] = field(default_factory=list)
    load_sensor_data: List[Dict[str, Any]] = field(default_factory=list)
    border_crossings: List[Dict[str, Any]] = field(default_factory=list)
    signed_daily_records: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self, tags: Dict[int, str] = None) -> Dict[str, Any]:
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
            "signatures": self.signatures,
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


def build_generations_tree(results: Dict[str, Any], tags: Dict[int, str]) -> Dict[str, Any]:
    """Build hierarchical view of decoded data grouped by generation and clean tag name."""
    gen1 = {}   # Generation 1
    gen2 = {}   # Generation 2
    gen22 = {}  # Generation 2.2

    driver = results.get("driver", {})
    vehicle = results.get("vehicle", {})
    events = results.get("events", [])
    faults = results.get("faults", [])
    activities = results.get("activities", [])
    vehicle_sessions = results.get("vehicle_sessions", [])
    places = results.get("places", [])
    calibrations = results.get("calibrations", [])
    card_icc = results.get("card_icc", {})
    raw_tags = results.get("raw_tags", {})

    # ── Tag 0x0501: DriverCardApplicationIdentification ──
    card_app = results.get("card_application", {})
    if card_app:
        gen1[_clean_tag_name(tags.get(0x0501, "ApplicationIdentification"))] = card_app

    # ── Tag 0x0502: EventsData ──
    if events:
        gen1[_clean_tag_name(tags.get(0x0502, "EventsData"))] = events

    # ── Tag 0x0503: FaultsData ──
    if faults:
        gen1[_clean_tag_name(tags.get(0x0503, "FaultsData"))] = faults

    # ── Tag 0x0504: DriverActivityData ──
    if activities:
        gen1[_clean_tag_name(tags.get(0x0504, "DriverActivityData"))] = activities

    # ── Tag 0x0505: VehiclesUsed (G1) ──
    if vehicle_sessions:
        gen1[_clean_tag_name(tags.get(0x0505, "VehiclesUsed"))] = vehicle_sessions

    # ── Tag 0x0506: Places ──
    if places:
        gen1[_clean_tag_name(tags.get(0x0506, "Places"))] = places

    # ── Tag 0x0507: CurrentUsage ──
    plate = vehicle.get("plate", "N/A")
    if plate != "N/A":
        gen1[_clean_tag_name(tags.get(0x0507, "CurrentUsage"))] = [{
            "plate": plate,
            "registration_nation": vehicle.get("registration_nation", "N/A"),
        }]

    # ── Tag 0x050C: CalibrationData ──
    if calibrations:
        gen1[_clean_tag_name(tags.get(0x050C, "CalibrationData"))] = calibrations

    # ── Tag 0x0520: Identification ──
    card_number = driver.get("card_number", "N/A")
    if card_number != "N/A":
        gen1[_clean_tag_name(tags.get(0x0520, "Identification"))] = {
            "issuing_nation": driver.get("issuing_nation", "N/A"),
            "card_number": card_number,
            "expiry_date": driver.get("expiry_date", "N/A"),
            "surname": driver.get("surname", "N/A"),
            "firstname": driver.get("firstname", "N/A"),
            "birth_date": driver.get("birth_date", "N/A"),
            "preferred_language": driver.get("preferred_language", "N/A"),
        }

    # ── Tag 0x0521: DrivingLicenceInfo ──
    lic_num = driver.get("licence_number", "N/A")
    if lic_num != "N/A":
        gen1[_clean_tag_name(tags.get(0x0521, "DrivingLicenceInfo"))] = {
            "licence_number": lic_num,
            "licence_issuing_nation": driver.get("licence_issuing_nation", "N/A"),
        }

    # ── Tag 0x0002/0x0005: EF_ICC/EF_IC (Card chip) ──
    chip = results.get("card_chip", {})
    if chip:
        gen1["ICC_ChipIdentification"] = chip

    # ── Tag 0x050E: CardDownload ──
    downloads = results.get("card_downloads", [])
    if downloads:
        gen1[_clean_tag_name(tags.get(0x050E, "CardDownload"))] = downloads

    # ── Tag 0x0508: ControlActivityData ──
    controls = results.get("control_activities", [])
    if controls:
        gen1[_clean_tag_name(tags.get(0x0508, "ControlActivityData"))] = controls

    # ── Tag 0x0100: CardIssuerIdentification ──
    issuer = results.get("card_issuer", {})
    if issuer:
        gen2[_clean_tag_name(tags.get(0x0100, "CardIssuerIdentification"))] = issuer

    # ── Tag 0x2020: CompanyHolderData ──
    companies = results.get("company_holders", [])
    if companies:
        gen2[_clean_tag_name(tags.get(0x2020, "CompanyHolderData"))] = companies

    # ── G1 VU Overview: CompanyInfo ──
    company_info = results.get("company_info", {})
    if company_info:
        gen1["CompanyInfo"] = company_info

    # ── G1 VU Overview: CardNumbers ──
    card_numbers = results.get("card_numbers", [])
    if card_numbers:
        gen1["InsertedCardNumbers"] = card_numbers

    # ── VU Download: VU Info (manufacturer) ──
    vu_info = results.get("vu_info", {})
    if vu_info:
        gen1["VU_TechnicalInfo"] = vu_info

    # ── VU Download: Inserted Drivers ──
    drivers = results.get("inserted_drivers", [])
    if drivers:
        gen1["InsertedDrivers"] = [{k: v for k, v in d.items() if not k.startswith("_")} for d in drivers]

    # ── VU Download: Workshops ──
    workshops = results.get("workshops", [])
    if workshops:
        gen1["CalibrationWorkshops"] = workshops

    # ── VU Download: Calibration VINs ──
    cal_vins = sorted(results.get("calibration_vins", set()))
    if cal_vins:
        gen1["CalibrationVINs"] = cal_vins

    # ── VU Download: Speed blocks ──
    speed_blocks = results.get("speed_blocks", [])
    if speed_blocks:
        gen1["DetailedSpeed"] = speed_blocks

    # ── VU Download: Card downloads ──
    card_downloads = results.get("card_downloads", [])
    if card_downloads:
        gen1["CardDownloadRecords"] = card_downloads

    signed_records = results.get("signed_daily_records", [])
    if signed_records:
        gen1["SignedDailyRecords"] = signed_records

    # ── G2 CardIccIdentification (0x0101) ──
    if card_icc:
        gen2[_clean_tag_name(tags.get(0x0101, "CardIccIdentification"))] = card_icc

    # ── G2 CardIdentification (0x0102) ──
    if card_number != "N/A":
        gen2[_clean_tag_name(tags.get(0x0102, "CardIdentification"))] = {
            "card_number": card_number,
            "issuing_nation": driver.get("issuing_nation", "N/A"),
            "expiry_date": driver.get("expiry_date", "N/A"),
        }

    # ── G2 DriverCardHolderIdentification (0x0201) ──
    surname = driver.get("surname", "N/A")
    if surname != "N/A":
        gen2[_clean_tag_name(tags.get(0x0201, "DriverCardHolderIdentification"))] = {
            "surname": surname,
            "firstname": driver.get("firstname", "N/A"),
            "birth_date": driver.get("birth_date", "N/A"),
            "preferred_language": driver.get("preferred_language", "N/A"),
        }

    # ── EF Vehicles_Used, G2 copy (FID 0x0505, Gen2 appendix) ──
    if vehicle_sessions:
        gen2["VehiclesUsed"] = vehicle_sessions

    # ── Tag 0x0523: G2 VehicleUnits_Used ──
    vehicle_units = results.get("vehicle_units", [])
    if vehicle_units:
        gen2[_clean_tag_name(tags.get(0x0523, "VehicleUnitsUsed"))] = vehicle_units

    # ── G2.2 tags ──
    gnss_ad = results.get("gnss_ad_records", [])
    load_unload = results.get("load_unload_records", [])
    trailers = results.get("trailer_registrations", [])
    gnss_places = results.get("gnss_places", [])
    load_sensor = results.get("load_sensor_data", [])
    borders = results.get("border_crossings", [])

    if gnss_ad:
        gen22[_clean_tag_name(tags.get(0x0525, "GNSSAccumulatedDriving"))] = gnss_ad
    if load_unload:
        gen22[_clean_tag_name(tags.get(0x0526, "LoadUnloadOperations"))] = load_unload
    if trailers:
        gen22[_clean_tag_name(tags.get(0x0527, "TrailerRegistrations"))] = trailers
    if gnss_places:
        gen22[_clean_tag_name(tags.get(0x0528, "GNSSEnhancedPlaces"))] = gnss_places
    if load_sensor:
        gen22[_clean_tag_name(tags.get(0x0529, "LoadSensorData"))] = load_sensor
    if borders:
        gen22[_clean_tag_name(tags.get(0x052A, "BorderCrossings"))] = borders

    # ── VU VehicleIdentification (0x0001) ──
    vin = vehicle.get("vin", "N/A")
    if vin != "N/A" or plate != "N/A":
        gen1[_clean_tag_name(tags.get(0x0001, "VehicleIdentification"))] = {
            "vin": vin,
            "plate": plate,
            "registration_nation": vehicle.get("registration_nation", "N/A"),
        }

    # ── Raw tags organized by generation ──
    raw_by_gen = {"Generation 1": {}, "Generation 2": {}, "Generation 2.2": {}}
    for key, occs in raw_tags.items():
        parts = key.split(" > ")
        leaf = parts[-1]
        if "_" in leaf:
            leaf_tag_id = leaf.split("_", 1)[0]
            try:
                tag_id_int = int(leaf_tag_id, 16)
                gen_name = _tag_generation(tags.get(tag_id_int, leaf))
            except ValueError:
                gen_name = "Generation 1"
        else:
            gen_name = "Generation 1"
        clean_name = _clean_tag_name(leaf)
        raw_by_gen[gen_name].setdefault(clean_name, []).extend(occs)

    for gen_key in list(raw_by_gen.keys()):
        if not raw_by_gen[gen_key]:
            del raw_by_gen[gen_key]

    tree = {}
    if gen1:
        tree["Generation 1"] = {**gen1, "_RawTags": raw_by_gen.get("Generation 1", {})}
    if gen2:
        tree["Generation 2"] = {**gen2, "_RawTags": raw_by_gen.get("Generation 2", {})}
    if gen22:
        tree["Generation 2.2"] = {**gen22, "_RawTags": raw_by_gen.get("Generation 2.2", {})}
    return tree
