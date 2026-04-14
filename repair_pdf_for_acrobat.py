#!/usr/bin/env python3
"""Thin wrapper around the Acrobat-fix stage in clean_and_fit_pdf.py."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from clean_and_fit_pdf import repair_pdf_for_acrobat


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Rewrite a PDF with Acrobat-friendly numeric serialization."
    )
    parser.add_argument("input_pdf", type=Path, help="Input PDF path.")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Output PDF path. Defaults to '<stem>.acrobat-fixed.pdf'.",
    )
    parser.add_argument(
        "--deps-dir",
        type=Path,
        default=Path(".pydeps"),
        help="Directory containing local Python dependencies. Default: .pydeps",
    )
    parser.add_argument(
        "--precision",
        type=int,
        default=6,
        help="Maximum decimal places for rewritten numeric literals. Default: 6.",
    )
    parser.add_argument(
        "--linearize",
        action="store_true",
        help="Write a linearized PDF.",
    )
    parser.add_argument(
        "--object-streams",
        choices=["disable", "preserve", "generate"],
        default="disable",
        help="Object stream handling. Default: disable.",
    )
    return parser.parse_args()


def default_output_path(input_pdf: Path) -> Path:
    return input_pdf.with_name(f"{input_pdf.stem}.acrobat-fixed.pdf")


def main() -> int:
    args = parse_args()

    input_pdf = args.input_pdf.resolve()
    if not input_pdf.exists():
        raise FileNotFoundError(f"Input PDF not found: {input_pdf}")

    output_pdf = (args.output or default_output_path(input_pdf)).resolve()
    if output_pdf == input_pdf:
        raise ValueError("Output PDF must be different from the input PDF.")

    stats = repair_pdf_for_acrobat(
        input_pdf=input_pdf,
        output_pdf=output_pdf,
        deps_dir=args.deps_dir,
        precision=args.precision,
        object_streams=args.object_streams,
        linearize=args.linearize,
    )

    print(f"Input:   {input_pdf}")
    print(f"Output:  {output_pdf}")
    print(
        "Fixes:   "
        f"{stats['normalized_pages']} page box set(s), "
        f"{stats['normalized_streams']} content stream(s)"
    )
    print(
        "Stage:   "
        f"precision={stats['precision']}, "
        f"objects={stats['object_streams']}, "
        f"linearize={stats['linearize']}"
    )
    print(f"Bytes:   {output_pdf.stat().st_size}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1)
