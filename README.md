# self-healing-data-pipeline

I'm Pavan Kalyan, an MS Data Science student at Wentworth Institute of Technology (Boston) with 3 years of experience as a Software Test Engineer testing IoT devices. This project is a data pipeline that **refuses to silently break**: when the incoming data drifts (renamed columns, brand-new fields) or arrives dirty (nulls, bad types, out-of-range values, duplicates), the pipeline heals what it recognizes, quarantines what it can't trust, and raises an alert — instead of crashing or, worse, loading garbage downstream.

The demo scenario is IoT smart-home telemetry (`device_id`, `timestamp`, `temp_c`, `humidity`, `battery_v`, `status`) — a domain I know well from testing connected devices.

## How it works

```
ingest → handle schema drift → validate → quarantine → transform → load → alert
```

1. **Ingest** — reads the day's CSV batch.
2. **Handle schema drift** — known renames are resolved through an alias map (`temperature_c` → `temp_c`); brand-new columns not in the schema are logged as drift events and dropped. Nothing here raises — drift is *data*, not an exception.
3. **Validate** — two layers: schema checks (missing/unexpected columns, dtype coercion) and row-level rule checks (nulls in required fields, out-of-range values, invalid categoricals, duplicates). Every failed row gets a human-readable reason.
4. **Quarantine** — failed rows are written to `quarantine_<day>.csv` *with the failure reason attached*, plus per-reason counts. Bad data is never silently dropped.
5. **Transform** — valid rows are type-coerced, deduplicated, sorted, and enriched with a derived `temp_f` column.
6. **Load** — clean data lands in **Parquet** (`clean_<day>.parquet`) and **SQLite** (`telemetry.db`, one table per day).
7. **Alert** — run stats (rows in/out/quarantined, drift events, quarantine breakdown) are printed and merged into `output/alerts.json`.

## Demo results (real runs)

I generated two batches with a seeded RNG so the demo is fully reproducible:

- **day1** — 1,000 clean rows (the happy path).
- **day2** — 1,010 rows with injected problems: `temp_c` renamed to `temperature_c`, a new `firmware_v` column, 15 rows with nulls, 10 out-of-range values, 8 wrong-typed values, 6 invalid statuses, and 10 exact duplicates.

| metric | day1 | day2 |
|---|---|---|
| rows in | 1,000 | 1,010 |
| rows out (clean) | 1,000 | 961 |
| rows quarantined | 0 | 49 |
| schema-drift events | 0 | 2 (`temperature_c`→`temp_c` alias applied; `firmware_v` dropped) |

Day-2 quarantine breakdown (sums to 49 — every bad row accounted for):

| reason | count |
|---|---|
| duplicate_row | 10 |
| null:device_id | 6 |
| invalid_value:status | 6 |
| null:temp_c | 5 |
| out_of_range:temp_c | 4 |
| bad_type:temp_c | 4 |
| bad_type:battery_v | 4 |
| null:timestamp | 4 |
| out_of_range:humidity | 3 |
| out_of_range:battery_v | 3 |

Reconciliation invariant holds on both days: **rows_in == rows_out + rows_quarantined**.

## Project structure

```
self-healing-data-pipeline/
├── config/
│   └── schema.json          # the schema contract: required columns, dtypes,
│                            #   valid ranges, allowed values, alias map
├── src/
│   ├── generate_data.py     # seeded synthetic telemetry generator (day1/day2)
│   ├── validate.py          # schema + row-level validation, per-row reasons
│   ├── quarantine.py        # writes failed rows with reasons; counts by reason
│   ├── transform.py         # alias/drift handling, cleaning, temp_f derivation
│   └── pipeline.py          # orchestrator: ingest→…→load→alert
├── run_pipeline.py          # CLI: python run_pipeline.py --day day1|day2
├── data/                    # generated demo CSVs (gitignored)
├── output/                  # parquet, sqlite, quarantine CSVs, alerts.json (gitignored)
├── requirements.txt
└── Dockerfile
```

## How to run

Prerequisites: Python 3.10+ (I tested on 3.12).

```bash
# 1. Set up a virtual environment and install dependencies
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 2. Generate the demo data (both batches, deterministic)
python src/generate_data.py

# 3. Run the pipeline for each day
python run_pipeline.py --day day1
python run_pipeline.py --day day2

# 4. Inspect the outputs
ls output/                       # clean_*.parquet, telemetry.db, quarantine_*.csv, alerts.json
cat output/alerts.json
```

### Docker

```bash
docker build -t self-healing-pipeline .
docker run --rm self-healing-pipeline
```

The container generates the data and runs both days end to end.

## Key design decisions

1. **Schema as a versioned JSON contract** (`config/schema.json`). The pipeline never hardcodes column expectations — ranges, dtypes, allowed values, and the alias map all live in one file, so a schema change is a config change, not a code change.
2. **Fail open on drift, fail closed on data.** A renamed column the alias map recognizes gets healed; an unknown column gets logged and dropped. But a row that violates a rule never flows downstream — it's quarantined. The pipeline keeps running either way.
3. **Quarantine, don't delete.** Every rejected row is persisted with its failure reason attached (`quarantine_<day>.csv`), plus per-reason counts. This gives me an audit trail and the option to replay rows after fixing them — the same instinct as keeping a failed test's logs, not just its pass/fail.
4. **Human-readable reasons per row.** `null:device_id`, `out_of_range:humidity (value=150.0, allowed 0.0..100.0)` — an on-call analyst can act on these without reading code.
5. **Reconciliation invariant.** Every run must satisfy `rows_in == rows_out + rows_quarantined`. If it doesn't, rows leaked somewhere — that's the pipeline's own smoke test.
6. **`alerts.json` as a run ledger.** Each day's stats merge into one file keyed by day, so reruns don't clobber history. In production this would be a metrics push / PagerDuty hook; here it's a file with the same shape.
7. **Dual load targets.** Parquet for analytics workloads, SQLite for zero-setup querying — the same clean frame goes to both from a single code path.
8. **Deterministic demo data.** Seeded RNG means anyone can regenerate `day1`/`day2` and reproduce the exact numbers in the table above.

## Future: mapping to an Airflow DAG

Each pipeline stage maps 1:1 to a DAG task, so this becomes production orchestration without restructuring:

| Pipeline stage | Airflow task | Notes |
|---|---|---|
| `generate_data.py` / ingest | `ingest_raw` (S3KeySensor / PythonOperator) | Swap CSV read for an object-store sensor |
| `transform.apply_aliases` + `drop_unexpected` | `handle_schema_drift` | Emits drift events to XCom for alerting |
| `validate` | `validate_records` | TaskFlow-mapped over partitions at scale |
| `quarantine.write_quarantine` | `quarantine_bad_rows` (BranchPythonOperator) | Skips downstream clean-path if everything failed |
| `transform.clean` | `transform_clean` | Pure function — easy to unit test |
| Parquet + SQLite loads | `load_parquet`, `load_sqlite` | Parallel; swap SQLite for Postgres/Snowflake hook |
| `alerts.json` merge + summary | `write_alerts` + `on_failure_callback` | Push metrics to Datadog / page on drift spikes |

A sketch of the DAG:

```python
with DAG("self_healing_pipeline", schedule="@daily", on_failure_callback=page_oncall):
    raw = ingest_raw()
    healed = handle_schema_drift(raw)
    validated = validate_records(healed)
    quarantine_bad_rows(validated) 
    clean = transform_clean(validated)
    [load_parquet(clean), load_sqlite(clean)] >> write_alerts()
```

The core logic (`src/`) wouldn't change — only the orchestration layer around it would.
