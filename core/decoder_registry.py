"""Centralized decoder registry with tag → decoder mapping, priorities, and validation rules.

Architecture: Schema-Driven Parser — Agent 5
All known tag definitions consolidated in one place for deterministic dispatch.
"""

from dataclasses import dataclass
from typing import Optional, Callable, Dict, List
import threading


@dataclass
class TagDecoder:
    tag: int
    name: str
    decoder_fn: Optional[Callable] = None
    container: bool = False
    min_length: int = 0
    max_length: int = 0x100000
    record_size: Optional[int] = None
    annex_ref: str = ""
    generation: str = "all"
    card_only: bool = False
    vu_only: bool = False
    signature_block: bool = False
    priority: int = 0


class DecoderRegistry:
    """Central registry of all known tag decoders with spec references."""

    _instance: Optional["DecoderRegistry"] = None
    _lock: threading.Lock = threading.Lock()

    def __init__(self):
        self._registry: Dict[int, TagDecoder] = {}
        self._container_tags: set = set()
        self._signature_tags: set = set()
        self._build()

    @classmethod
    def instance(cls) -> "DecoderRegistry":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        with cls._lock:
            cls._instance = None

    def _build(self):
        from . import decoders

        definitions = [

            # ── Generation 1 & 2 Common ──
            TagDecoder(0x0001, "VU_VehicleIdentification",
                       decoders.parse_vu_vehicle_identification,
                       annex_ref="Annex 1B §2.15", generation="G1", vu_only=True,
                       min_length=32, record_size=32),

            TagDecoder(0x0002, "EF_ICC",
                       decoders.parse_ef_icc,
                       annex_ref="Annex 1B §2.7", generation="G1", card_only=True,
                       min_length=4),

            TagDecoder(0x0005, "EF_IC",
                       decoders.parse_ef_ic,
                       annex_ref="Annex 1B §2.6", generation="G1", card_only=True,
                       min_length=2, record_size=8),

            TagDecoder(0x0100, "CardIssuerIdentification",
                       decoders.parse_card_issuer_identification,
                       annex_ref="Annex 1B §2.9", generation="G1", card_only=True,
                       min_length=20),

            TagDecoder(0x0101, "G2_CardIccIdentification",
                       decoders.parse_g2_card_icc_identification,
                       annex_ref="Annex 1C §2.23", generation="G2", card_only=True,
                       min_length=24),

            TagDecoder(0x0102, "G2_CardIdentification",
                       decoders.parse_card_identification,
                       annex_ref="Annex 1B §2.15", generation="G2", card_only=True,
                       min_length=65, record_size=65),

            TagDecoder(0x0201, "G2_DriverCardHolderIdentification",
                       decoders.parse_driver_card_holder_identification,
                       annex_ref="Annex 1B §2.17", generation="all",
                       min_length=78, record_size=78),

            TagDecoder(0x2020, "CompanyHolderData",
                       decoders.parse_company_holder_data,
                       annex_ref="Annex 1B", generation="G1",
                       min_length=10),

            TagDecoder(0x0501, "G1_DriverCardApplicationIdentification",
                       decoders.parse_g1_app_identification,
                       annex_ref="Annex 1B §2.28", generation="G1", card_only=True,
                       min_length=10, record_size=10),

            TagDecoder(0x0502, "G1_EventsData",
                       decoders.parse_g1_events_data,
                       annex_ref="Annex 1B §2.20", generation="G1", card_only=True,
                       min_length=24),

            TagDecoder(0x0503, "G1_FaultsData",
                       decoders.parse_g1_faults_data,
                       annex_ref="Annex 1B §2.21", generation="G1", card_only=True,
                       min_length=24),

            TagDecoder(0x0504, "G1_DriverActivityData",
                       decoders.parse_cyclic_buffer_activities,
                       annex_ref="Annex 1B §2.32", generation="G1", card_only=True,
                       min_length=16),

            TagDecoder(0x0505, "G1_VehiclesUsed",
                       decoders.parse_g1_vehicles_used,
                       annex_ref="Annex 1B §2.19", generation="G1", card_only=True,
                       min_length=4, record_size=31),

            TagDecoder(0x0506, "G1_Places",
                       decoders.parse_g1_places,
                       annex_ref="Annex 1B §2.22", generation="G1", card_only=True,
                       min_length=10),

            TagDecoder(0x0507, "G1_CurrentUsage",
                       decoders.parse_g1_current_usage,
                       annex_ref="Annex 1B §2.23", generation="G1", card_only=True,
                       min_length=19, record_size=19),

            TagDecoder(0x0508, "G1_ControlActivityData",
                       decoders.parse_control_activity_data,
                       annex_ref="Annex 1B §2.23", generation="G1", card_only=True,
                       min_length=46, record_size=46),

            TagDecoder(0x0509, "VuCardRecord",
                       decoders.parse_g2_vu_record,
                       annex_ref="Annex 1C §4.5.3.2.8", generation="G2",
                       vu_only=True, priority=1),

            TagDecoder(0x050A, "VuCardIWRecord",
                       decoders.parse_g2_vu_record,
                       annex_ref="Annex 1C §4.5.3.2.9", generation="G2",
                       vu_only=True, priority=1),

            TagDecoder(0x050B, "VuDownloadablePeriod",
                       decoders.parse_g2_vu_record,
                       annex_ref="Annex 1C §4.5.3.2.10", generation="G2",
                       vu_only=True, priority=1),

            TagDecoder(0x050C, "CalibrationData",
                       decoders.parse_calibration_data,
                       annex_ref="Annex 1B §2.118", generation="all",
                       min_length=167),

            TagDecoder(0x050D, "VuTimeAdjustmentData",
                       decoders.parse_g2_vu_record,
                       annex_ref="Annex 1C §4.5.3.2.12", generation="G2",
                       vu_only=True, priority=1),

            TagDecoder(0x050E, "G1_CardDownload",
                       decoders.parse_card_download,
                       annex_ref="Annex 1B §2.18", generation="G1", card_only=True,
                       min_length=4),

            TagDecoder(0x050F, "VuCompanyLocksData",
                       decoders.parse_g2_vu_record,
                       annex_ref="Annex 1C §4.5.3.2.13", generation="G2",
                       vu_only=True, priority=1),

            TagDecoder(0x0510, "SensorPairedData",
                       decoders.parse_g2_vu_record,
                       annex_ref="Annex 1C §4.5.3.2.14", generation="G2",
                       vu_only=True, priority=1),

            TagDecoder(0x0511, "SensorExternalGNSSCoupledData",
                       decoders.parse_g2_vu_record,
                       annex_ref="Annex 1C §4.5.3.2.15", generation="G2",
                       vu_only=True, priority=1),

            TagDecoder(0x0512, "VuITSConsentData",
                       decoders.parse_g2_vu_record,
                       annex_ref="Annex 1C §4.5.3.2.16", generation="G2",
                       vu_only=True, priority=1),

            TagDecoder(0x0520, "G1_Identification",
                       decoders.parse_g1_identification,
                       annex_ref="Annex 1B §2.15+§2.17", generation="G1", card_only=True,
                       min_length=65, record_size=143),

            TagDecoder(0x0521, "G1_DrivingLicenceInfo",
                       decoders.parse_g1_driving_licence,
                       annex_ref="Annex 1B §2.26", generation="G1", card_only=True,
                       min_length=53, record_size=53),

            TagDecoder(0x0522, "G1_SpecificConditions",
                       decoders.parse_specific_conditions,
                       annex_ref="Annex 1B §2.27", generation="G1", card_only=True,
                       min_length=8),

            TagDecoder(0x0523, "G2_VehiclesUsed",
                       decoders.parse_g1_vehicles_used,
                       annex_ref="Annex 1C §2.19", generation="G2", card_only=True,
                       min_length=4, record_size=35),

            TagDecoder(0x0524, "G2_DriverActivityData",
                       decoders.parse_cyclic_buffer_activities,
                       annex_ref="Annex 1C §2.32", generation="G2", card_only=True,
                       min_length=16),

            TagDecoder(0x0206, "VU_ActivityDailyRecord",
                       decoders.parse_cyclic_buffer_activities,
                       annex_ref="Annex 1C", generation="G2",
                       min_length=100),

            # ── G2.2 GNSS / Load / Trailer tags ──
            TagDecoder(0x0525, "G22_GNSSAccumulatedDriving",
                       decoders.parse_g22_gnss_accumulated_driving,
                       annex_ref="Reg. EU 2021/1228", generation="G2.2",
                       min_length=12, container=True),

            TagDecoder(0x0526, "G22_LoadUnloadOperations",
                       decoders.parse_g22_load_unload_operations,
                       annex_ref="ASN.1: LoadUnloadRecord", generation="G2.2",
                       min_length=13, container=True),

            TagDecoder(0x0527, "G22_TrailerRegistrations",
                       decoders.parse_g22_trailer_registrations,
                       annex_ref="ASN.1: TrailerRegistrationRecord", generation="G2.2",
                       min_length=20, container=True),

            TagDecoder(0x0528, "G22_GNSSEnhancedPlaces",
                       decoders.parse_g22_gnss_enhanced_places,
                       annex_ref="Annex 1C §2.79c", generation="G2.2",
                       min_length=14, container=True),

            TagDecoder(0x0529, "G22_LoadSensorData",
                       decoders.parse_g22_load_sensor_data,
                       annex_ref="Reg. EU 2023/980", generation="G2.2",
                       min_length=8, container=True),

            TagDecoder(0x052A, "G22_BorderCrossings",
                       decoders.parse_g22_border_crossings,
                       annex_ref="ASN.1: BorderCrossingRecord", generation="G2.2",
                       min_length=14, container=True),

            TagDecoder(0x0225, "G22_VU_GNSSADRecord",
                       decoders.parse_g22_gnss_accumulated_driving,
                       annex_ref="Reg. EU 2023/980", generation="G2.2",
                       vu_only=True, container=True),

            TagDecoder(0x0226, "G22_VU_LoadUnloadRecord",
                       decoders.parse_g22_load_unload_operations,
                       annex_ref="Reg. EU 2023/980", generation="G2.2",
                       vu_only=True, container=True),

            TagDecoder(0x0227, "G22_VU_TrailerRecord",
                       decoders.parse_g22_trailer_registrations,
                       annex_ref="Reg. EU 2023/980", generation="G2.2",
                       vu_only=True, container=True),

            TagDecoder(0x0228, "G22_VU_BorderCrossingRecord",
                       decoders.parse_g22_border_crossings,
                       annex_ref="Reg. EU 2023/980", generation="G2.2",
                       vu_only=True, container=True),

            TagDecoder(0x0222, "EF_GNSS_Places",
                       decoders.parse_g22_gnss_enhanced_places,
                       annex_ref="Annex 1C GNSS", generation="G2",
                       min_length=14),

            TagDecoder(0x0223, "EF_GNSS_Accumulated_Position",
                       decoders.parse_g22_gnss_accumulated_driving,
                       annex_ref="Annex 1C GNSS", generation="G2",
                       min_length=16),

            # ── G2.2 VU Record Tags ──
            TagDecoder(0x052B, "VuControllerIdentification",
                       decoders.parse_g2_vu_record,
                       annex_ref="Reg. EU 2023/980", generation="G2.2",
                       vu_only=True, priority=1),

            TagDecoder(0x052C, "VuDetailedSpeedData",
                       decoders.parse_g2_vu_record,
                       annex_ref="Reg. EU 2023/980", generation="G2.2",
                       vu_only=True, priority=1),

            TagDecoder(0x052D, "VuOverSpeedingEventData",
                       decoders.parse_g2_vu_record,
                       annex_ref="Annex 1C §2.215", generation="G2.2",
                       vu_only=True, priority=1, record_size=32),

            TagDecoder(0x052E, "VuOverSpeedingControlData",
                       decoders.parse_g2_vu_record,
                       annex_ref="Annex 1C §2.212", generation="G2.2",
                       vu_only=True, priority=1, record_size=9),

            TagDecoder(0x052F, "VuTimeAdjustmentGNSSRecord",
                       decoders.parse_g2_vu_record,
                       annex_ref="Annex 1C §2.230", generation="G2.2",
                       vu_only=True, priority=1, record_size=8),

            TagDecoder(0x0530, "VuPowerSupplyInterruptionData",
                       decoders.parse_g2_vu_record,
                       annex_ref="Annex 1C §2.240", generation="G2.2",
                       vu_only=True, priority=1, record_size=87),

            TagDecoder(0x0531, "VuSensorFaultData",
                       decoders.parse_g2_vu_record,
                       annex_ref="Annex 1C §2.240", generation="G2.2",
                       vu_only=True, priority=1, record_size=90),

            TagDecoder(0x0532, "G22_SensorExternalGNSSCoupledData",
                       decoders.parse_g2_vu_record,
                       annex_ref="Reg. EU 2023/980", generation="G2.2",
                       vu_only=True, priority=1),

            TagDecoder(0x0533, "G22_SensorPairedData",
                       decoders.parse_g2_vu_record,
                       annex_ref="Reg. EU 2023/980", generation="G2.2",
                       vu_only=True, priority=1),

            # ── G1 VU Containers ──
            TagDecoder(0x7601, "G1_VU_TechnicalData",
                       decoders.parse_g1_vu_overview,
                       annex_ref="Annex 1B §4.5.3.2.2", generation="G1",
                       vu_only=True, container=True, min_length=200),

            TagDecoder(0x7602, "G1_VU_Activities",
                       annex_ref="Annex 1B §4.5.3.2.3", generation="G1",
                       vu_only=True, container=True),

            TagDecoder(0x7603, "G1_VU_EventsFaults",
                       annex_ref="Annex 1B §4.5.3.2.4", generation="G1",
                       vu_only=True, container=True),

            TagDecoder(0x7604, "G1_VU_Speed",
                       annex_ref="Annex 1B §4.5.3.2.5", generation="G1",
                       vu_only=True, container=True),

            TagDecoder(0x7605, "G1_VU_TechnicalData",
                       annex_ref="Annex 1B §4.5.3.2.2", generation="G1",
                       vu_only=True, container=True),

            # ── G2 VU Containers ──
            TagDecoder(0x7621, "G2_ApplicationContainer",
                       annex_ref="Annex 1C §4.5.3.2", generation="G2",
                       vu_only=True, container=True),

            TagDecoder(0x7622, "G2_VU_Activities",
                       annex_ref="Annex 1C §4.5.3.2.3", generation="G2",
                       vu_only=True, container=True),

            TagDecoder(0x7623, "G2_VU_EventsFaults",
                       annex_ref="Annex 1C §4.5.3.2.4", generation="G2",
                       vu_only=True, container=True),

            TagDecoder(0x7624, "G2_VU_Speed",
                       annex_ref="Annex 1C §4.5.3.2.5", generation="G2",
                       vu_only=True, container=True),

            TagDecoder(0x7D21, "G2_SecurityContainer",
                       annex_ref="Annex 1C §4.5.3.2.7", generation="G2",
                       container=True),

            TagDecoder(0xAD21, "G2_SecurityContainer",
                       annex_ref="Annex 1C §4.5.3.2.7", generation="G2",
                       container=True),

            # ── G2.2 Containers ──
            TagDecoder(0x7631, "G22_ApplicationContainer",
                       annex_ref="Reg. EU 2023/980", generation="G2.2",
                       vu_only=True, container=True),

            TagDecoder(0x7632, "G22_VU_Activities",
                       annex_ref="Reg. EU 2023/980", generation="G2.2",
                       vu_only=True, container=True),

            TagDecoder(0x7633, "G22_VU_EventsFaults",
                       annex_ref="Reg. EU 2023/980", generation="G2.2",
                       vu_only=True, container=True),

            TagDecoder(0x7634, "G22_VU_Speed",
                       annex_ref="Reg. EU 2023/980", generation="G2.2",
                       vu_only=True, container=True),

            TagDecoder(0x7F21, "G22_CardCertificateContainer",
                       annex_ref="Reg. EU 2023/980", generation="G2.2",
                       container=True),

            TagDecoder(0x7F4E, "G22_SecurityContainer",
                       annex_ref="Reg. EU 2023/980", generation="G2.2",
                       container=True),

            # ── Certificate Tags ──
            TagDecoder(0xC100, "G1_CardCertificate",
                       decoders.parse_g1_certificate,
                       annex_ref="Annex 1B §2.29", generation="G1",
                       signature_block=True, record_size=194),

            TagDecoder(0xC108, "G1_CA_Certificate",
                       decoders.parse_g1_certificate,
                       annex_ref="Annex 1B §2.30", generation="G1",
                       signature_block=True, record_size=194),

            TagDecoder(0xC101, "G2_CardCertificate",
                       decoders.parse_g1_certificate,
                       annex_ref="Annex 1C §2.30", generation="G2",
                       signature_block=True),

            TagDecoder(0xC109, "G2_CA_Certificate",
                       decoders.parse_g1_certificate,
                       annex_ref="Annex 1C §2.31", generation="G2",
                       signature_block=True),

            TagDecoder(0x0103, "G2_CardCertificate",
                       decoders.parse_g1_certificate,
                       annex_ref="Annex 1C §2.30", generation="G2",
                       signature_block=True, record_size=194),

            TagDecoder(0x0104, "G2_MemberStateCertificate",
                       decoders.parse_g1_certificate,
                       annex_ref="Annex 1C §2.31", generation="G2",
                       signature_block=True, record_size=194),

            TagDecoder(0xC102, "G22_CardCertificate",
                       decoders.parse_g1_certificate,
                       annex_ref="Reg. EU 2023/980", generation="G2.2",
                       signature_block=True),

            TagDecoder(0xC10A, "G22_CA_Certificate",
                       decoders.parse_g1_certificate,
                       annex_ref="Reg. EU 2023/980", generation="G2.2",
                       signature_block=True),

            # ── G2.2 Certificate Profile ──
            TagDecoder(0x42, "CertificateProfileIdentifier",
                       decoders.parse_g22_certificate_profile,
                       annex_ref="Annex 1C §2.80", generation="G2.2",
                       min_length=2),

            TagDecoder(0x4208, "G22_CertificateProfileIdentifier",
                       decoders.parse_g22_certificate_profile,
                       annex_ref="Reg. EU 2023/980", generation="G2.2",
                       min_length=2),

            # ── BER-TLV Sub-tags (G2.2 certificate internals) ──
            TagDecoder(0x5F29, "G22_CardIssuingMemberState",
                       decoders.parse_g22_certificate_subtag,
                       annex_ref="Annex 1C §2.24", generation="G2.2",
                       min_length=1),

            TagDecoder(0x5F4C, "G22_CardExtendedSerialNumber",
                       decoders.parse_g22_certificate_subtag,
                       annex_ref="Annex 1C §2.23", generation="G2.2"),

            TagDecoder(0x5F20, "G22_CardHolderName",
                       decoders.parse_g22_certificate_subtag,
                       annex_ref="Annex 1C §2.17", generation="G2.2"),

            TagDecoder(0x5F25, "G22_CardExpiryDate",
                       decoders.parse_g22_certificate_subtag,
                       annex_ref="Annex 1C §2.24", generation="G2.2"),

            TagDecoder(0x5F24, "G22_CardEffectiveDate",
                       decoders.parse_g22_certificate_subtag,
                       annex_ref="Annex 1C §2.24", generation="G2.2"),

            TagDecoder(0x5F37, "G22_CertificateSignature",
                       decoders.parse_certificate_signature,
                       annex_ref="Annex 1C §2.31", generation="G2.2"),

            TagDecoder(0x7F49, "G22_PublicKeyInfo",
                       decoders.parse_public_key_info,
                       annex_ref="Annex 1C §2.30", generation="G2.2"),

            TagDecoder(0x960F, "G22_GNSS_Auth_Data",
                       decoders.parse_g22_auth_subtag,
                       annex_ref="Reg. EU 2023/980", generation="G2.2"),

            TagDecoder(0x6399, "G22_Load_Unload_Auth",
                       decoders.parse_g22_auth_subtag,
                       annex_ref="Reg. EU 2023/980", generation="G2.2"),
        ]

        for d in definitions:
            self._registry[d.tag] = d
            if d.container or (d.tag & 0xFF00) == 0x7600:
                self._container_tags.add(d.tag)
            if d.signature_block:
                self._signature_tags.add(d.tag)

    def get_decoder(self, tag: int) -> Optional[TagDecoder]:
        return self._registry.get(tag)

    def is_container(self, tag: int) -> bool:
        if tag in self._container_tags:
            return True
        if (tag & 0xFF00) == 0x7600:
            return True
        return False

    def is_signature(self, tag: int) -> bool:
        return tag in self._signature_tags

    def get_all_tags(self) -> List[int]:
        return sorted(self._registry.keys())

    def get_unhandled_tags(self, seen_tags: set) -> List[TagDecoder]:
        """Return tag decoders in registry that weren't dispatched."""
        return [self._registry[t] for t in sorted(self._registry) if t not in seen_tags]

    def get_spec_ref(self, tag: int) -> str:
        dec = self._registry.get(tag)
        return dec.annex_ref if dec else ""

    def get_by_generation(self, generation: str) -> List[TagDecoder]:
        return [d for d in self._registry.values()
                if d.generation == generation or d.generation == "all"]

    def get_containers(self) -> List[TagDecoder]:
        return [d for d in self._registry.values() if d.container]

    def get_prioritized(self) -> List[TagDecoder]:
        return sorted(self._registry.values(), key=lambda d: (-d.priority, d.tag))

    def __len__(self) -> int:
        return len(self._registry)

    def __contains__(self, tag: int) -> bool:
        return tag in self._registry
