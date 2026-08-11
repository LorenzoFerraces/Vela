#!/usr/bin/env python3
"""
pdf_to_text.py — Extract all text from a PDF into a single .txt file.

Usage:
  python pdf_to_text.py document.pdf
  python pdf_to_text.py document.pdf --output notes.txt
"""

import argparse
import sys
from pathlib import Path

import fitz  # PyMuPDF


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pdf", type=Path, help="Path to input PDF")
    ap.add_argument("--output", type=Path, default=None, help="Output .txt path (default: <pdf>.txt)")
    args = ap.parse_args()

    if not args.pdf.exists():
        sys.exit(f"File not found: {args.pdf}")

    output_path = args.output or args.pdf.with_suffix(".txt")

    doc = fitz.open(args.pdf)
    pages = []
    for i, page in enumerate(doc, start=1):
        pages.append(f"--- Page {i} ---\n{page.get_text().strip()}")

    output_path.write_text("\n\n".join(pages), encoding="utf-8")
    print(f"Extracted {len(doc)} pages -> {output_path}")


if __name__ == "__main__":
    main()
