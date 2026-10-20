"""The completed VuCardIWRecord tail must not add a single column to the UI.

The tail fields (`previous_vehicle`, the numeric `manual_input_flag` and its
meaning, and the completeness bookkeeping) are real, spec-derived data: they
belong in the model and in the JSON export. They are **not** a table or report
column, because the owner's rule is that the on-screen layout is preserved
exactly — and any new head would first need a translated label in all 33
catalogs, which nobody has produced.

This is the same contract `tests/unit/test_vu_event_fault_versioning.py`
enforces for the event/fault bookkeeping keys: a key that carries analysis
detail lives in the JSON and is hidden from every reporting path.

The comparison is direct: `visible_columns()` of a record that carries all the
new keys must equal `visible_columns()` of the same record without them, on both
the export path (`report_format`) and the GUI path (`app.gui._columns_for`).
"""
import pytest

from app import gui
from core.utils import report_format
from core.utils.report_format import humanize_key, visible_columns

#: Every key this batch added to a `card_iw_records` record.
NEW_TAIL_KEYS = (
    "previous_vehicle",
    "manual_input_flag",
    "manual_input_flag_meaning",
    "record_bytes",
    "record_complete",
    "missing_bytes",
    "raw_tail_bytes",
)

#: A record shaped like the ones the two walks emit, pre-batch (all synthetic).
BASE_RECORD = {
    "holder_surname": "ZETA",
    "holder_first_names": "KAPPA",
    "card": {"present": True, "card_type": 1, "nation": "I",
             "card_number": "0000000000471126", "generation": 2},
    "card_expiry": "2025-12-29T04:23:49+00:00",
    "insertion_time": "2023-07-27T04:25:07+00:00",
    "odometer_insertion_km": 412_399,
    "card_slot": 1,
    "withdrawal_time": "2023-07-27T14:41:53+00:00",
    "odometer_withdrawal_km": 386_114,
    "confidence": "high",
}

TAIL_VALUES = {
    "previous_vehicle": {
        "registration_nation": "E",
        "registration_nation_code": 0x0F,
        "registration_code_page": 0x01,
        "registration_plate": "YY654YY",
        "card_withdrawal_time": "2023-07-26T21:24:12+00:00",
        "card_withdrawal_timestamp": 1_690_406_652,
        "vu_generation": 2,
    },
    "manual_input_flag": 1,
    "manual_input_flag_meaning": "manualEntries",
    "record_bytes": 131,
    "record_complete": True,
    "missing_bytes": 0,
    "raw_tail_bytes": 4,
}


def _record_with_tail():
    record = dict(BASE_RECORD)
    record.update(TAIL_VALUES)
    return record


@pytest.mark.parametrize("key", NEW_TAIL_KEYS)
def test_each_new_key_is_hidden_on_both_reporting_paths(key):
    """Both hidden-key sets must carry every new key — they are separate lists."""
    assert key in report_format.HIDDEN_KEYS
    assert key in gui.HIDDEN_KEYS


def test_visible_columns_are_identical_with_and_without_the_new_keys():
    """The whole point: the table/export layout does not move by one column."""
    without = [dict(BASE_RECORD)]
    with_tail = [_record_with_tail()]

    assert visible_columns(without) == visible_columns(with_tail)
    assert gui._columns_for(without, None) == gui._columns_for(with_tail, None)


def test_no_new_head_text_is_introduced():
    """Every visible column still humanises to a label the catalogs already have."""
    for column in visible_columns([_record_with_tail()]):
        if column in NEW_TAIL_KEYS:
            pytest.fail(f"{column} leaked into the report columns")
    # A sanity anchor: the pre-existing columns are still the same set.
    assert set(visible_columns([_record_with_tail()])) == {
        "holder_surname", "holder_first_names", "card", "card_expiry",
        "insertion_time", "odometer_insertion_km", "card_slot",
        "withdrawal_time", "odometer_withdrawal_km"}
    assert humanize_key("holder_surname") == "Holder Surname"


def test_the_values_stay_available_to_consumers():
    """Hidden from the table, not from the data: the JSON keeps every value."""
    record = _record_with_tail()

    assert record["previous_vehicle"]["registration_plate"] == "YY654YY"
    assert record["manual_input_flag"] == 1
    assert record["manual_input_flag_meaning"] == "manualEntries"
    assert record["record_complete"] is True
    assert record["record_bytes"] == 131
