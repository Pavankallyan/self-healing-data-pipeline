"""Shared fixtures for the self-healing-data-pipeline tests."""

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


@pytest.fixture
def schema():
    """Mirror of config/schema.json (kept inline so tests stay hermetic)."""
    return {
        "columns": {
            "device_id": {"type": "string", "required": True},
            "timestamp": {"type": "datetime", "required": True},
            "temp_c": {"type": "float", "required": True, "min": -40.0, "max": 60.0},
            "humidity": {"type": "float", "required": True, "min": 0.0, "max": 100.0},
            "battery_v": {"type": "float", "required": True, "min": 2.5, "max": 4.2},
            "status": {
                "type": "string",
                "required": True,
                "allowed": ["online", "idle", "offline"],
            },
        }
    }


@pytest.fixture
def clean_df():
    """One fully valid telemetry batch."""
    return pd.DataFrame(
        {
            "device_id": ["SH-001", "SH-002"],
            "timestamp": ["2026-10-24T08:00:00", "2026-10-24T08:05:00"],
            "temp_c": [21.5, 19.0],
            "humidity": [45.0, 52.5],
            "battery_v": [3.9, 4.1],
            "status": ["online", "idle"],
        }
    )
