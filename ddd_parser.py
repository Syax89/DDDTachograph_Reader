import struct
import os
import json
import mmap
import logging
from datetime import datetime

# Configure basic logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

try:
    from geocoding_engine import process_locations_with_geocoding
    GEOCODING_AVAILABLE = True
except ImportError:
    GEOCODING_AVAILABLE = False

from signature_validator import SignatureValidator
from core.models import TachoResult
from core.tag_navigator import TagNavigator
from src.infrastructure.parsers.tag_definitions import TACHO_TAGS

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
        tags = TACHO_TAGS.copy()
        json_path = os.path.join(os.path.dirname(os.path.dirname(self.file_path)), 'all_tacho_tags.json')
        if not os.path.exists(json_path): json_path = 'all_tacho_tags.json'
        if os.path.exists(json_path):
            try:
                with open(json_path, 'r') as f:
                    extra_tags = json.load(f)
                    for k, v in extra_tags.items(): tags[int(k, 16)] = v
            except (json.JSONDecodeError, ValueError) as e:
                logger.warning(f"Failed to load extra tags from {json_path}: {e}")
        return tags

    def _safe_read(self, pos, length):
        if pos < 0 or length < 0 or (pos + length) > self.file_size: return None
        try:
            return self.raw_data[pos : pos + length]
        except Exception as e:
            logger.error(f"Safe read failed at pos {pos}, length {length}: {e}")
            return None

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
                try:
                    self.results = process_locations_with_geocoding(self.results)
                except Exception as e:
                    logger.error(f"Geocoding processing failed: {e}")

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
