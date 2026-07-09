"""Structural parser: deterministic byte walker, record dispatcher and G1/G2 VU walkers."""

# ruff: noqa: F401

from core.parser.deterministic import DeterministicParser
from core.parser.record_array import RecordArrayParser, parse_g2_trep02_activities
from core.parser.g1_walker import iter_g1_vu_messages, walk_g1_vu, TREP_NAMES
from core.parser.vu_dispatcher import (
    iter_vu_sections,
    walk_vu_record_arrays,
    RECORD_TYPES,
    TREP_SECTIONS,
)
