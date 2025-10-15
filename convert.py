"""Command-line tool to batch convert .glb files to .obj files.

The tool scans an input directory (default: ``input``) for ``.glb`` files and
exports each model as ``.obj`` into the output directory (default: ``output``),
mirroring the input folder structure. Conversion relies on the ``trimesh``
library.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Iterable
from zipfile import ZipFile

try:  # noqa: SIM105 - handled for runtime dependency messaging
	import trimesh  # type: ignore
except ImportError:  # pragma: no cover - only hits when dependency missing
	trimesh = None  # type: ignore[assignment]


LOGGER = logging.getLogger("glb_to_obj")


@dataclass
class ConversionStats:
	"""Counters summarising a conversion run."""

	converted: int = 0
	skipped: int = 0
	failed: int = 0

	def as_dict(self) -> dict[str, int]:
		return {
			"converted": self.converted,
			"skipped": self.skipped,
			"failed": self.failed,
		}


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
	parser = argparse.ArgumentParser(
		description="Batch convert all .glb files in a folder to .obj format.",
	)
	parser.add_argument(
		"--input",
		"-i",
		type=Path,
		default=Path("input"),
		help="Directory containing .glb files (default: ./input).",
	)
	parser.add_argument(
		"--output",
		"-o",
		type=Path,
		default=Path("output"),
		help="Directory to write .obj files into (default: ./output).",
	)
	parser.add_argument(
		"--recursive",
		action="store_true",
		help="Recurse into sub-directories when searching for .glb files.",
	)
	parser.add_argument(
		"--overwrite",
		action="store_true",
		help="Overwrite existing .obj files in the output directory.",
	)
	parser.add_argument(
		"--quiet",
		"-q",
		action="store_true",
		help="Only print warnings and errors.",
	)

	return parser.parse_args(list(argv) if argv is not None else None)


def ensure_directories(input_dir: Path, output_dir: Path) -> None:
	if not input_dir.exists():
		input_dir.mkdir(parents=True, exist_ok=True)
		LOGGER.warning(
			"Input directory %s did not exist. Created it; populate it with .glb files and rerun.",
			input_dir,
		)
	elif not input_dir.is_dir():
		raise SystemExit(f"Input path {input_dir} is not a directory")

	output_dir.mkdir(parents=True, exist_ok=True)


def collect_glb_files(input_dir: Path, recursive: bool) -> list[Path]:
	pattern = "**/*.glb" if recursive else "*.glb"
	files = sorted(p for p in input_dir.glob(pattern) if p.is_file())
	if not files:
		LOGGER.warning("No .glb files found in %s", input_dir)
	return files


def convert_file(src: Path, dst_root: Path, input_root: Path, overwrite: bool) -> str:
	if trimesh is None:
		raise SystemExit(
			"trimesh is required for conversion. Install dependencies via 'pip install -r requirements.txt'."
		)

	relative = src.relative_to(input_root)
	destination = dst_root / relative.with_suffix(".obj")
	destination.parent.mkdir(parents=True, exist_ok=True)

	if destination.exists() and not overwrite:
		LOGGER.info("Skipping existing file: %s", destination)
		return "skipped"

	try:
		scene = trimesh.load(src, force="scene")
		scene.export(destination)
		LOGGER.info("Converted %s -> %s", src, destination)
		return "converted"
	except Exception:  # noqa: BLE001
		LOGGER.exception("Failed to convert %s", src)
		return "failed"


def convert_glb_bytes(payload: bytes, filename: str = "model.glb") -> tuple[bytes, list[str]]:
	"""Convert an in-memory GLB payload and return a ZIP archive of outputs.

	Parameters
	----------
	payload:
		Raw GLB file bytes.
	filename:
		Original file name (used for extensions and default archive naming).

	Returns
	-------
	archive_bytes:
		Bytes of a ZIP archive containing generated artefacts.
	artefacts:
		Relative paths of files stored in the ZIP.

	Raises
	------
	ValueError
		If the payload is empty.
	RuntimeError
		If conversion fails or produces no files.
	"""

	if not payload:
		raise ValueError("GLB payload is empty")

	with TemporaryDirectory() as tmp_dir:
		tmp_path = Path(tmp_dir)
		input_dir = tmp_path / "input"
		output_dir = tmp_path / "output"
		input_dir.mkdir(parents=True, exist_ok=True)
		output_dir.mkdir(parents=True, exist_ok=True)

		src_name = Path(filename).name or "model.glb"
		src_path = input_dir / src_name
		src_path.write_bytes(payload)

		result = convert_file(src_path, output_dir, input_dir, overwrite=True)
		if result == "failed":
			raise RuntimeError("Conversion failed; see logs for details")

		produced_files = [p for p in output_dir.rglob("*") if p.is_file()]
		if not produced_files:
			raise RuntimeError("Conversion completed but produced no files")

		zip_buffer = BytesIO()
		artefacts: list[str] = []
		with ZipFile(zip_buffer, "w") as zip_file:
			for artefact in produced_files:
				rel_path = artefact.relative_to(output_dir)
				zip_file.write(artefact, arcname=str(rel_path))
				artefacts.append(str(rel_path))

		zip_buffer.seek(0)
		return zip_buffer.getvalue(), artefacts


def run_conversion(args: argparse.Namespace) -> ConversionStats:
	ensure_directories(args.input, args.output)

	glb_files = collect_glb_files(args.input, args.recursive)

	stats = ConversionStats()
	for idx, glb_file in enumerate(glb_files, start=1):
		result = convert_file(glb_file, args.output, args.input, args.overwrite)
		setattr(stats, result, getattr(stats, result) + 1)
		LOGGER.debug("Progress: %s/%s", idx, len(glb_files))

	return stats


def configure_logging(quiet: bool) -> None:
	level = logging.WARNING if quiet else logging.INFO
	logging.basicConfig(level=level, format="%(levelname)s: %(message)s")


def main(argv: Iterable[str] | None = None) -> int:
	args = parse_args(argv)
	configure_logging(args.quiet)

	start = time.time()
	stats = run_conversion(args)
	duration = time.time() - start

	LOGGER.info(
		"Conversion finished in %.2fs: %s converted, %s skipped, %s failed.",
		duration,
		stats.converted,
		stats.skipped,
		stats.failed,
	)

	return 0 if stats.failed == 0 else 1


if __name__ == "__main__":
	sys.exit(main())
