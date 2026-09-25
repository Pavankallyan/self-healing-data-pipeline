"""CLI entry point: python run_pipeline.py --day day1|day2"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.pipeline import run


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the self-healing data pipeline.")
    parser.add_argument("--day", choices=["day1", "day2"], required=True,
                        help="Which demo batch to process.")
    args = parser.parse_args()
    run(args.day)


if __name__ == "__main__":
    main()
