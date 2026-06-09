from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
import logging

from src.domain.models.entities import TachographFile, Driver, Vehicle, Activity
from src.domain.models.value_objects import ActivityType, NationCode, VIN

logger = logging.getLogger(__name__)

class TachoDomainMapper:
    @staticmethod
    def to_domain(parser_result: Dict[str, Any]) -> TachographFile:
        """
        Maps the raw dictionary output from TachoParser to a TachographFile domain entity.
        """
        metadata = parser_result.get("metadata", {})
        filename = metadata.get("filename", "unknown.ddd")
        parsed_at_str = metadata.get("parsed_at")
        if parsed_at_str:
            try:
                parsed_at = datetime.fromisoformat(parsed_at_str)
            except (ValueError, TypeError):
                parsed_at = datetime.now()
        else:
            parsed_at = datetime.now()

        # Map Driver
        driver_data = parser_result.get("driver", {})
        driver = TachoDomainMapper._map_driver(driver_data)

        # Map Vehicle
        vehicle_data = parser_result.get("vehicle", {})
        vehicle = TachoDomainMapper._map_vehicle(vehicle_data)

        # Map Activities
        activities_data = parser_result.get("activities", [])
        activities = TachoDomainMapper._map_activities(activities_data)

        return TachographFile(
            filename=filename,
            parsed_at=parsed_at,
            driver=driver,
            vehicle=vehicle,
            activities=activities
        )

    @staticmethod
    def _map_driver(data: Dict[str, Any]) -> Optional[Driver]:
        card_number = data.get("card_number") or "N/A"
        if card_number == "N/A":
            return None
        
        surname = data.get("surname") or "N/A"
        firstname = data.get("firstname") or "N/A"
        
        birth_date = TachoDomainMapper._parse_date(data.get("birth_date") or "N/A")
        expiry_date = TachoDomainMapper._parse_date(data.get("expiry_date") or "N/A")
        
        issuing_nation_str = data.get("issuing_nation") or "N/A"
        issuing_nation = None
        if issuing_nation_str and issuing_nation_str != "N/A":
            clean_code = issuing_nation_str.split('(')[0].strip()
            if len(clean_code) <= 3 and clean_code:
                try:
                    issuing_nation = NationCode(clean_code)
                except ValueError:
                    pass

        return Driver(
            card_number=card_number,
            surname=surname,
            firstname=firstname,
            birth_date=birth_date,
            expiry_date=expiry_date,
            issuing_nation=issuing_nation
        )

    @staticmethod
    def _map_vehicle(data: Dict[str, Any]) -> Optional[Vehicle]:
        vin_str = data.get("vin") or "N/A"
        if vin_str == "N/A":
            return None
        
        try:
            vin = VIN(vin_str)
        except Exception:
            vin = VIN(value=vin_str)

        plate = data.get("plate") or "N/A"
        
        reg_nation_str = data.get("registration_nation") or "N/A"
        reg_nation = None
        if reg_nation_str and reg_nation_str != "N/A":
            clean_code = reg_nation_str.split('(')[0].strip()
            if clean_code and len(clean_code) <= 3:
                try:
                    reg_nation = NationCode(clean_code)
                except ValueError:
                    pass

        return Vehicle(
            vin=vin,
            plate=plate,
            registration_nation=reg_nation
        )

    @staticmethod
    def _map_activities(daily_blocks: List[Dict[str, Any]]) -> List[Activity]:
        raw_events = []
        
        for block in daily_blocks:
            date_str = block.get("data", "N/A")
            if date_str == "N/A":
                continue
            
            try:
                base_date = datetime.strptime(date_str, "%d/%m/%Y")
            except ValueError:
                logger.warning(f"Invalid date format: {date_str}")
                continue

            for event in block.get("eventi", []):
                ora_str = event.get("ora", "00:00")
                try:
                    parts = ora_str.split(':')
                    hours = int(parts[0])
                    minutes = int(parts[1])
                    
                    # Calculate total minutes offset
                    offset_minutes = hours * 60 + minutes
                    event_time = base_date + timedelta(minutes=offset_minutes)
                    
                    tipo_str = event.get("tipo", "UNKNOWN")
                    tipo_upper = str(tipo_str).upper()
                    activity_type = ActivityType.UNKNOWN
                    if tipo_upper in ("RIPOSO", "REST"):
                        activity_type = ActivityType.BREAK
                    elif tipo_upper in ("DISPONIBILITÀ", "DISPONIBILITA", "AVAILABILITY", "AVAILABLE"):
                        activity_type = ActivityType.AVAILABILITY
                    elif tipo_upper in ("LAVORO", "WORK"):
                        activity_type = ActivityType.WORK
                    elif tipo_upper in ("GUIDA", "DRIVING", "DRIVE"):
                        activity_type = ActivityType.DRIVING
                    
                    is_manual = event.get("card_present") is False
                    # Actually `is_manual` usually means "Manual Entry". 
                    # The parser has `card_present` and `slot`.
                    # Let's map `is_manual` to checking `card_present` for now, or maybe just default False.
                    # The requirement says "and its components ... Activities".
                    # Let's assume card_present=False implies it *might* be manual or inferred.
                    
                    raw_events.append({
                        "time": event_time,
                        "type": activity_type,
                        "is_manual": is_manual
                    })
                    
                except (ValueError, IndexError):
                    continue

        # Sort by time
        raw_events.sort(key=lambda x: x["time"])

        # Create Activity objects with duration
        activities = []
        for i in range(len(raw_events)):
            current = raw_events[i]
            if i < len(raw_events) - 1:
                next_event = raw_events[i+1]
                duration = (next_event["time"] - current["time"]).total_seconds() / 60
            else:
                duration = 0 # Unknown for last event
            
            # Filter out zero duration events if any (artifacts)
            if duration < 0:
                # This shouldn't happen if sorted, unless duplicate timestamps
                duration = 0 
            
            activities.append(Activity(
                type=current["type"],
                start_time=current["time"],
                duration_minutes=int(duration),
                is_manual=current["is_manual"]
            ))
            
        return activities

    @staticmethod
    def _parse_date(date_str: str) -> Optional[datetime]:
        if not date_str or date_str == "N/A":
            return None
        try:
            return datetime.strptime(date_str, "%d/%m/%Y")
        except ValueError:
            return None
