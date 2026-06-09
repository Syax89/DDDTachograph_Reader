from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional
from .value_objects import ActivityType, NationCode, VIN

@dataclass
class Driver:
    card_number: str
    surname: str
    firstname: str
    birth_date: Optional[datetime] = None
    expiry_date: Optional[datetime] = None
    issuing_nation: Optional[NationCode] = None

@dataclass
class Vehicle:
    vin: Optional[VIN] = None
    plate: str = "N/A"
    registration_nation: Optional[NationCode] = None

@dataclass
class Activity:
    type: ActivityType
    start_time: datetime
    duration_minutes: int
    is_manual: bool = False

@dataclass
class TachographFile:
    filename: str
    parsed_at: datetime = field(default_factory=datetime.now)
    driver: Optional[Driver] = None
    vehicle: Optional[Vehicle] = None
    activities: List[Activity] = field(default_factory=list)
    # ... other fields will be added
