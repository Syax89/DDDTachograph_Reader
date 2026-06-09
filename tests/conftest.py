import pytest
from core.decoder_registry import DecoderRegistry


@pytest.fixture(autouse=True)
def reset_registry():
    DecoderRegistry.reset_instance()
    yield
    DecoderRegistry.reset_instance()
