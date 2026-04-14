#!/usr/bin/env python3
"""Remove leading wrapper groups from a PDF page and fit the page to content.

This module keeps the original CLI workflow intact and also exposes a reusable
``process_pdf`` function so it can be wrapped by a desktop GUI.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
import zlib
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Callable

LONG_DECIMAL_RE = re.compile(
    rb"(?<![A-Za-z0-9_.])([+-]?\d+\.\d{7,})(?![A-Za-z0-9_.])"
)
OBJECT_STREAM_CHOICES = {"disable", "preserve", "generate"}
ProgressCallback = Callable[[str], None]


@dataclass
class ProcessingOptions:
    input_pdf: Path
    output_pdf: Path | None = None
    page: int = 1
    wrapper_groups: int = 2
    padding: float = 0.0
    acrobat_fix: bool = True
    dpi: int = 1200
    pdftoppm: Path | None = None
    deps_dir: Path = Path(".pydeps")
    precision: int = 6
    linearize: bool = False
    object_streams: str = "disable"
    tmp_dir: Path = Path("tmp/pdfs")
    keep_temp: bool = False


@dataclass
class ProcessingResult:
    input_pdf: Path
    output_pdf: Path
    page: int
    wrapper_groups: int
    renderer: str
    bbox_pt: tuple[float, float, float, float]
    size_pt: tuple[float, float]
    output_bytes: int
    repair_stats: dict[str, int | str | bool] | None = None
    kept_files: dict[str, Path] | None = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Remove the first N nested wrapper drawing groups from one PDF page "
            "and output an exact-fit vector PDF."
        )
    )
    parser.add_argument("input_pdf", type=Path, help="Input PDF path.")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Output PDF path. Defaults to '<stem>.no-outer-rects.exact-fit.pdf'.",
    )
    parser.add_argument(
        "--page",
        type=int,
        default=1,
        help="1-based page number to process. Output contains only this page.",
    )
    parser.add_argument(
        "--wrapper-groups",
        type=int,
        default=2,
        help="Number of first nested drawing groups to remove. Default: 2.",
    )
    parser.add_argument(
        "--padding",
        type=float,
        default=0.0,
        help="Padding to add around measured content bounds, in PDF points.",
    )
    parser.add_argument(
        "--acrobat-fix",
        action="store_true",
        default=True,
        help="Run an Acrobat-compatibility rewrite after fitting. Default: enabled.",
    )
    parser.add_argument(
        "--no-acrobat-fix",
        dest="acrobat_fix",
        action="store_false",
        help="Skip the Acrobat-compatibility rewrite.",
    )
    parser.add_argument(
        "--dpi",
        type=int,
        default=1200,
        help="Render DPI used to measure painted bounds. Default: 1200.",
    )
    parser.add_argument(
        "--pdftoppm",
        type=Path,
        help="Optional fallback path to pdftoppm. Used only if PyMuPDF is unavailable.",
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
        help="Maximum decimal places for Acrobat-fix numeric rewriting. Default: 6.",
    )
    parser.add_argument(
        "--linearize",
        action="store_true",
        help="Write a linearized final PDF during the Acrobat-fix stage.",
    )
    parser.add_argument(
        "--object-streams",
        choices=sorted(OBJECT_STREAM_CHOICES),
        default="disable",
        help="Object stream handling for the Acrobat-fix stage. Default: disable.",
    )
    parser.add_argument(
        "--tmp-dir",
        type=Path,
        default=Path("tmp/pdfs"),
        help="Directory for intermediate files. Default: tmp/pdfs.",
    )
    parser.add_argument(
        "--keep-temp",
        action="store_true",
        help="Keep intermediate cleaned PDF and rendered PNG.",
    )
    return parser.parse_args()


def page_size_points(page) -> tuple[float, float]:
    mediabox = page.mediabox
    width = float(mediabox.right) - float(mediabox.left)
    height = float(mediabox.top) - float(mediabox.bottom)
    return width, height


def default_output_path(input_pdf: Path) -> Path:
    return input_pdf.with_name(f"{input_pdf.stem}.no-outer-rects.exact-fit.pdf")


def resolve_pdftoppm(explicit_path: Path | None) -> str:
    if explicit_path is not None:
        if not explicit_path.exists():
            raise FileNotFoundError(f"pdftoppm not found: {explicit_path}")
        return str(explicit_path)
    found = shutil.which("pdftoppm")
    if not found:
        raise FileNotFoundError(
            "pdftoppm was not found on PATH. Pass --pdftoppm with its full path."
        )
    return found


def add_local_dep_path(local_dep_dir: Path) -> None:
    resolved = str(local_dep_dir.resolve())
    if local_dep_dir.exists() and resolved not in sys.path:
        sys.path.insert(0, resolved)


def load_pdf_backend(local_dep_dir: Path | None = None):
    try:
        from pypdf import PdfReader, PdfWriter, Transformation
        from pypdf.generic import ContentStream, DecodedStreamObject, NameObject
    except ImportError:
        if local_dep_dir is not None:
            add_local_dep_path(local_dep_dir)
        try:
            from pypdf import PdfReader, PdfWriter, Transformation
            from pypdf.generic import ContentStream, DecodedStreamObject, NameObject
        except ImportError:
            try:
                from PyPDF2 import PdfReader, PdfWriter, Transformation
                from PyPDF2.generic import ContentStream, DecodedStreamObject, NameObject
            except ImportError as exc:
                raise ModuleNotFoundError(
                    "Install pypdf or PyPDF2 to use clean_and_fit_pdf."
                ) from exc

    return (
        PdfReader,
        PdfWriter,
        Transformation,
        ContentStream,
        DecodedStreamObject,
        NameObject,
    )


def load_pil_modules(local_dep_dir: Path | None = None):
    try:
        from PIL import Image, ImageChops, ImageFile
    except ImportError as exc:
        if local_dep_dir is not None:
            add_local_dep_path(local_dep_dir)
            try:
                from PIL import Image, ImageChops, ImageFile
            except ImportError:
                raise ModuleNotFoundError("Install Pillow to use clean_and_fit_pdf.") from exc
        else:
            raise ModuleNotFoundError("Install Pillow to use clean_and_fit_pdf.") from exc

    ImageFile.LOAD_TRUNCATED_IMAGES = True
    Image.MAX_IMAGE_PIXELS = None
    return Image, ImageChops


def load_pymupdf(local_dep_dir: Path | None = None):
    try:
        import pymupdf  # type: ignore
    except ImportError:
        if local_dep_dir is not None:
            add_local_dep_path(local_dep_dir)
            try:
                import pymupdf  # type: ignore
            except ImportError:
                pymupdf = None  # type: ignore[assignment]
        else:
            pymupdf = None  # type: ignore[assignment]
        if pymupdf is not None:
            return pymupdf
        try:
            import fitz as pymupdf  # type: ignore
        except ImportError as exc:
            raise ModuleNotFoundError("Install PyMuPDF to use the built-in renderer.") from exc

    return pymupdf


def load_pikepdf(local_dep_dir: Path):
    try:
        import pikepdf  # type: ignore
    except ImportError as exc:
        add_local_dep_path(local_dep_dir)
        try:
            import pikepdf  # type: ignore
        except ImportError:
            raise ModuleNotFoundError(
                "Install pikepdf or place it in the dependency directory."
            ) from exc

    return pikepdf


def format_decimal(value: Decimal, precision: int) -> str:
    quant = Decimal(1).scaleb(-precision)
    rounded = value.quantize(quant)
    text = format(rounded, "f").rstrip("0").rstrip(".")
    if text in {"-0", "+0", ""}:
        return "0"
    return text


def round_numeric_literal(match: re.Match[bytes], precision: int) -> bytes:
    raw = match.group(1).decode("ascii")
    try:
        value = Decimal(raw)
    except InvalidOperation:
        return match.group(1)
    return format_decimal(value, precision).encode("ascii")


def normalize_page_boxes(page, precision: int) -> None:
    for box_name in ("/MediaBox", "/CropBox", "/BleedBox", "/TrimBox", "/ArtBox"):
        if box_name not in page.obj:
            continue
        box = page.obj[box_name]
        if len(box) != 4:
            continue
        normalized = [
            Decimal(format_decimal(Decimal(str(value)), precision)) for value in box
        ]
        page.obj[box_name] = normalized


def normalize_contents(page, precision: int, pikepdf) -> int:
    page.contents_coalesce()
    contents = page.obj.get("/Contents")
    if contents is None:
        return 0

    original = contents.read_bytes()
    rewritten = LONG_DECIMAL_RE.sub(
        lambda match: round_numeric_literal(match, precision), original
    )
    if rewritten != original:
        contents.write(zlib.compress(rewritten), filter=pikepdf.Name("/FlateDecode"))
        return 1
    return 0


def repair_pdf_for_acrobat(
    input_pdf: Path,
    output_pdf: Path,
    deps_dir: Path,
    precision: int,
    object_streams: str,
    linearize: bool,
) -> dict[str, int | str | bool]:
    pikepdf = load_pikepdf(deps_dir)
    object_stream_mode = getattr(pikepdf.ObjectStreamMode, object_streams)

    normalized_pages = 0
    normalized_streams = 0
    with pikepdf.open(str(input_pdf)) as pdf:
        for page in pdf.pages:
            normalize_page_boxes(page, precision)
            normalized_pages += 1
            normalized_streams += normalize_contents(page, precision, pikepdf)

        pdf.save(
            str(output_pdf),
            compress_streams=True,
            recompress_flate=True,
            normalize_content=False,
            object_stream_mode=object_stream_mode,
            linearize=linearize,
            fix_metadata_version=True,
        )

    return {
        "normalized_pages": normalized_pages,
        "normalized_streams": normalized_streams,
        "precision": precision,
        "linearize": linearize,
        "object_streams": object_streams,
    }


def remove_leading_nested_groups(
    page, reader, groups_to_remove: int, local_dep_dir: Path | None = None
) -> bytes:
    _, _, _, ContentStream, _, _ = load_pdf_backend(local_dep_dir)
    content = ContentStream(page.get_contents(), reader)
    new_operations = []
    depth = 0
    skip_depth = None
    removed = 0

    for operands, operator in content.operations:
        if operator == b"q":
            if skip_depth is None and depth == 1 and removed < groups_to_remove:
                removed += 1
                depth += 1
                skip_depth = depth
                continue
            depth += 1
            new_operations.append((operands, operator))
            continue

        if operator == b"Q":
            if skip_depth is not None:
                if depth == skip_depth:
                    depth -= 1
                    skip_depth = None
                    continue
                depth -= 1
                continue
            depth -= 1
            new_operations.append((operands, operator))
            continue

        if skip_depth is None:
            new_operations.append((operands, operator))

    if removed != groups_to_remove:
        raise RuntimeError(
            f"Expected to remove {groups_to_remove} wrapper groups, removed {removed}."
        )

    content.operations = new_operations
    return content.get_data()


def write_single_page_pdf(
    source_pdf: Path,
    output_pdf: Path,
    page_number: int,
    cleaned_stream: bytes | None = None,
    bbox_pt: tuple[float, float, float, float] | None = None,
    padding: float = 0.0,
    local_dep_dir: Path | None = None,
) -> None:
    (
        PdfReader,
        PdfWriter,
        Transformation,
        _,
        DecodedStreamObject,
        NameObject,
    ) = load_pdf_backend(local_dep_dir)
    reader = PdfReader(str(source_pdf))
    page = reader.pages[page_number - 1]
    writer = PdfWriter()

    if cleaned_stream is not None:
        stream = DecodedStreamObject()
        stream.set_data(cleaned_stream)
        stream = stream.flate_encode()
        page[NameObject("/Contents")] = writer._add_object(stream)

    if bbox_pt is not None:
        x0, y0, x1, y1 = bbox_pt
        shift_x = -(x0 - padding)
        shift_y = -(y0 - padding)
        width = (x1 - x0) + 2 * padding
        height = (y1 - y0) + 2 * padding
        page.add_transformation(Transformation().translate(tx=shift_x, ty=shift_y))
        for box_name in ["mediabox", "cropbox", "trimbox", "bleedbox", "artbox"]:
            box = getattr(page, box_name, None)
            if box is None:
                continue
            box.lower_left = (0, 0)
            box.upper_right = (width, height)

    current_contents = page.get_contents()
    if current_contents is not None:
        stream = DecodedStreamObject()
        stream.set_data(current_contents.get_data())
        stream = stream.flate_encode()
        page[NameObject("/Contents")] = writer._add_object(stream)

    writer.add_page(page)
    with output_pdf.open("wb") as handle:
        writer.write(handle)


def render_page_to_png(
    pdf_path: Path,
    png_prefix: Path,
    page_number: int,
    dpi: int,
    pdftoppm: str,
) -> Path:
    command = [
        pdftoppm,
        "-r",
        str(dpi),
        "-png",
        "-f",
        str(page_number),
        "-l",
        str(page_number),
        "-singlefile",
        str(pdf_path),
        str(png_prefix),
    ]
    subprocess.run(command, check=True)
    png_path = png_prefix.parent / f"{png_prefix.name}.png"
    if not png_path.exists():
        raise FileNotFoundError(f"Expected render output not found: {png_path}")
    return png_path


def render_page_to_png_with_pymupdf(
    pdf_path: Path,
    png_prefix: Path,
    page_number: int,
    dpi: int,
    local_dep_dir: Path | None = None,
) -> Path:
    pymupdf = load_pymupdf(local_dep_dir)
    png_path = png_prefix.parent / f"{png_prefix.name}.png"
    scale = dpi / 72.0

    with pymupdf.open(str(pdf_path)) as document:
        page = document.load_page(page_number - 1)
        pixmap = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
        pixmap.save(str(png_path))

    if not png_path.exists():
        raise FileNotFoundError(f"Expected render output not found: {png_path}")
    return png_path


def measure_nonwhite_bbox(
    png_path: Path,
    dpi: int,
    page_height_pt: float,
    local_dep_dir: Path | None = None,
) -> tuple[float, float, float, float]:
    Image, ImageChops = load_pil_modules(local_dep_dir)
    with Image.open(png_path) as image:
        rgb = image.convert("RGB")
        inverted = ImageChops.invert(rgb)
        bbox = inverted.getbbox()

    if bbox is None:
        raise RuntimeError("No non-white content detected in rendered page.")

    left, upper, right, lower = bbox
    scale = 72.0 / dpi
    x0 = left * scale
    x1 = right * scale
    y1 = page_height_pt - upper * scale
    y0 = page_height_pt - lower * scale
    return x0, y0, x1, y1


def build_processing_options(args: argparse.Namespace) -> ProcessingOptions:
    return ProcessingOptions(
        input_pdf=args.input_pdf,
        output_pdf=args.output,
        page=args.page,
        wrapper_groups=args.wrapper_groups,
        padding=args.padding,
        acrobat_fix=args.acrobat_fix,
        dpi=args.dpi,
        pdftoppm=args.pdftoppm,
        deps_dir=args.deps_dir,
        precision=args.precision,
        linearize=args.linearize,
        object_streams=args.object_streams,
        tmp_dir=args.tmp_dir,
        keep_temp=args.keep_temp,
    )


def resolve_renderer(
    local_dep_dir: Path, explicit_pdftoppm: Path | None
) -> tuple[str, str | None]:
    try:
        load_pymupdf(local_dep_dir)
        return "PyMuPDF", None
    except ModuleNotFoundError:
        pdftoppm = resolve_pdftoppm(explicit_pdftoppm)
        return "pdftoppm", pdftoppm


def _validate_options(options: ProcessingOptions) -> tuple[Path, Path]:
    input_pdf = options.input_pdf.resolve()
    if not input_pdf.exists():
        raise FileNotFoundError(f"Input PDF not found: {input_pdf}")

    output_pdf = (options.output_pdf or default_output_path(input_pdf)).resolve()
    if output_pdf == input_pdf:
        raise ValueError("Output PDF must be different from the input PDF.")

    if options.page < 1:
        raise ValueError("--page must be 1 or greater.")
    if options.wrapper_groups < 0:
        raise ValueError("--wrapper-groups must be 0 or greater.")
    if options.dpi <= 0:
        raise ValueError("--dpi must be positive.")
    if options.padding < 0:
        raise ValueError("--padding must be 0 or greater.")
    if options.precision < 0:
        raise ValueError("--precision must be 0 or greater.")
    if options.object_streams not in OBJECT_STREAM_CHOICES:
        raise ValueError(
            "--object-streams must be one of "
            + ", ".join(sorted(OBJECT_STREAM_CHOICES))
            + "."
        )

    return input_pdf, output_pdf


def process_pdf(
    options: ProcessingOptions, progress: ProgressCallback | None = None
) -> ProcessingResult:
    reporter = progress or (lambda _message: None)
    input_pdf, output_pdf = _validate_options(options)
    PdfReader, _, _, _, _, _ = load_pdf_backend(options.deps_dir)
    renderer_name, renderer_resource = resolve_renderer(options.deps_dir, options.pdftoppm)

    reporter(f"Using input PDF: {input_pdf}")
    reporter(f"Writing output PDF: {output_pdf}")
    if renderer_resource:
        reporter(f"Using renderer: {renderer_name} ({renderer_resource})")
    else:
        reporter(f"Using renderer: {renderer_name}")

    tmp_dir = options.tmp_dir.resolve()
    tmp_dir.mkdir(parents=True, exist_ok=True)

    reader = PdfReader(str(input_pdf))
    if options.page > len(reader.pages):
        raise IndexError(
            f"Input has {len(reader.pages)} page(s), cannot use page {options.page}."
        )

    _, page_height_pt = page_size_points(reader.pages[options.page - 1])

    reporter("Removing wrapper groups from the selected page.")
    kept_files: dict[str, Path] | None = None
    with tempfile.TemporaryDirectory(dir=tmp_dir) as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        cleaned_pdf = temp_dir / "cleaned.pdf"
        fitted_raw_pdf = temp_dir / "fitted-raw.pdf"
        png_prefix = temp_dir / "rendered"

        cleaned_stream = remove_leading_nested_groups(
            reader.pages[options.page - 1],
            reader,
            options.wrapper_groups,
            options.deps_dir,
        )
        write_single_page_pdf(
            source_pdf=input_pdf,
            output_pdf=cleaned_pdf,
            page_number=options.page,
            cleaned_stream=cleaned_stream,
            local_dep_dir=options.deps_dir,
        )

        reporter("Rendering a temporary PNG to measure the painted bounds.")
        if renderer_name == "PyMuPDF":
            rendered_png = render_page_to_png_with_pymupdf(
                pdf_path=cleaned_pdf,
                png_prefix=png_prefix,
                page_number=1,
                dpi=options.dpi,
                local_dep_dir=options.deps_dir,
            )
        else:
            rendered_png = render_page_to_png(
                pdf_path=cleaned_pdf,
                png_prefix=png_prefix,
                page_number=1,
                dpi=options.dpi,
                pdftoppm=renderer_resource or resolve_pdftoppm(options.pdftoppm),
            )
        bbox_pt = measure_nonwhite_bbox(
            rendered_png, options.dpi, page_height_pt, options.deps_dir
        )

        reporter("Rewriting the page to the measured content size.")
        write_single_page_pdf(
            source_pdf=cleaned_pdf,
            output_pdf=fitted_raw_pdf,
            page_number=1,
            bbox_pt=bbox_pt,
            padding=options.padding,
            local_dep_dir=options.deps_dir,
        )

        repair_stats = None
        if options.acrobat_fix:
            reporter("Applying the Acrobat compatibility rewrite.")
            repair_stats = repair_pdf_for_acrobat(
                input_pdf=fitted_raw_pdf,
                output_pdf=output_pdf,
                deps_dir=options.deps_dir,
                precision=options.precision,
                object_streams=options.object_streams,
                linearize=options.linearize,
            )
        else:
            reporter("Skipping the Acrobat compatibility rewrite.")
            shutil.copy2(fitted_raw_pdf, output_pdf)

        if options.keep_temp:
            kept_files = {
                "cleaned_pdf": output_pdf.with_name(
                    f"{output_pdf.stem}.intermediate-cleaned.pdf"
                ),
                "fitted_pdf": output_pdf.with_name(
                    f"{output_pdf.stem}.intermediate-fitted.pdf"
                ),
                "measurement_png": output_pdf.with_name(
                    f"{output_pdf.stem}.measurement.png"
                ),
            }
            kept_files["cleaned_pdf"].write_bytes(cleaned_pdf.read_bytes())
            kept_files["fitted_pdf"].write_bytes(fitted_raw_pdf.read_bytes())
            kept_files["measurement_png"].write_bytes(rendered_png.read_bytes())
            reporter("Saved the intermediate debug files next to the output PDF.")

    x0, y0, x1, y1 = bbox_pt
    width = (x1 - x0) + 2 * options.padding
    height = (y1 - y0) + 2 * options.padding
    reporter("Finished processing the PDF.")
    return ProcessingResult(
        input_pdf=input_pdf,
        output_pdf=output_pdf,
        page=options.page,
        wrapper_groups=options.wrapper_groups,
        renderer=renderer_name,
        bbox_pt=bbox_pt,
        size_pt=(width, height),
        output_bytes=output_pdf.stat().st_size,
        repair_stats=repair_stats,
        kept_files=kept_files,
    )


def format_result_summary(result: ProcessingResult) -> list[str]:
    x0, y0, x1, y1 = result.bbox_pt
    width, height = result.size_pt
    lines = [
        f"Input:   {result.input_pdf}",
        f"Output:  {result.output_pdf}",
        f"Page:    {result.page}",
        f"Removed: {result.wrapper_groups} wrapper group(s)",
        f"Render:  {result.renderer}",
        (
            "Bounds:  "
            f"x0={x0:.3f}, y0={y0:.3f}, x1={x1:.3f}, y1={y1:.3f} pt"
        ),
        f"Size:    {width:.3f} x {height:.3f} pt",
        f"Bytes:   {result.output_bytes}",
    ]
    if result.repair_stats is not None:
        lines.append("Acrobat: enabled")
        lines.append(
            "Fixes:   "
            f"{result.repair_stats['normalized_pages']} page box set(s), "
            f"{result.repair_stats['normalized_streams']} content stream(s)"
        )
        lines.append(
            "Stage:   "
            f"precision={result.repair_stats['precision']}, "
            f"objects={result.repair_stats['object_streams']}, "
            f"linearize={result.repair_stats['linearize']}"
        )
    else:
        lines.append("Acrobat: disabled")

    if result.kept_files:
        lines.append(f"Kept:    {result.kept_files['cleaned_pdf']}")
        lines.append(f"Kept:    {result.kept_files['fitted_pdf']}")
        lines.append(f"Kept:    {result.kept_files['measurement_png']}")
    return lines


def main() -> int:
    args = parse_args()
    result = process_pdf(build_processing_options(args))
    for line in format_result_summary(result):
        print(line)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1)
