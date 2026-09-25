"""Pipeline orchestrator: ingest -> drift-handling -> validate -> quarantine
-> transform -> load (Parquet + SQLite). Prints a run summary and appends
per-day stats to output/alerts.json.
"""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from src import quarantine as quarantine_mod
from src import transform as transform_mod
from src import validate as validate_mod

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
OUTPUT_DIR = BASE_DIR / "output"
ALERTS_PATH = OUTPUT_DIR / "alerts.json"


def _log_drift(events: list[dict]) -> None:
    for e in events:
        if e["type"] == "column_renamed":
            print(f"  [drift] column renamed: {e['detected']} -> {e['canonical']} ({e['action']})")
        elif e["type"] == "unexpected_column":
            print(f"  [drift] unexpected column: {e['column']} ({e['action']})")


def run(day: str) -> dict:
    print(f"=== self-healing-data-pipeline run: {day} ===")
    schema = validate_mod.load_schema()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Ingest
    raw_path = DATA_DIR / f"{day}.csv"
    df_raw = pd.read_csv(raw_path)
    rows_in = len(df_raw)
    print(f"[ingest] read {rows_in} rows from {raw_path.name}")

    # 2. Self-healing: resolve schema drift via alias map, drop unknown cols
    df, alias_events = transform_mod.apply_aliases(df_raw, schema.get("aliases", {}))
    df, unexpected_events = transform_mod.drop_unexpected(df, schema)
    drift_events = alias_events + unexpected_events
    if drift_events:
        print(f"[drift] detected {len(drift_events)} schema-drift event(s):")
        _log_drift(drift_events)
    else:
        print("[drift] none detected")

    # 3. Validate (per-row pass/fail with human-readable reasons)
    result = validate_mod.validate(df, schema)
    valid_mask = result["valid_mask"]
    failures = result["failures"]
    print(f"[validate] {int(valid_mask.sum())} valid, {len(failures)} failed")

    # 4. Quarantine failures with reasons attached
    qstats = quarantine_mod.write_quarantine(failures, OUTPUT_DIR / f"quarantine_{day}.csv")
    print(f"[quarantine] wrote {qstats['rows_quarantined']} rows -> quarantine_{day}.csv")

    # 5. Transform valid rows
    clean = transform_mod.clean(df.loc[valid_mask], schema)
    rows_out = len(clean)
    print(f"[transform] {rows_out} clean rows (added temp_f, coerced types, deduped)")

    # 6. Load: Parquet + SQLite
    parquet_path = OUTPUT_DIR / f"clean_{day}.parquet"
    clean.to_parquet(parquet_path, index=False)
    db_path = OUTPUT_DIR / "telemetry.db"
    with sqlite3.connect(db_path) as conn:
        clean.to_sql(f"telemetry_{day}", conn, if_exists="replace", index=False)
    print(f"[load] -> {parquet_path.name} and telemetry.db:telemetry_{day}")

    # 7. Alerts: merge this day's stats into alerts.json (other days preserved)
    summary = {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "rows_in": rows_in,
        "rows_out": rows_out,
        "rows_quarantined": qstats["rows_quarantined"],
        "drift_events": drift_events,
        "drift_event_count": len(drift_events),
        "quarantine_reasons": qstats["reason_counts"],
        "quarantine_file": f"output/quarantine_{day}.csv",
        "outputs": [f"output/clean_{day}.parquet", f"output/telemetry.db:telemetry_{day}"],
    }
    alerts = json.loads(ALERTS_PATH.read_text()) if ALERTS_PATH.exists() else {}
    alerts[day] = summary
    ALERTS_PATH.write_text(json.dumps(alerts, indent=2))
    print(f"[alerts] updated {ALERTS_PATH.name}")

    print(f"=== done: in={rows_in} out={rows_out} quarantined={qstats['rows_quarantined']} "
          f"drift={len(drift_events)} ===\n")
    return summary


if __name__ == "__main__":
    import sys

    day = sys.argv[1] if len(sys.argv) > 1 else "day1"
    run(day)
