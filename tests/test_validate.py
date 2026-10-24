"""Unit tests for src/validate.py (schema + row-level validation) and
src/quarantine.py (failed-row persistence)."""

import pandas as pd
import pytest

from quarantine import write_quarantine
from validate import validate


def test_clean_batch_passes_every_check(clean_df, schema):
    result = validate(clean_df, schema)
    assert result["valid_mask"].all()
    assert result["failures"].empty
    assert result["reasons"] == {}
    assert result["schema_report"] == {"missing_columns": [], "unexpected_columns": []}


def test_missing_column_flags_every_row(clean_df, schema):
    df = clean_df.drop(columns=["humidity"])
    result = validate(df, schema)
    assert not result["valid_mask"].any()
    assert result["schema_report"]["missing_columns"] == ["humidity"]
    assert result["reasons"]["missing_column:humidity"] == 2
    assert "missing_column:humidity" in result["failures"]["failure_reason"].iloc[0]


def test_unexpected_column_reported_but_rows_stay_valid(clean_df, schema):
    df = clean_df.copy()
    df["firmware"] = "1.2.3"
    result = validate(df, schema)
    assert result["valid_mask"].all()
    assert result["schema_report"]["unexpected_columns"] == ["firmware"]


def test_bad_type_float_value(clean_df, schema):
    df = clean_df.copy()
    df.loc[1, "temp_c"] = "warm"
    result = validate(df, schema)
    assert result["valid_mask"].tolist() == [True, False]
    assert result["failures"]["failure_reason"].iloc[0].startswith("bad_type:temp_c")


def test_out_of_range_float_value(clean_df, schema):
    df = clean_df.copy()
    df.loc[0, "battery_v"] = 4.9  # above the 4.2 max
    result = validate(df, schema)
    assert result["valid_mask"].tolist() == [False, True]
    assert "out_of_range:battery_v" in result["failures"]["failure_reason"].iloc[0]
    assert result["reasons"]["out_of_range:battery_v"] == 1


def test_range_boundaries_are_inclusive(clean_df, schema):
    df = clean_df.copy()
    df.loc[0, "humidity"] = 100.0
    df.loc[1, "humidity"] = 0.0
    assert validate(df, schema)["valid_mask"].all()


def test_null_required_string_and_float(clean_df, schema):
    df = clean_df.copy()
    df.loc[0, "device_id"] = None
    df.loc[1, "temp_c"] = None
    result = validate(df, schema)
    assert result["valid_mask"].tolist() == [False, False]
    reasons = result["failures"]["failure_reason"].tolist()
    assert reasons[0] == "null:device_id"
    assert reasons[1] == "null:temp_c"


def test_blank_string_counts_as_null(clean_df, schema):
    df = clean_df.copy()
    df.loc[0, "device_id"] = "   "
    result = validate(df, schema)
    assert result["valid_mask"].tolist() == [False, True]
    assert result["failures"]["failure_reason"].iloc[0] == "null:device_id"


def test_invalid_categorical_value(clean_df, schema):
    df = clean_df.copy()
    df.loc[1, "status"] = "sleeping"
    result = validate(df, schema)
    assert result["valid_mask"].tolist() == [True, False]
    assert "invalid_value:status" in result["failures"]["failure_reason"].iloc[0]


def test_bad_datetime_value(clean_df, schema):
    df = clean_df.copy()
    df.loc[0, "timestamp"] = "not-a-date"
    result = validate(df, schema)
    assert result["valid_mask"].tolist() == [False, True]
    assert "bad_type:timestamp" in result["failures"]["failure_reason"].iloc[0]


def test_exact_duplicate_keeps_first_occurrence(clean_df, schema):
    df = pd.concat([clean_df, clean_df.iloc[[0]]], ignore_index=True)
    result = validate(df, schema)
    assert result["valid_mask"].tolist() == [True, True, False]
    assert result["failures"]["failure_reason"].iloc[0] == "duplicate_row"


def test_multiple_reasons_joined_with_semicolon(clean_df, schema):
    df = clean_df.copy()
    df.loc[0, "temp_c"] = 99.9
    df.loc[0, "status"] = "broken"
    result = validate(df, schema)
    reason = result["failures"]["failure_reason"].iloc[0]
    assert "out_of_range:temp_c" in reason
    assert "invalid_value:status" in reason
    assert "; " in reason


def test_reason_counts_collapse_parenthesised_detail(clean_df, schema):
    df = clean_df.copy()
    df.loc[0, "temp_c"] = 99.9
    df.loc[1, "temp_c"] = -99.9
    result = validate(df, schema)
    assert result["reasons"] == {"out_of_range:temp_c": 2}


def test_quarantine_writes_rows_with_reasons(tmp_path, clean_df, schema):
    result = validate(clean_df.assign(status=["online", "broken"]), schema)
    out = tmp_path / "quarantine.csv"
    stats = write_quarantine(result["failures"], out)
    assert stats["rows_quarantined"] == 1
    assert stats["reason_counts"] == {"invalid_value:status": 1}
    saved = pd.read_csv(out)
    assert list(saved.columns)[-1] == "failure_reason"
    assert "invalid_value:status" in saved["failure_reason"].iloc[0]


def test_quarantine_header_only_when_nothing_failed(tmp_path, clean_df, schema):
    result = validate(clean_df, schema)
    out = tmp_path / "empty.csv"
    stats = write_quarantine(result["failures"], out)
    assert stats["rows_quarantined"] == 0
    assert stats["reason_counts"] == {}
    assert out.exists()
    assert pd.read_csv(out).empty


def test_quarantine_adds_failure_reason_column_if_missing(tmp_path, clean_df):
    out = tmp_path / "plain.csv"
    stats = write_quarantine(clean_df.iloc[[0]], out)
    assert stats["rows_quarantined"] == 1
    saved = pd.read_csv(out)
    assert "failure_reason" in saved.columns
    assert pd.isna(saved["failure_reason"].iloc[0])  # blank reason, not a crash
