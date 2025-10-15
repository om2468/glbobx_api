"""Quick integration test against the deployed Render API."""

from __future__ import annotations

import argparse
import sys
import time
from io import BytesIO
from pathlib import Path
from zipfile import BadZipFile, ZipFile
from typing import Any

import requests


DEFAULT_BASE_URL = "https://glbobx-api.onrender.com"
DEFAULT_OUTPUT_DIR = Path("output")
POLL_INTERVAL_SECONDS = 2.0
MAX_POLL_ATTEMPTS = 90  # 3 minutes by default


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
	parser = argparse.ArgumentParser(description="Submit a GLB file to the deployed API and download the result.")
	parser.add_argument(
		"glb_path",
		type=Path,
		nargs="?",
		default=Path("input/oldmodelzaz.glb"),
		help="Path to the GLB file to upload (default: input/oldmodelzaz.glb)",
	)
	parser.add_argument(
		"--base-url",
		default=DEFAULT_BASE_URL,
		help="Base URL of the API service.",
	)
	parser.add_argument(
		"--output-dir",
		type=Path,
		default=DEFAULT_OUTPUT_DIR,
		help="Directory to write the downloaded ZIP archive (default: ./output).",
	)
	parser.add_argument(
		"--attempts",
		type=int,
		default=MAX_POLL_ATTEMPTS,
		help="Maximum number of status polls before giving up.",
	)
	parser.add_argument(
		"--interval",
		type=float,
		default=POLL_INTERVAL_SECONDS,
		help="Seconds to wait between polls.",
	)
	return parser.parse_args(argv)


def submit_job(base_url: str, glb_path: Path) -> str:
	if not glb_path.is_file():
		raise FileNotFoundError(f"GLB file not found: {glb_path}")

	files = {"file": (glb_path.name, glb_path.read_bytes(), "model/gltf-binary")}
	response = requests.post(f"{base_url}/convert", files=files, timeout=60)
	response.raise_for_status()
	payload = response.json()
	job_id = payload.get("job_id")
	if not job_id:
		raise RuntimeError(f"Unexpected response payload: {payload}")
	return job_id


def poll_status(base_url: str, job_id: str, attempts: int, interval: float) -> dict[str, Any]:
	for attempt in range(1, attempts + 1):
		response = requests.get(f"{base_url}/jobs/{job_id}", timeout=30)
		if response.status_code == 404:
			time.sleep(interval)
			continue
			
		response.raise_for_status()
		payload = response.json()
		status = payload.get("status")
		if status in {"finished", "failed", "timeout"}:
			return payload
			time.sleep(interval)

	raise TimeoutError(f"Job {job_id} did not finish after {attempts} attempts")


def _detect_filename(headers: dict[str, str], fallback: str) -> str:
	content_disposition = headers.get("Content-Disposition")
	if not content_disposition:
		return fallback

	parts = content_disposition.split(";")
	for part in parts:
		part = part.strip()
		if part.lower().startswith("filename="):
			value = part.split("=", 1)[1].strip().strip('"')
			return value or fallback
	return fallback


def download_archive(base_url: str, job_id: str, output_dir: Path) -> Path:
	response = requests.get(f"{base_url}/jobs/{job_id}/download", timeout=120, stream=True)
	response.raise_for_status()
	filename = _detect_filename(response.headers, fallback=f"{job_id}.zip")
	output_dir.mkdir(parents=True, exist_ok=True)
	final_path = output_dir / filename

	try:
		data = bytearray()
		for chunk in response.iter_content(chunk_size=8192):
			if chunk:
				data.extend(chunk)

		if not data:
			raise RuntimeError("Received empty response when downloading archive")

		# Validate ZIP integrity before writing to disk.
		with ZipFile(BytesIO(data)) as archive:
			bad_member = archive.testzip()
			if bad_member is not None:
				raise RuntimeError(f"Archive corrupted at member {bad_member}")

		final_path.write_bytes(data)
		return final_path
	except KeyboardInterrupt:
		if final_path.exists():
			final_path.unlink()
		raise


def main(argv: list[str] | None = None) -> int:
	args = parse_args(argv)
	print(f"Submitting {args.glb_path} to {args.base_url}")
	job_id = submit_job(args.base_url.rstrip("/"), args.glb_path)
	print(f"Job queued: {job_id}")

	print("Polling for completion...")
	result = poll_status(args.base_url.rstrip("/"), job_id, args.attempts, args.interval)
	status = result.get("status")
	print(f"Final status: {status}")
	if status != "finished":
		print(f"Detail: {result.get('detail')}")
		return 1

	archive_path = download_archive(args.base_url.rstrip("/"), job_id, args.output_dir)
	print(f"Downloaded archive to {archive_path} containing: {result.get('artefacts')}")
	return 0


if __name__ == "__main__":
	sys.exit(main())
