"""A decoder that raises must not make a field vanish silently.

``DeterministicParser`` catches the exception so the structural walk carries
on; the warning it logs is tallied by the shared failure counter, so it must
reach ``metadata.decoder_failures`` and the CLI summary must warn about it.
"""
import dataclasses

from app.cli import print_summary
from app.engine import TachoParser
from core.registry.registry import DecoderRegistry
from tests.integration import generate_mock_ddd as mock


def _boom(*_args):
    raise RuntimeError("synthetic decoder crash")


def test_decoder_exception_reaches_metadata_and_summary(tmp_path, monkeypatch, capsys):
    path = tmp_path / "mock_g1_card.ddd"
    mock.generate_g1_card(str(path))
    clean = TachoParser(str(path)).parse()["metadata"]
    assert clean.get("decoder_failure_count", 0) == 0

    real_get = DecoderRegistry.get_decoder

    def failing_get(self, tag, *args, **kwargs):
        dec = real_get(self, tag, *args, **kwargs)
        if tag == 0x0521 and dec is not None and dec.decoder_fn:
            return dataclasses.replace(dec, decoder_fn=_boom)
        return dec

    monkeypatch.setattr(DecoderRegistry, "get_decoder", failing_get)
    result = TachoParser(str(path)).parse()
    meta = result["metadata"]
    assert meta["decoder_failure_count"] >= 1
    assert any("0x0521" in msg and "dispatch failed" in msg
               for msg in meta["decoder_failures"])
    # The rest of the file is still decoded.
    assert result["activities"]

    print_summary(result)
    assert "decoder failure(s) during parsing" in capsys.readouterr().out


def test_clean_summary_has_no_decoder_warning(capsys):
    print_summary({"metadata": {"integrity_check": "Verified", "decoder_failure_count": 0}})
    assert "decoder failure" not in capsys.readouterr().out
