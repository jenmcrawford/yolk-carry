"""Dump the text of a coach-authored meal plan PDF for manual transcription.

Usage:
    uv run --with pdfplumber python scripts/extract_plan_pdf.py examples/<file>.pdf
"""

import sys
from pathlib import Path

import pdfplumber


def main(path: str) -> None:
    with pdfplumber.open(path) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            print(f"\n{'=' * 70}\nPAGE {i}\n{'=' * 70}")
            print(page.extract_text() or "(no text layer)")
            for j, table in enumerate(page.extract_tables(), start=1):
                print(f"\n--- page {i} table {j} ---")
                for row in table:
                    print(row)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: extract_plan_pdf.py <path-to-pdf>")
    main(str(Path(sys.argv[1])))
