"""Policy tests for VU download signature completeness."""
from core.crypto import vu_signature


def test_missing_g2_trep_signature_rejects_entire_download(monkeypatch):
    # The Overview supplies the certificates and a structurally valid signature.
    # The following Activities section contains data but no SignatureRecord.
    sections = [
        {
            "marker": 0,
            "trep": 0x21,
            "records": [
                (2, 0x04, 1, 1, 8),
                (8, 0x0F, 1, 1, 14),
                (14, 0x08, 64, 1, 83),
            ],
        },
        {
            "marker": 83,
            "trep": 0x22,
            "records": [(85, 0x01, 1, 1, 91)],
        },
    ]
    data = bytearray(91)
    data[7] = 0x04
    data[13] = 0x0F

    monkeypatch.setattr(vu_signature, "iter_vu_sections", lambda _data: iter(sections))
    monkeypatch.setattr(vu_signature, "parse_cvc", lambda _raw: {"car": "ca"})
    monkeypatch.setattr(vu_signature, "cvc_public_key", lambda _cvc: (object(), object()))
    monkeypatch.setattr(vu_signature, "cvc_temporal_status", lambda *_args: {})
    monkeypatch.setattr(vu_signature, "verify_cvc_chain_link", lambda *_args: True)

    report = vu_signature.verify_vu_download(bytes(data))

    assert report["all_treps_valid"] is False
    assert report["treps"][-1] == {
        "trep": "0x22",
        "section": "Activities",
        "signature_valid": False,
        "reason": "signature record missing",
    }


def test_trep_signature_must_be_final_record_array(monkeypatch):
    section = {
        "marker": 0,
        "trep": 0x21,
        "records": [
            (2, 0x04, 1, 1, 8),
            (8, 0x0F, 1, 1, 14),
            (14, 0x01, 1, 1, 20),
            (20, 0x08, 64, 1, 89),
        ],
    }
    data = bytearray(95)
    data[7] = 0x04
    data[13] = 0x0F

    monkeypatch.setattr(vu_signature, "iter_vu_sections", lambda _data: iter([section]))
    monkeypatch.setattr(vu_signature, "parse_cvc", lambda _raw: {"car": "ca"})
    monkeypatch.setattr(vu_signature, "cvc_public_key", lambda _cvc: (object(), object()))
    monkeypatch.setattr(vu_signature, "cvc_temporal_status", lambda *_args: {})
    monkeypatch.setattr(vu_signature, "verify_cvc_chain_link", lambda *_args: True)
    monkeypatch.setattr(vu_signature, "_verify_ecdsa", lambda *_args: True)

    assert vu_signature.verify_vu_download(bytes(data))["all_treps_valid"] is True

    section["records"].append((89, 0x01, 1, 1, 95))
    report = vu_signature.verify_vu_download(bytes(data))

    assert report["all_treps_valid"] is False
    assert report["treps"] == [{
        "trep": "0x21",
        "section": "Overview",
        "signature_valid": False,
        "reason": "signature record is not final",
    }]
