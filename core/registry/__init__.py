"""Decoder registry: tag-to-decoder mapping with context-aware scoring."""

# ruff: noqa: F401

from core.registry.registry import DecoderRegistry, TagDecoder
from core.registry.models import TachoResult, build_generations_tree, _clean_tag_name
