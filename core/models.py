from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from datetime import datetime

@dataclass
class DriverInfo:
    card_number: str = "N/A"
    surname: str = "N/A"
    firstname: str = "N/A"
    birth_date: str = "N/A"
    expiry_date: str = "N/A"
    issuing_nation: str = "N/A"
    preferred_language: str = "N/A"
    licence_number: str = "N/A"
    licence_issuing_nation: str = "N/A"

@dataclass
class VehicleInfo:
    vin: str = "N/A"
    plate: str = "N/A"
    registration_nation: str = "N/A"

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

    def to_dict(self) -> Dict[str, Any]:
        """Convert the result to a dictionary compatible with the original parser."""
        return {
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
            "signatures": self.signatures
        }
