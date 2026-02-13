from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional

class ActivityType(Enum):
    BREAK = "BREAK"
    AVAILABILITY = "AVAILABILITY"
    WORK = "WORK"
    DRIVING = "DRIVING"
    UNKNOWN = "UNKNOWN"

@dataclass(frozen=True)
class NationCode:
    code: str
    
    def __post_init__(self):
        if not self.code or len(self.code) > 3:
            raise ValueError(f"Invalid Nation Code: {self.code}")

@dataclass(frozen=True)
class VIN:
    value: str
    
    def __post_init__(self):
        if len(self.value) != 17:
            # We might want to be less strict during initial parsing but warn
            pass

@dataclass(frozen=True)
class GeoCoordinate:
    latitude: float
    longitude: float
    
    def __post_init__(self):
        if not (-90 <= self.latitude <= 90):
            raise ValueError(f"Invalid latitude: {self.latitude}")
        if not (-180 <= self.longitude <= 180):
            raise ValueError(f"Invalid longitude: {self.longitude}")
