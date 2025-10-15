"""FastAPI app that exposes GLB → OBJ conversion as an async job API."""

from __future__ import annotations

import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from dataclasses import dataclass, field
from io import BytesIO
from typing import Dict, Optional
from uuid import uuid4

from fastapi import BackgroundTasks, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from convert import convert_glb_bytes


DEFAULT_CONCURRENCY = int(os.getenv("WORKER_CONCURRENCY", "2"))
DEFAULT_TIMEOUT = int(os.getenv("JOB_TIMEOUT_SECONDS", "120"))


@dataclass
class JobRecord:
	job_id: str
	status: str = "queued"
	detail: Optional[str] = None
	artefacts: list[str] = field(default_factory=list)
	archive: Optional[bytes] = None
	created_at: float = field(default_factory=lambda: time.time())
	started_at: Optional[float] = None
	finished_at: Optional[float] = None
	original_name: Optional[str] = None


class JobManager:
	"""Coordinates background conversion jobs with a hard timeout."""

	def __init__(self, timeout_seconds: int, max_workers: int) -> None:
		self._timeout = timeout_seconds
		self._executor = ThreadPoolExecutor(max_workers=max_workers)
		self._lock = threading.Lock()
		self._jobs: Dict[str, JobRecord] = {}

	def submit(self, payload: bytes, filename: str) -> str:
		job_id = uuid4().hex
		record = JobRecord(job_id=job_id, original_name=filename)
		with self._lock:
			self._jobs[job_id] = record

		future = self._executor.submit(convert_glb_bytes, payload, filename)
		threading.Thread(
			target=self._monitor_future,
			args=(job_id, future),
			daemon=True,
		).start()
		return job_id

	def _monitor_future(self, job_id, future) -> None:  # type: ignore[no-untyped-def]
		with self._lock:
			record = self._jobs.get(job_id)
			if record is None:
				return
			record.status = "running"
			record.started_at = time.time()

		try:
			archive_bytes, artefacts = future.result(timeout=self._timeout)
		except FuturesTimeoutError:
			future.cancel()
			with self._lock:
				record = self._jobs.get(job_id)
				if record is not None:
					record.status = "timeout"
					record.detail = f"Conversion exceeded {self._timeout}s limit"
					record.finished_at = time.time()
		except Exception as exc:  # noqa: BLE001
			with self._lock:
				record = self._jobs.get(job_id)
				if record is not None:
					record.status = "failed"
					record.detail = str(exc)
					record.finished_at = time.time()
		else:
			with self._lock:
				record = self._jobs.get(job_id)
				if record is not None:
					record.status = "finished"
					record.archive = archive_bytes
					record.artefacts = artefacts
					record.finished_at = time.time()

	def get(self, job_id: str) -> Optional[JobRecord]:
		with self._lock:
			return self._jobs.get(job_id)

	def cleanup(self, max_age_seconds: int) -> None:
		threshold = time.time() - max_age_seconds
		with self._lock:
			for job_id, record in list(self._jobs.items()):
				finished = record.finished_at or record.created_at
				if finished < threshold:
					del self._jobs[job_id]


job_manager = JobManager(timeout_seconds=DEFAULT_TIMEOUT, max_workers=DEFAULT_CONCURRENCY)

app = FastAPI(title="GLB to OBJ Converter API", version="1.0.0")
app.add_middleware(
	CORSMiddleware,
	allow_origins=["*"],
	allow_credentials=False,
	allow_methods=["GET", "POST"],
	allow_headers=["*"]
)


@app.get("/healthz")
def health_check() -> dict[str, str]:
	return {"status": "ok"}


@app.post("/convert")
async def submit_conversion(background_tasks: BackgroundTasks, file: UploadFile = File(...)) -> JSONResponse:
	payload = await file.read()
	if not payload:
		raise HTTPException(status_code=400, detail="Uploaded file is empty")

	job_id = job_manager.submit(payload, file.filename or "model.glb")
	background_tasks.add_task(job_manager.cleanup, max_age_seconds=3600)
	return JSONResponse({"job_id": job_id, "status": "queued"})


@app.get("/jobs/{job_id}")
def fetch_job(job_id: str) -> JSONResponse:
	record = job_manager.get(job_id)
	if record is None:
		raise HTTPException(status_code=404, detail="Job not found")

	response: dict[str, object] = {
		"job_id": record.job_id,
		"status": record.status,
		"detail": record.detail,
		"artefacts": record.artefacts if record.status == "finished" else [],
		"created_at": record.created_at,
		"started_at": record.started_at,
		"finished_at": record.finished_at,
	}
	if record.status == "finished":
		response["download_url"] = f"/jobs/{record.job_id}/download"
	return JSONResponse(response)


@app.get("/jobs/{job_id}/download")
def download_archive(job_id: str) -> StreamingResponse:
	record = job_manager.get(job_id)
	if record is None or record.status != "finished" or record.archive is None:
		raise HTTPException(status_code=404, detail="Job output not available")

	filename = (record.original_name or "model.glb").rsplit(".", 1)[0] or "model"
	buffer = BytesIO(record.archive)
	response = StreamingResponse(buffer, media_type="application/zip")
	response.headers["Content-Disposition"] = f"attachment; filename={filename}.zip"
	return response


@app.on_event("shutdown")
def shutdown_event() -> None:
	job_manager.cleanup(max_age_seconds=0)


if __name__ == "__main__":
	import uvicorn

	uvicorn.run("app:app", host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
