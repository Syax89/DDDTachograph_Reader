"""Unit tests for plausibility validators (core.decoders.validators)."""
from core.decoders import validators as v


def test_speed_bounds():
    assert v.is_plausible_speed(0)
    assert v.is_plausible_speed(90)
    assert v.is_plausible_speed(250)
    assert not v.is_plausible_speed(251)
    assert not v.is_plausible_speed(25284)
    assert not v.is_plausible_speed(-1)
    assert not v.is_plausible_speed(None)


def test_timestamp_bounds():
    assert v.is_plausible_timestamp(1_600_000_000)      # 2020
    assert not v.is_plausible_timestamp(0)
    assert not v.is_plausible_timestamp(5_000_000_000)   # >2100
    assert not v.is_plausible_timestamp(None)


def test_odometer_bounds():
    assert v.is_plausible_odometer(0)
    assert v.is_plausible_odometer(1_000_000)
    assert not v.is_plausible_odometer(-5)
    assert not v.is_plausible_odometer(50_000_000)


def test_printable_text_rejects_binary_garbage():
    assert v.is_printable_text("I-00000142371003")
    assert v.is_printable_text("")
    assert not v.is_printable_text("\x125\x1a7\x129\x02B")
    assert not v.is_printable_text(None)


def test_plausible_sensor_info():
    good = {"param_speed_max_kmh": 16, "param_speed_avg_kmh": 22,
            "sensor_approval": "I-00000142371003"}
    bad = {"param_speed_max_kmh": 25284, "param_speed_avg_kmh": 726,
           "sensor_approval": "\x125\x1a7"}
    assert v.is_plausible_sensor_info(good)
    assert not v.is_plausible_sensor_info(bad)
    assert not v.is_plausible_sensor_info(None)


def test_plausible_count():
    assert v.is_plausible_count(0, 100)
    assert v.is_plausible_count(100, 100)
    assert not v.is_plausible_count(101, 100)
    assert not v.is_plausible_count(-1, 100)
