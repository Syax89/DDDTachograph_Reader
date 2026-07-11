"""Shared utilities: encoding, reporting, logging, constants, BER-TLV, coverage, event codes."""

# ruff: noqa: F401

from core.utils.encoding import BytesEncoder
from core.utils.version import __version__, APP_NAME
from core.utils.report_format import (
    records_to_table,
    section_tables,
    summary_rows,
    humanize_key,
    fmt_value,
    expand_activities,
)
from core.utils.tag_defs import TACHO_TAGS
from core.utils.logger import (
    get_logger,
    decoder_failure_count,
    decoder_failures,
    reset_decoder_failures,
)
from core.utils.constants import (
    MAX_TLV_LENGTH,
    MAX_RECURSION_DEPTH,
    EC_CURVE_OIDS,
    RECORD_ARRAY_MAX_RECORDS,
    RECORD_ARRAY_MAX_SIZE,
    MAX_ODO_DISTANCE_KM,
)
from core.utils.ber_tlv import read_ber_tlv_header
from core.utils.coverage import (
    KNOWN_PADDING_BYTES,
    coverage_metrics,
    coverage_pct,
    is_padding_block,
    merge_intervals,
)
from core.utils.event_codes import (
    describe_event,
    describe_fault,
    describe_calibration_purpose,
    describe_control_type,
    specific_condition_label,
)
