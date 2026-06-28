from core.g1_vu_walker import iter_g1_vu_messages


def test_trep06_ignores_false_marker_inside_card_payload():
    data = b"\x76\x06" + b"card-payload" + b"\x76\x01" + b"not-a-trep01"

    messages = list(iter_g1_vu_messages(data))

    assert len(messages) == 1
    assert messages[0]["trep"] == 0x06
    assert messages[0]["body_end"] == len(data)
    assert messages[0]["end"] == len(data)


def test_trep06_stops_at_marker_that_starts_valid_chain():
    # TREP 04 with zero speed blocks has a deterministic 2-byte body.
    data = b"\x76\x06" + b"card-payload" + b"\x76\x04\x00\x00"

    messages = list(iter_g1_vu_messages(data))

    assert [message["trep"] for message in messages] == [0x06, 0x04]
    assert messages[0]["body_end"] == len(data) - 4
    assert messages[1]["end"] == len(data)


def test_sensor_special_section_walks_to_trailer():
    # Some sensor/special G1 downloads contain a normal signed overview,
    # followed by an opaque 0x7611 section and a 0x7614 trailer.
    overview_body = b"\x00" * 493
    signature = b"\xAA" * 128
    special_body = b"sensor-data\x76\x01-not-a-real-marker"
    trailer_body = b"\x00\x00"
    data = (
        b"\x76\x01" + overview_body + signature
        + b"\x76\x11" + special_body
        + b"\x76\x14" + trailer_body
    )

    messages = list(iter_g1_vu_messages(data))

    assert [message["trep"] for message in messages] == [0x01, 0x11, 0x14]
    assert messages[0]["sig_len"] == 128
    assert messages[1]["body_end"] == len(data) - 4
    assert messages[2]["end"] == len(data)
