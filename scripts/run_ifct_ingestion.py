#!/usr/bin/env python
"""
Standalone runner script for IFCT 2017 database ingestion.
Can be run via:
    python scripts/run_ifct_ingestion.py
"""
import os
import sys
from pathlib import Path

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django
django.setup()

from nutrition.ingestion.pipeline import run_ifct_ingestion


def main():
    pdf_path = BASE_DIR / "raw_data" / "IFCT2017_16122024.pdf"
    if not pdf_path.exists():
        print(f"Error: PDF not found at {pdf_path}")
        sys.exit(1)

    print(f"=== Starting IFCT 2017 SQL Database Ingestion ===")
    print(f"PDF source: {pdf_path}")
    summary = run_ifct_ingestion(str(pdf_path))
    print(f"\n[DONE] Ingestion Complete!")
    print(f"  Food Groups: {summary['groups_count']}")
    print(f"  Foods:       {summary['foods_count']}")
    print(f"  Proximates:  {summary['proximates_count']}")
    print(f"  Vitamins:    {summary['vitamins_count']}")
    print(f"  Minerals:    {summary['minerals_count']}")
    print(f"  Duration:    {summary['elapsed_seconds']}s")


if __name__ == "__main__":
    main()
