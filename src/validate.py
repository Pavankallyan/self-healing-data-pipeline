"""Schema + row-level validation for the telemetry pipeline.

Two layers:
  1. Schema validation: missing required columns, unexpected columns,
     per-column dtype coercion checks.
  2. Row-level rule checks: nulls in required fields, out-of-range values,
     invalid categorical values, exact duplicate rows.

Every failed row gets a human-readable reason (possibly several, joined
with "; "). Schema-level problems never crash the run -- they are reported
in the schema report and attached as row reasons where relevant.
"""

import json
from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd

BASE_DIR = Path(__file__).resolve().parent.parent


def load_schema(path: str | Path | None = None) -> dict[str, Any]:
    path = Path(path) if path else BASE_DIR / "config" / "schema.json"
    return json.loads(path.read_text())


def validate(df: pd.DataFrame, schema: dict[str, Any]) -> dict[str, Any]:
    """Validate df against schema.

    Returns:
        valid_mask      bool Series, True for rows that passed every check
        failures        DataFrame of failed rows + 'failure_reason' column
        reasons         dict of individual reason -> count (quarantine stats)
        schema_report   missing / unexpected columns found
    """
    columns = schema["columns"]
    reasons: dict[Any, list[str]] = {i: [] for i in df.index}

    missing_columns = [c for c in columns if c not in df.columns]
    for col in missing_columns:
        for i in df.index:
            reasons[i].append(f"missing_column:{col}")

    for col, spec in columns.items():
        if col not in df.columns:
            continue
        s = df[col]
        dtype = spec["type"]

        if dtype == "float":
            coerced = pd.to_numeric(s, errors="coerce")
            bad_type = coerced.isna() & s.notna()
            for i in s.index[bad_type]:
                reasons[i].append(f"bad_type:{col} (value={s.loc[i]!r})")
            if "min" in spec and "max" in spec:
                out = coerced.notna() & ((coerced < spec["min"]) | (coerced > spec["max"]))
                for i in s.index[out]:
                    reasons[i].append(
                        f"out_of_range:{col} (value={s.loc[i]!r}, "
                        f"allowed {spec['min']}..{spec['max']})"
                    )

        elif dtype == "datetime":
            coerced = pd.to_datetime(s, errors="coerce")
            bad_type = coerced.isna() & s.notna()
            for i in s.index[bad_type]:
                reasons[i].append(f"bad_type:{col} (value={s.loc[i]!r})")

        elif dtype == "string":
            if spec.get("required"):
                nulls = s.isna() | (s.astype(str).str.strip() == "")
                # astype(str) turns NaN into 'nan'; isna() already covers it,
                # the extra clause only catches genuine empty/blank strings.
                nulls = s.isna() | ((s.notna()) & (s.astype(str).str.strip() == ""))
                for i in s.index[nulls]:
                    reasons[i].append(f"null:{col}")
            not_string = s.notna() & ~s.map(lambda v: isinstance(v, str))
            for i in s.index[not_string]:
                reasons[i].append(f"bad_type:{col} (value={s.loc[i]!r})")
            if "allowed" in spec:
                invalid = s.notna() & ~s.isin(spec["allowed"])
                for i in s.index[invalid]:
                    reasons[i].append(
                        f"invalid_value:{col} (value={s.loc[i]!r}, "
                        f"allowed {spec['allowed']})"
                    )

        # generic null check for required non-string fields
        if spec.get("required") and dtype != "string":
            for i in s.index[s.isna()]:
                if not any(r.startswith(f"null:{col}") or r.startswith(f"missing_column:{col}")
                           for r in reasons[i]):
                    reasons[i].append(f"null:{col}")

    # Exact duplicate rows (keep the first occurrence as the valid one)
    check_cols = [c for c in columns if c in df.columns]
    if check_cols:
        dupes = df.duplicated(subset=check_cols, keep="first")
        for i in df.index[dupes]:
            reasons[i].append("duplicate_row")

    valid_mask = pd.Series(
        {i: len(reasons[i]) == 0 for i in df.index}, dtype=bool
    )
    valid_mask.index = df.index

    failures = df.loc[~valid_mask].copy()
    failures["failure_reason"] = ["; ".join(reasons[i]) for i in failures.index]

    counter: Counter = Counter()
    for rs in reasons.values():
        for r in rs:
            # collapse to the reason key (drop the parenthesised detail)
            counter[r.split(" (")[0]] += 1

    return {
        "valid_mask": valid_mask,
        "failures": failures,
        "reasons": dict(counter),
        "schema_report": {
            "missing_columns": missing_columns,
            "unexpected_columns": [c for c in df.columns if c not in columns],
        },
    }
