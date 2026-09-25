"""Synthetic IoT smart-home telemetry generator.

Produces two deterministic batches (seeded RNG) under data/:
  - day1.csv : clean baseline, 1000 rows.
  - day2.csv : same shape but with real-world problems injected:
      * schema drift: temp_c renamed to temperature_c, plus a brand-new
        firmware_v column,
      * corrupt rows: nulls in required fields, out-of-range values,
        wrong types, invalid status values, and exact duplicate rows.

Run:  python src/generate_data.py
"""

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"

N_ROWS = 1000
SEED_DAY1 = 42
SEED_DAY2 = 123

DEVICES = [f"SH-{i:03d}" for i in range(1, 11)]
FIRMWARE_VERSIONS = ["v2.3.1", "v2.4.0"]
STATUSES = ["online", "idle", "offline"]
INVALID_STATUSES = ["ERROR", "maintenance"]


def make_clean(n: int, seed: int, day: str) -> pd.DataFrame:
    """Generate n clean telemetry rows."""
    rng = np.random.default_rng(seed)
    base = pd.Timestamp(f"2026-09-{day} 00:00:00")
    minutes = rng.integers(0, 24 * 60, n)
    return pd.DataFrame(
        {
            "device_id": rng.choice(DEVICES, n),
            "timestamp": [(base + pd.Timedelta(minutes=int(m))).isoformat() for m in minutes],
            "temp_c": np.round(rng.normal(22.0, 3.0, n), 2),
            "humidity": np.round(np.clip(rng.normal(45.0, 8.0, n), 2.0, 98.0), 1),
            "battery_v": np.round(np.clip(rng.normal(3.6, 0.15, n), 3.0, 4.1), 2),
            "status": rng.choice(STATUSES, n),
        }
    )


def inject_problems(df: pd.DataFrame, seed: int) -> tuple[pd.DataFrame, dict]:
    """Inject schema drift + corrupt rows into a clean frame (deterministic).

    Returns the corrupted frame and a log of what was injected.
    """
    rng = np.random.default_rng(seed)
    log: dict[str, int] = {}

    # --- Schema drift: rename a column, add a brand-new one -----------------
    df = df.rename(columns={"temp_c": "temperature_c"})
    df["firmware_v"] = rng.choice(FIRMWARE_VERSIONS, len(df))
    log["column_renamed_temp_c_to_temperature_c"] = 1
    log["new_column_firmware_v"] = 1

    # Columns that will hold deliberately wrong types must be object dtype
    # first, otherwise pandas cannot store strings in a float column.
    df["temperature_c"] = df["temperature_c"].astype(object)
    df["battery_v"] = df["battery_v"].astype(object)

    # --- Pick non-overlapping row indices for each in-place corruption ------
    idx = rng.choice(len(df), size=39, replace=False)
    cursor = 0

    def take(k: int) -> np.ndarray:
        nonlocal cursor
        part = idx[cursor : cursor + k]
        cursor += k
        return part

    # 1. Nulls in required fields (15 rows)
    null_device = take(6)
    null_temp = take(5)
    null_ts = take(4)
    df.loc[null_device, "device_id"] = np.nan
    df.loc[null_temp, "temperature_c"] = np.nan
    df.loc[null_ts, "timestamp"] = np.nan
    log["null_device_id"] = 6
    log["null_temperature_c"] = 5
    log["null_timestamp"] = 4

    # 2. Out-of-range values (10 rows)
    hot = take(4)
    humid = take(3)
    dead_batt = take(3)
    df.loc[hot, "temperature_c"] = 85.0        # max allowed is 60
    df.loc[humid, "humidity"] = 150.0          # max allowed is 100
    df.loc[dead_batt, "battery_v"] = -1.0      # min allowed is 2.5
    log["out_of_range_temperature_c"] = 4
    log["out_of_range_humidity"] = 3
    log["out_of_range_battery_v"] = 3

    # 3. Wrong types (8 rows)
    bad_temp_type = take(4)
    bad_batt_type = take(4)
    df.loc[bad_temp_type, "temperature_c"] = "twenty-two"
    df.loc[bad_batt_type, "battery_v"] = "low"
    log["wrong_type_temperature_c"] = 4
    log["wrong_type_battery_v"] = 4

    # 4. Invalid status values (6 rows)
    bad_status = take(6)
    df.loc[bad_status, "status"] = rng.choice(INVALID_STATUSES, 6)
    log["invalid_status"] = 6

    # --- Exact duplicate rows (10 rows appended) -----------------------------
    clean_sources = np.setdiff1d(np.arange(len(df)), idx)
    dup_sources = rng.choice(clean_sources, size=10, replace=False)
    dupes = df.iloc[dup_sources].copy()
    df = pd.concat([df, dupes], ignore_index=True)
    log["duplicate_rows"] = 10

    return df, log


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate demo telemetry batches.")
    parser.add_argument("--day", choices=["day1", "day2"], default=None,
                        help="Generate only one batch (default: both).")
    args = parser.parse_args()

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    days = [args.day] if args.day else ["day1", "day2"]

    if "day1" in days:
        df1 = make_clean(N_ROWS, SEED_DAY1, "24")
        df1.to_csv(DATA_DIR / "day1.csv", index=False)
        print(f"day1: wrote {len(df1)} clean rows -> {DATA_DIR / 'day1.csv'}")

    if "day2" in days:
        df2, log = inject_problems(make_clean(N_ROWS, SEED_DAY2, "25"), SEED_DAY2 + 999)
        df2.to_csv(DATA_DIR / "day2.csv", index=False)
        print(f"day2: wrote {len(df2)} rows -> {DATA_DIR / 'day2.csv'}")
        print("day2 injected problems:")
        for what, count in log.items():
            print(f"  - {what}: {count}")


if __name__ == "__main__":
    main()
