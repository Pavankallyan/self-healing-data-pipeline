"""Quarantine: persist failed rows with their failure reasons attached.

Bad rows are never silently dropped -- they land in a quarantine CSV with a
failure_reason column, plus per-reason counts for alerting.
"""

from pathlib import Path

import pandas as pd


def write_quarantine(failures: pd.DataFrame, path: str | Path) -> dict:
    """Write failed rows to CSV with failure reasons attached.

    Returns a stats dict: rows quarantined, file path, counts by reason.
    Always writes a file (header-only when there are no failures) so
    downstream consumers can rely on it existing.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    if "failure_reason" not in failures.columns:
        failures = failures.copy()
        failures["failure_reason"] = ""

    failures.to_csv(path, index=False)

    reason_counts: dict[str, int] = {}
    for cell in failures["failure_reason"]:
        for reason in str(cell).split("; "):
            reason = reason.strip()
            if reason:
                # collapse to the reason key, dropping the parenthesised detail
                # (the full detail stays in the failure_reason column)
                key = reason.split(" (")[0]
                reason_counts[key] = reason_counts.get(key, 0) + 1

    return {
        "quarantine_file": str(path),
        "rows_quarantined": int(len(failures)),
        "reason_counts": reason_counts,
    }
