"""Deterministic walker for Gen1 VU downloads (Annex 1B §2.2.6).

A G1 VU download is a sequence of messages ``SID 0x76 + TREP + body`` where
the body length is fully determined by the TREP structure itself (fixed
prefixes plus count-prefixed record sections — there is no TLV length field).
When the download was requested with signatures, each body is followed by its
128-byte RSA signature.

Body layouts (Annex 1B §2.2.6.1-2.2.6.6):

  TREP 01 Overview:      certificates(194+194) + VIN(17) + registration(15)
                         + 3×TimeReal(12) + slots(1) [=433]
                         + VuDownloadActivityData(58)
                         + noOfLocks(1) + 98×N + noOfControls(1) + 31×N
  TREP 02 Activities:    dateOfDay(4) + odometerMidnight(3)
                         + noOfIW(2) + 129×N + noOfChanges(2) + 2×N
                         + noOfPlaces(1) + 28×N + noOfConditions(2) + 5×N
  TREP 03 EventsFaults:  noOfFaults(1) + 82×N + noOfEvents(1) + 83×N
                         + overspeedControl(9) + noOfOverspeed(1) + 31×N
                         + noOfTimeAdj(1) + 98×N
  TREP 04 DetailedSpeed: noOfSpeedBlocks(2) + 64×N
  TREP 05 TechnicalData: VuIdentification(116) + SensorPaired(20)
                         + noOfCalibrations(1) + 167×N
  TREP 06 CardDownload:  variable-length card data; body extends to next
                          0x76 TREP marker or EOF
  TREP 11 Sensor/Special: non-standard raw S-section observed in sensor files;
                          body extends to TREP 14 trailer
  TREP 14 Trailer:       2-byte raw terminator observed as 0x0000

Confirmed against real G1 VU downloads: the walk lands exactly on every
subsequent ``0x76 TREP`` marker and on the end of file.
"""
import struct

from core.utils.logger import get_logger
from core.parser.card_envelope import card_image_extent
from core.decoders.vu_g1 import (
    parse_g1_vu_overview,
    _parse_trep_02_activities,
    _parse_trep_02_g1_structured,
    _parse_trep_03_events_faults,
    _parse_trep_04_speed,
    _parse_trep_05_technical,
    _parse_trep_06_card_download,
    _parse_sensor_download,
)

_log = get_logger(__name__)

RSA_SIGNATURE_LEN = 128
MAX_CHAIN_VALIDATION_DEPTH = 64

TREP_NAMES = {
    0x01: "Overview",
    0x02: "Activities",
    0x03: "EventsFaults",
    0x04: "DetailedSpeed",
    0x05: "TechnicalData",
    0x06: "CardDownload",
    0x11: "SensorSpecialData",
    0x14: "SensorTrailer",
}


def _trep01_body_len(d, p, n):
    q = p + 433 + 58
    if q >= n:
        return None
    q += 1 + d[q] * 98          # VuCompanyLocksData
    if q >= n:
        return None
    q += 1 + d[q] * 31          # VuControlActivityData
    return q - p if q <= n else None


def _trep02_body_len(d, p, n):
    q = p + 7                   # dateOfDay(4) + odometerMidnight(3)
    if q + 2 > n:
        return None
    q += 2 + struct.unpack(">H", d[q:q + 2])[0] * 129   # VuCardIWData
    if q + 2 > n:
        return None
    q += 2 + struct.unpack(">H", d[q:q + 2])[0] * 2     # VuActivityDailyData
    if q + 1 > n:
        return None
    q += 1 + d[q] * 28                                  # VuPlaceDailyWorkPeriodData
    if q + 2 > n:
        return None
    q += 2 + struct.unpack(">H", d[q:q + 2])[0] * 5     # VuSpecificConditionData
    return q - p if q <= n else None


def _trep03_body_len(d, p, n):
    q = p
    if q >= n:
        return None
    q += 1 + d[q] * 82          # VuFaultData
    if q >= n:
        return None
    q += 1 + d[q] * 83          # VuEventData
    q += 9                      # VuOverSpeedingControlData
    if q >= n:
        return None
    q += 1 + d[q] * 31          # VuOverSpeedingEventData
    if q >= n:
        return None
    q += 1 + d[q] * 98          # VuTimeAdjustmentData
    return q - p if q <= n else None


def _trep04_body_len(d, p, n):
    if p + 2 > n:
        return None
    q = p + 2 + struct.unpack(">H", d[p:p + 2])[0] * 64
    return q - p if q <= n else None


def _trep05_body_len(d, p, n):
    q = p + 116 + 20
    if q >= n:
        return None
    q += 1 + d[q] * 167         # VuCalibrationData
    return q - p if q <= n else None


def _trep06_body_len(d, p, n):
    return _next_valid_marker(d, p, n) - p


def _trep11_body_len(d, p, n):
    # A genuine G1 sensor download (TREP 0x11) is always closed by a
    # ``76 14`` trailer. Without that trailer the ``76 11`` we are looking at
    # is a false marker inside another section's payload (typically a byte pair
    # in TREP 06 card-download data), so this is NOT a valid TREP 11 body.
    # Returning None makes the chain validation reject the candidate boundary,
    # letting the unbounded CardDownload extend to its real end instead of
    # being split mid-record and fed to the sensor decoder as garbage.
    pos = p
    while pos < n - 1:
        if d[pos] == 0x76 and d[pos + 1] == 0x14:
            return pos - p
        pos += 1
    return None


def _trep14_body_len(d, p, n):
    return 2 if p + 2 <= n else None


def _new_walk_ctx():
    """Shared caches for one walk over a fixed ``(d, n)`` buffer.

    ``markers`` memoises ``_next_valid_marker(p)`` by start offset and ``memo``
    memoises ``_valid_chain_from(pos)`` by position. Both are pure functions of
    the buffer, so sharing them across a whole walk keeps the nested
    CardDownload boundary search polynomial instead of exponential.
    """
    return {"memo": {}, "markers": {}}


def _next_valid_marker(d, p, n, validation_depth=0, ctx=None):
    """Return the next marker that starts a valid TREP chain, or EOF.

    TREP 06 CardDownload has no explicit length. Card EF payloads can contain
    byte pairs such as ``76 01`` that look like message markers, so a raw scan
    would split the card data in the middle. Accept a candidate boundary only
    when the remaining bytes form a valid Annex 1B TREP sequence.

    *ctx* carries the shared memo/cache across a whole walk: without it every
    nested CardDownload node restarts the boundary search from scratch, which a
    crafted repeated ``76 04 00 00 76 06 00 00 00 00`` pattern turns into
    exponential time.
    """
    if ctx is None:
        ctx = _new_walk_ctx()
    markers = ctx["markers"]
    if p in markers:
        return markers[p]
    memo = ctx["memo"]
    pos = p
    result = n
    while pos < n - 1:
        if d[pos] == 0x76 and d[pos + 1] in TREP_NAMES:
            # A nested TREP 06 candidate cannot be disambiguated from card EF
            # payload without a length field; keep it inside the card download.
            if d[pos + 1] != 0x06 and _valid_chain_from(d, pos, n, memo, validation_depth + 1, ctx):
                result = pos
                break
        pos += 1
    markers[p] = result
    return result


def _valid_chain_from(d, pos, n, memo, validation_depth=0, ctx=None):
    """Return True if bytes from *pos* to EOF form a valid TREP sequence.

    This uses explicit DFS frames rather than Python recursion: a card-download
    marker can be followed by thousands of valid short TREP messages. Nested
    variable-length card-download checks are capped separately.
    """
    if ctx is not None:
        memo = ctx["memo"]
    else:
        ctx = {"memo": memo, "markers": {}}
    if validation_depth > MAX_CHAIN_VALIDATION_DEPTH:
        _log.debug("G1 TREP chain validation depth exceeded at 0x%X", pos)
        return False
    if pos == n:
        return True
    if pos in memo:
        return memo[pos]

    stack = [(pos, None)]
    while stack:
        current, candidate_ends = stack[-1]
        if current == n:
            memo[current] = True
            stack.pop()
            continue
        if current in memo:
            stack.pop()
            continue

        if candidate_ends is None:
            if not _is_marker(d, current):
                memo[current] = False
                stack.pop()
                continue
            trep = d[current + 1]
            body_start = current + 2
            if trep == 0x06:
                body_len = _next_valid_marker(d, body_start, n, validation_depth + 1, ctx) - body_start
            else:
                body_len = _BODY_LEN_FNS[trep](d, body_start, n)
            if body_len is None:
                memo[current] = False
                stack.pop()
                continue
            body_end = body_start + body_len
            if body_end > n:
                memo[current] = False
                stack.pop()
                continue
            candidate_ends = []
            sig_end = body_end + RSA_SIGNATURE_LEN
            if sig_end == n or _is_marker(d, sig_end):
                candidate_ends.append(sig_end)
            if body_end == n or _is_marker(d, body_end):
                candidate_ends.append(body_end)
            stack[-1] = (current, candidate_ends)

        if any(end == n or memo.get(end) is True for end in candidate_ends):
            memo[current] = True
            stack.pop()
            continue
        pending = next((end for end in candidate_ends if end not in memo), None)
        if pending is not None:
            stack.append((pending, None))
            continue
        memo[current] = False
        stack.pop()

    return memo.get(pos, False)


_BODY_LEN_FNS = {
    0x01: _trep01_body_len,
    0x02: _trep02_body_len,
    0x03: _trep03_body_len,
    0x04: _trep04_body_len,
    0x05: _trep05_body_len,
    0x06: _trep06_body_len,
    0x11: _trep11_body_len,
    0x14: _trep14_body_len,
}


def _is_marker(data, pos):
    return pos + 2 <= len(data) and data[pos] == 0x76 and data[pos + 1] in TREP_NAMES


def _marker_in(data, start):
    """True when a ``0x76 TREP`` marker exists at or after ``start``.

    Used to tell a harmless trailing pad/trailer (no further message) from a
    real mis-measured boundary (a message still follows)."""
    if start >= len(data):
        return False
    return any(_is_marker(data, i) for i in range(start, len(data) - 1))


def iter_g1_vu_messages(data):
    """Walk the G1 VU message stream from offset 0.

    Yields dicts ``{pos, trep, body_start, body_end, sig_len, end}``. The walk
    is self-checking: each message must end exactly on the next ``0x76 TREP``
    marker or on EOF (with or without the 128-byte RSA signature), otherwise
    iteration stops. Callers detect a partial walk by comparing the last
    ``end`` with ``len(data)``.
    """
    n = len(data)
    pos = 0
    ctx = _new_walk_ctx()
    while pos < n:
        if not _is_marker(data, pos):
            return
        trep = data[pos + 1]
        body_start = pos + 2
        if trep == 0x06:
            # A card image relayed inside the VU transfer (DDP_049): the region is
            # a complete card STAP stream, so its extent comes from the card's own
            # length fields — not from a boundary search — and it carries no VU
            # TREP signature (the card has its own EF signatures).
            extent, elements = card_image_extent(memoryview(data)[body_start:])
            if not (elements and (body_start + extent == n
                                  or _is_marker(data, body_start + extent))):
                # The STAP walk can run past the card into the following VU
                # section when the card's last element is followed by bytes that
                # still look like an element. The next valid TREP marker is the
                # bound then; the region is accepted only when the bytes up to it
                # are a complete card.
                boundary = _next_valid_marker(data, body_start, n, ctx=ctx)
                if boundary - body_start > 0:
                    inner, elements = card_image_extent(
                        memoryview(data)[body_start:boundary])
                    if elements and inner == boundary - body_start:
                        extent = inner
            if elements and (body_start + extent == n
                             or _is_marker(data, body_start + extent)):
                end = body_start + extent
                yield {"pos": pos, "trep": trep, "body_start": body_start,
                       "body_end": end, "sig_len": 0, "end": end,
                       "card_region": True, "card_bytes": extent,
                       "card_elements": elements}
                pos = end
                continue
        card_incomplete = False
        if trep == 0x06:
            # CardDownload length is determined by the boundary search; share
            # the walk caches so each position is resolved once (see
            # _next_valid_marker).
            body_len = _next_valid_marker(data, body_start, n, ctx=ctx) - body_start
            # The header promises a card image; when the bytes are not a complete
            # card stream, that is an INTEGRITY finding (the region does not
            # close), reported instead of passing as a legacy card body.
            inner, elements = card_image_extent(
                memoryview(data)[body_start:body_start + body_len])
            card_incomplete = not (elements and inner == body_len)
        else:
            body_len = _BODY_LEN_FNS[trep](data, body_start, n)
        if body_len is None:
            return
        body_end = body_start + body_len

        # The signature is present when the next marker (or EOF) sits exactly
        # 128 bytes after the body; absent when it sits right at the body end.
        # A trailing pad/trailer after the last signed message (a stray byte, or
        # any bytes that do not start a further message) must not discard the
        # whole block: accept it when no TREP marker follows the signature.
        sig_at = body_end + RSA_SIGNATURE_LEN
        if sig_at == n or _is_marker(data, sig_at):
            sig_len = RSA_SIGNATURE_LEN
        elif body_end == n or _is_marker(data, body_end):
            sig_len = 0
        elif not _marker_in(data, sig_at):
            sig_len = RSA_SIGNATURE_LEN if sig_at <= n else 0
        else:
            return

        end = body_end + sig_len
        message = {"pos": pos, "trep": trep, "body_start": body_start,
                   "body_end": body_end, "sig_len": sig_len, "end": end}
        if card_incomplete:
            message["card_region_incomplete"] = True
        yield message
        pos = end


def walk_g1_vu(data, results):
    """Semantic dispatch of a G1 VU download via the deterministic walk.

    Each message body is handed once, at its exact offset, to the existing
    structured TREP parsers (instead of the legacy byte-by-byte 0x76 scan).
    Returns ``(messages, complete)`` where *complete* is True when the walk
    covered the whole file.
    """
    data = bytes(data)
    messages = list(iter_g1_vu_messages(data))
    trailing = len(data) - messages[-1]["end"] if messages else 0
    signature_bytes = sum(m["sig_len"] for m in messages)
    # Complete when the walk consumed every byte, or when the only remainder is
    # padding: a run of 0x00/0xFF fill or a bare marker prefix that no message
    # can start. A remainder that is neither is a *short signature block* (a cut
    # RSA signature leaves 1..127 arbitrary bytes after the body) or trailing
    # junk: both are INTEGRITY findings, not a decoding failure, and they must not
    # let the download claim a complete walk.
    pad = data[messages[-1]["end"]:] if messages else b""
    # Only 0x00/0xFF fill is padding (Appendix 1 §2: unused content is filled with
    # FF, and erased space is zeroed). A lone 0x76 is the first byte of a truncated
    # section marker, not fill: it makes the walk incomplete, and the byte is still
    # reported in metadata.vu_integrity.
    padding_only = (not pad) or all(b in (0x00, 0xFF) for b in pad)
    complete = bool(messages) and not _marker_in(data, messages[-1]["end"]) and padding_only
    results["_g1_walk_signature_bytes"] = signature_bytes
    if trailing:
        results["_g1_walk_trailing_bytes"] = trailing

    integrity = []
    if messages and trailing:
        last = messages[-1]
        if last["sig_len"] == 0 and trailing < RSA_SIGNATURE_LEN:
            # The body is complete and decodable; only the signature block is
            # shorter than the 128 bytes the generation-1 transfer defines.
            integrity.append({"trep": f"0x{last['trep']:02X}",
                              "status": "signature_truncated",
                              "missing_bytes": RSA_SIGNATURE_LEN - trailing,
                              "trailing_bytes": trailing})
        else:
            integrity.append({"trep": f"0x{last['trep']:02X}",
                              "status": "trailing_bytes",
                              "missing_bytes": 0,
                              "trailing_bytes": trailing})
    def _dispatch_trep02(body, res, message_offset=None):
        # The walk yields exact bodies, so try the deterministic layout first:
        # the heuristic wrapper rejects short bodies (< 50 bytes) that are
        # legitimate card-not-inserted days (18-byte TREP 02 messages).
        if not _parse_trep_02_g1_structured(body, res,
                                            message_offset=message_offset):
            _parse_trep_02_activities(body, res)

    # Each handler receives the message offset: a stored record's identity is its
    # position in the download, never a subset of its decoded fields.
    dispatch = {
        0x01: parse_g1_vu_overview,
        0x02: _dispatch_trep02,
        0x03: _parse_trep_03_events_faults,
        0x04: _parse_trep_04_speed,
        0x05: _parse_trep_05_technical,
        0x06: _parse_trep_06_card_download,
        0x11: _parse_sensor_download,
    }
    dispatch_failed = False
    card_regions = []
    for msg in messages:
        body = data[msg["body_start"]:msg["body_end"]]
        if msg.get("card_region_incomplete"):
            card_regions.append({
                "offset": msg["body_start"],
                "bytes": msg["body_end"] - msg["body_start"],
                "tlvs": 0,
                "tlv_complete": False,
                "boundary": "resynchronised (card EF stream does not close)",
                "delegated": False,
            })
            integrity.append({"trep": "0x06", "status": "card_download_incomplete",
                              "missing_bytes": 0,
                              "trailing_bytes": msg["body_end"] - msg["body_start"]})
        if msg.get("card_region"):
            # The bytes are a card image: recorded here and handed to the plain
            # card pipeline by the engine. They are not VU TREP payload, so they
            # take no part in the VU signature accounting.
            card_regions.append({
                "offset": msg["body_start"],
                "bytes": msg["card_bytes"],
                "tlvs": msg["card_elements"],
                "tlv_complete": True,
                "boundary": "STAP/EF framing",
                "delegated": False,
            })
            continue
        handler = dispatch.get(msg["trep"])
        if handler is None:
            continue
        try:
            if msg["trep"] in (0x01, 0x02, 0x03, 0x05):
                handler(body, results, message_offset=msg["pos"])
            else:
                handler(body, results)
        except Exception as exc:  # a decoder bug must not break the walk
            dispatch_failed = True
            # WARNING, not DEBUG: this is a swallowed decode error whose only
            # other trace is the fallback the caller now declares.
            _log.warning("G1 VU TREP %02X dispatch failed at 0x%X: %s",
                         msg["trep"], msg["pos"], exc)

    if integrity:
        # Model-only: which section's byte run does not match the normative
        # length, and by how much (a short signature block, trailing junk, a card
        # region that does not close). Integrity is not decodability.
        results.setdefault("metadata", {}).setdefault(
            "vu_integrity", []).extend(integrity)
    if card_regions:
        results.setdefault("metadata", {}).setdefault(
            "vu_card_download_sections", []).extend(card_regions)
    complete = complete and not dispatch_failed
    # Decodability is a separate question from integrity: every message the walk
    # yielded was decoded by its TREP parser unless the walk stopped on a marker
    # it could not parse (or a parser raised). A short signature block or trailing
    # junk leaves this True — the records are there, only the integrity report
    # says the block is incomplete.
    undecodable_tail = bool(messages) and _marker_in(data, messages[-1]["end"])
    results["_g1_walk_decoded_all"] = bool(messages) and not undecodable_tail and not dispatch_failed
    _log.debug("G1 VU walk: %d messages, complete=%s, decoded_all=%s",
               len(messages), complete, results["_g1_walk_decoded_all"])
    return messages, complete
