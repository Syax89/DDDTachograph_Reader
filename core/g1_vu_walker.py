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

from core.logger import get_logger

_log = get_logger(__name__)

RSA_SIGNATURE_LEN = 128

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
    pos = p
    while pos < n - 1:
        if d[pos] == 0x76 and d[pos + 1] == 0x14:
            return pos - p
        pos += 1
    return n - p


def _trep14_body_len(d, p, n):
    return 2 if p + 2 <= n else None


def _next_valid_marker(d, p, n):
    """Return the next marker that starts a valid TREP chain, or EOF.

    TREP 06 CardDownload has no explicit length. Card EF payloads can contain
    byte pairs such as ``76 01`` that look like message markers, so a raw scan
    would split the card data in the middle. Accept a candidate boundary only
    when the remaining bytes form a valid Annex 1B TREP sequence.
    """
    pos = p
    memo = {}
    while pos < n - 1:
        if d[pos] == 0x76 and d[pos + 1] in TREP_NAMES:
            # A nested TREP 06 candidate cannot be disambiguated from card EF
            # payload without a length field; keep it inside the card download.
            if d[pos + 1] != 0x06 and _valid_chain_from(d, pos, n, memo):
                return pos
        pos += 1
    return n


def _valid_chain_from(d, pos, n, memo):
    """Return True if bytes from *pos* to EOF form a valid TREP sequence."""
    if pos == n:
        return True
    cached = memo.get(pos)
    if cached is not None:
        return cached
    if not _is_marker(d, pos):
        memo[pos] = False
        return False

    trep = d[pos + 1]
    body_start = pos + 2
    body_len = _BODY_LEN_FNS[trep](d, body_start, n)
    if body_len is None:
        memo[pos] = False
        return False
    body_end = body_start + body_len
    if body_end > n:
        memo[pos] = False
        return False

    candidate_ends = []
    sig_end = body_end + RSA_SIGNATURE_LEN
    if sig_end == n or _is_marker(d, sig_end):
        candidate_ends.append(sig_end)
    if body_end == n or _is_marker(d, body_end):
        candidate_ends.append(body_end)

    for end in candidate_ends:
        if end > pos and _valid_chain_from(d, end, n, memo):
            memo[pos] = True
            return True
    memo[pos] = False
    return False


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
    while pos < n:
        if not _is_marker(data, pos):
            return
        trep = data[pos + 1]
        body_start = pos + 2
        body_len = _BODY_LEN_FNS[trep](data, body_start, n)
        if body_len is None:
            return
        body_end = body_start + body_len

        # The signature is present when the next marker (or EOF) sits exactly
        # 128 bytes after the body; absent when it sits right at the body end.
        if body_end + RSA_SIGNATURE_LEN == n or _is_marker(data, body_end + RSA_SIGNATURE_LEN):
            sig_len = RSA_SIGNATURE_LEN
        elif body_end == n or _is_marker(data, body_end):
            sig_len = 0
        else:
            return

        end = body_end + sig_len
        yield {"pos": pos, "trep": trep, "body_start": body_start,
               "body_end": body_end, "sig_len": sig_len, "end": end}
        pos = end


def walk_g1_vu(data, results):
    """Semantic dispatch of a G1 VU download via the deterministic walk.

    Each message body is handed once, at its exact offset, to the existing
    structured TREP parsers (instead of the legacy byte-by-byte 0x76 scan).
    Returns ``(messages, complete)`` where *complete* is True when the walk
    covered the whole file.
    """
    from core import decoders

    data = bytes(data)
    messages = list(iter_g1_vu_messages(data))
    complete = bool(messages) and messages[-1]["end"] == len(data)

    def _dispatch_trep02(body, res):
        # The walk yields exact bodies, so try the deterministic layout first:
        # the heuristic wrapper rejects short bodies (< 50 bytes) that are
        # legitimate card-not-inserted days (18-byte TREP 02 messages).
        if not decoders._parse_trep_02_g1_structured(body, res):
            decoders._parse_trep_02_activities(body, res)

    dispatch = {
        0x01: decoders.parse_g1_vu_overview,
        0x02: _dispatch_trep02,
        0x03: decoders._parse_trep_03_events_faults,
        0x04: decoders._parse_trep_04_speed,
        0x05: decoders._parse_trep_05_technical,
        0x06: decoders._parse_trep_06_card_download,
        0x11: decoders._parse_sensor_download,
    }
    for msg in messages:
        body = data[msg["body_start"]:msg["body_end"]]
        handler = dispatch.get(msg["trep"])
        if handler is None:
            continue
        try:
            handler(body, results)
        except Exception as exc:  # a decoder bug must not break the walk
            _log.debug("G1 VU TREP %02X dispatch failed at 0x%X: %s",
                       msg["trep"], msg["pos"], exc)

    _log.debug("G1 VU walk: %d messages, complete=%s", len(messages), complete)
    return messages, complete
