#!/usr/bin/env python3
"""Generate the normative tag/FID matrix from DecoderRegistry.

The registry is the executable source of truth for dispatch. This script makes
that source auditable by exporting every registered variant with generation,
scope, encoding, status and Annex/regulatory reference.
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.decoder_registry import DecoderRegistry, TagDecoder  # noqa: E402


def scope(decoder: TagDecoder) -> str:
    if decoder.card_only:
        return "Card"
    if decoder.vu_only:
        return "VU"
    return "Card/VU"


def encoding(decoder: TagDecoder) -> str:
    if (decoder.tag & 0xFF00) == 0x7600:
        return "SID/TREP" if decoder.generation == "G1" else "TREP/RecordArray"
    if decoder.vu_only and 0x0509 <= decoder.tag <= 0x0533:
        return "RecordArray"
    if decoder.generation == "G1":
        return "STAP/T2L2"
    if decoder.generation in ("G2", "G2.2"):
        return "BER-TLV"
    return "STAP/BER"


def status(decoder: TagDecoder) -> str:
    if decoder.container:
        return "container"
    if decoder.signature_block:
        return "signature"
    if decoder.decoder_fn:
        return "decoded"
    return "recognized_raw"


def row(decoder: TagDecoder) -> dict:
    return {
        "tag": f"0x{decoder.tag:04X}",
        "name": decoder.name,
        "generation": decoder.generation,
        "scope": scope(decoder),
        "encoding": encoding(decoder),
        "status": status(decoder),
        "decoder": decoder.decoder_fn.__name__ if decoder.decoder_fn else "",
        "container": decoder.container,
        "signature_block": decoder.signature_block,
        "min_length": decoder.min_length,
        "max_length": decoder.max_length,
        "record_size": decoder.record_size,
        "dtypes": [f"0x{d:02X}" for d in decoder.dtypes] if decoder.dtypes else [],
        "parent_tags": [f"0x{t:04X}" for t in decoder.parent_tags] if decoder.parent_tags else [],
        "annex_ref": decoder.annex_ref,
    }


def rows() -> list[dict]:
    return [row(decoder) for decoder in DecoderRegistry.instance().iter_decoders()]


def print_markdown(matrix: list[dict]) -> None:
    print("# Generated Tag/FID Decoding Matrix")
    print()
    print("Generated from `core.decoder_registry.DecoderRegistry`. Do not hand-edit")
    print("the table content; update registry definitions or this generator instead.")
    print()
    print("| Tag | Name | Generation | Scope | Encoding | Status | Decoder | Record Size | Annex / Regulation |")
    print("|---:|---|---|---|---|---|---|---:|---|")
    for item in matrix:
        record_size = item["record_size"] if item["record_size"] is not None else ""
        print(
            f"| `{item['tag']}` | {item['name']} | {item['generation']} | "
            f"{item['scope']} | {item['encoding']} | {item['status']} | "
            f"`{item['decoder']}` | {record_size} | {item['annex_ref']} |"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="emit JSON instead of Markdown")
    args = parser.parse_args()

    matrix = rows()
    if args.json:
        print(json.dumps(matrix, indent=2, sort_keys=True))
    else:
        print_markdown(matrix)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
