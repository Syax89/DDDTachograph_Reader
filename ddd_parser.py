import struct
import os
import json
import mmap
from datetime import datetime

try:
    from geocoding_engine import process_locations_with_geocoding
    GEOCODING_AVAILABLE = True
except ImportError:
    GEOCODING_AVAILABLE = False

from signature_validator import SignatureValidator
from core.models import TachoResult
from core.tag_navigator import TagNavigator

class TachoParser:
    """
    Professional analysis engine for Tachograph files (.DDD).
    Version 5.1 - Refactored Edition
    """
    
    def __init__(self, file_path):
        self.file_path = file_path
        self.file_size = os.path.getsize(file_path) if os.path.exists(file_path) else 0
        self.raw_data = None
        self._fd = None
        self.validator = SignatureValidator()
        self.bytes_covered = 0
        self.card_public_key = None
        self.msca_cert_raw = None
        self.card_cert_raw = None
        self.validation_status = "Pending"
        
        # Initialize results using the model but keep it as a dict for legacy compatibility
        self.results = TachoResult().to_dict()
        self.results["metadata"]["filename"] = os.path.basename(file_path)
        self.results["metadata"]["file_size_bytes"] = self.file_size
        
        self.TAGS = self._load_tags()
        self.navigator = TagNavigator(self)

    def _load_tags(self):
        """Load tags from internal defaults and optional JSON file."""
        tags = {
            0x0001: "VU_VehicleIdentification", 0x0002: "EF_ICC", 0x0005: "EF_IC",
            0x0101: "G2_CardIccIdentification", 0x0102: "G2_CardIdentification",
            0x0103: "G2_CardCertificate", 0x0104: "G2_MemberStateCertificate",
            0x0201: "G2_DriverCardHolderIdentification", 0x0501: "G1_CardIccIdentification",
            0x0502: "G1_EventsData", 0x0503: "G1_FaultsData", 0x0504: "G1_DriverActivityData",
            0x0505: "G1_VehiclesUsed", 0x0506: "G1_Places", 0x0507: "G1_CurrentUsage",
            0x0508: "G1_ControlActivityData", 0x050C: "CalibrationData",
            0x050E: "G1_CardDownload", 0x0520: "G1_Identification",
            0x0521: "G1_DrivingLicenceInfo", 0x0522: "G1_SpecificConditions",
            0x0523: "G2_VehiclesUsed", 0x0524: "G2_DriverActivityData",
            0x0206: "VU_ActivityDailyRecord", 0x0222: "EF_GNSS_Places",
            0x0223: "EF_GNSS_Accumulated_Position", 0xC100: "G1_CardCertificate",
            0xC108: "G1_CA_Certificate", 0xC101: "G2_CardCertificate", 0xC109: "G2_CA_Certificate",
            # Gen 2.2 (Smart V2) - Reg. EU 2023/980
            0x7631: "G22_ApplicationContainer",
            0x0525: "G22_GNSSAccumulatedDriving",
            0x0526: "G22_LoadUnloadOperations",
            0x0527: "G22_TrailerRegistrations",
            0x0528: "G22_GNSSEnhancedPlaces",
            0x0529: "G22_LoadSensorData",
            0x052A: "G22_BorderCrossings",
            0x0225: "G22_VU_GNSSADRecord",
            0x0226: "G22_VU_LoadUnloadRecord",
            0x0227: "G22_VU_TrailerRecord",
            0x0228: "G22_VU_BorderCrossingRecord",
            0xC102: "G22_CardCertificate", 0xC10A: "G22_CA_Certificate"
        }
        json_path = os.path.join(os.path.dirname(os.path.dirname(self.file_path)), 'all_tacho_tags.json')
        if not os.path.exists(json_path): json_path = 'all_tacho_tags.json'
        if os.path.exists(json_path):
            try:
                with open(json_path, 'r') as f:
                    extra_tags = json.load(f)
                    for k, v in extra_tags.items(): tags[int(k, 16)] = v
            except: pass
        return tags

    def _safe_read(self, pos, length):
        if pos < 0 or length < 0 or (pos + length) > self.file_size: return None
        try: return self.raw_data[pos : pos + length]
        except: return None

    def get_coverage_report(self):
        """Returns the percentage of bytes assigned to identified fields."""
        if self.file_size == 0: return 0.0
        return round((self.bytes_covered / self.file_size) * 100, 2)

    def parse(self):
        if not os.path.exists(self.file_path):
            self.results["metadata"]["integrity_check"] = "File Not Found"
            return self.results
        if self.file_size == 0:
            self.results["metadata"]["integrity_check"] = "Empty File"
            return self.results

        try:
            self._fd = open(self.file_path, 'rb')
            self.raw_data = mmap.mmap(self._fd.fileno(), 0, access=mmap.ACCESS_READ)
            
            header = self._safe_read(0, 2)
            if header == b'\x76\x31':
                self.results["metadata"]["generation"] = "G2.2 (Smart V2)"
            elif header in (b'\x76\x21', b'\x76\x22'):
                self.results["metadata"]["generation"] = "G2 (Smart)"
            else:
                self.results["metadata"]["generation"] = "G1 (Digital)"

            # Recursive parsing
            self.navigator.parse_stap_recursive(0, self.file_size)

            self.results["metadata"]["coverage_pct"] = self.get_coverage_report()
            
            # Post-processing: Deduplication & Sorting
            seen = {}
            unique = []
            for act in self.results["activities"]:
                key = f"{act['data']}_{len(act['eventi'])}"
                if key not in seen:
                    seen[key] = True
                    unique.append(act)
            unique.sort(key=lambda x: datetime.strptime(x["data"], '%d/%m/%Y') if x["data"] != "N/A" else datetime.min, reverse=True)
            self.results["activities"] = unique
            
            # Forensic Validation
            if self.card_cert_raw and self.msca_cert_raw:
                status, pubkey = self.validator.validate_tacho_chain(self.card_cert_raw, self.msca_cert_raw)
                if status is True: self.validation_status, self.card_public_key = "Verified", pubkey
                elif status == "Incomplete (Missing ERCA)": self.validation_status, self.card_public_key = "Verified (Local Chain)", pubkey
                else: self.validation_status = "Invalid Certificate Chain"
            else: self.validation_status = "Incomplete Certificates"

            self.results["metadata"]["integrity_check"] = self.validation_status

            if GEOCODING_AVAILABLE and self.results["locations"]:
                try: self.results = process_locations_with_geocoding(self.results)
                except: pass

        except Exception as e:
            self.results["metadata"]["integrity_check"] = f"Error: {str(e)}"
        finally:
            if self.raw_data: self.raw_data.close()
            if self._fd: self._fd.close()
        
        return self.results

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        print(json.dumps(TachoParser(sys.argv[1]).parse(), indent=2))
