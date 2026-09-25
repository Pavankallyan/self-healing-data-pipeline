"""Transform: schema-drift handling + cleaning of valid rows.

This is the "self-healing" part. Instead of crashing on unexpected input:

  * known column renames are resolved through an alias map
    (temperature_c -> temp_c) and logged as drift events;
  * brand-new columns not in the schema are logged and dropped rather than
    breaking the load;
  * valid rows are type-coerced, deduplicated (safety net), and enriched
    with a derived temp_f column.
"""

from typing import Any

import pandas as pd


def apply_aliases(df: pd.DataFrame, aliases: dict[str, str]) -> tuple[pd.DataFrame, list[dict]]:
    """Rename known drifted columns to their canonical names.

    Returns (renamed_frame, drift_events). Never raises for a missing alias.
    """
    events: list[dict] = []
    df = df.copy()
    for alias, canonical in aliases.items():
        if alias in df.columns and canonical not in df.columns:
            df = df.rename(columns={alias: canonical})
            events.append(
                {
                    "type": "column_renamed",
                    "detected": alias,
                    "canonical": canonical,
                    "action": "alias_applied",
                }
            )
        elif alias in df.columns and canonical in df.columns:
            events.append(
                {
                    "type": "column_renamed",
                    "detected": alias,
                    "canonical": canonical,
                    "action": "both_present_kept_canonical",
                }
            )
    return df, events


def drop_unexpected(df: pd.DataFrame, schema: dict[str, Any]) -> tuple[pd.DataFrame, list[dict]]:
    """Drop columns not present in the schema, logging each as a drift event."""
    expected = set(schema["columns"])
    unexpected = [c for c in df.columns if c not in expected]
    events = [
        {"type": "unexpected_column", "column": c, "action": "dropped"}
        for c in unexpected
    ]
    return df.drop(columns=unexpected), events


def clean(df: pd.DataFrame, schema: dict[str, Any]) -> pd.DataFrame:
    """Coerce types, dedupe, and add derived columns to validated rows."""
    df = df.copy()
    for col, spec in schema["columns"].items():
        if col not in df.columns:
            continue
        if spec["type"] == "float":
            df[col] = pd.to_numeric(df[col], errors="coerce")
        elif spec["type"] == "datetime":
            df[col] = pd.to_datetime(df[col], errors="coerce")

    df = df.drop_duplicates().reset_index(drop=True)  # safety net
    df["temp_f"] = (df["temp_c"] * 9 / 5 + 32).round(2)
    df = df.sort_values("timestamp").reset_index(drop=True)

    ordered = list(schema["columns"]) + ["temp_f"]
    return df[[c for c in ordered if c in df.columns]]
