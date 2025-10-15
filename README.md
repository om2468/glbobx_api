# GLB to OBJ Converter

This repository provides two ways to turn `.glb` assets into `.obj` exports:

- A command-line batch converter for local folders.
- A lightweight FastAPI service that queues background conversion jobs (great for Render or other lightweight hosting).

## Features

- Recursive or flat directory scanning
- Preserves the input folder structure under the output directory
- Skips already converted files unless `--overwrite` is provided
- Helpful logging, including warnings when the input directory is empty

## Requirements

- Python 3.9+
- [pip](https://pip.pypa.io/) for dependency installation

Install dependencies:

```bash
pip install -r requirements.txt
```

## Usage

Choose whichever workflow fits best.

### Option 1 — CLI batch converter

By default the script looks for GLB files inside `./input` and writes OBJ files
into `./output`. The directories are created as needed.

```bash
python convert.py
```

### Option 2 — FastAPI job API

Start the API server locally with Uvicorn:

```bash
uvicorn app:app --reload --host 0.0.0.0 --port 8000
```

Upload a GLB file; you receive a job ID immediately. Conversion runs in a background worker and can be tailored via environment variables:

- `WORKER_CONCURRENCY` (default `2`): number of background threads.
- `JOB_TIMEOUT_SECONDS` (default `120`): hard limit before a job times out.

#### REST workflow

1. Submit work:

   ```bash
   curl -X POST \
     -F file=@example.glb \
     http://localhost:8000/convert
   # => {"job_id":"<id>","status":"queued"}
   ```

2. Poll status:

   ```bash
   curl http://localhost:8000/jobs/<id>
   # => {"status":"finished","artefacts":[...],"download_url":"/jobs/<id>/download"}
   ```

3. Download ZIP (once finished):

   ```bash
   curl -L -o output.zip http://localhost:8000/jobs/<id>/download
   ```

Jobs older than one hour are purged automatically when new jobs arrive; adjust the retention by editing `app.py` if you need a different policy.

#### Using the shared helper directly

Both the CLI and API call the same `convert_glb_bytes` helper. You can reuse it from any Python workflow:

```python
from pathlib import Path

from convert import convert_glb_bytes

payload = Path("example.glb").read_bytes()
archive_bytes, artefacts = convert_glb_bytes(payload, filename="example.glb")

output_path = Path("example.zip")
output_path.write_bytes(archive_bytes)
print("Generated:", artefacts)
```

To match the Streamlit experience:

Keep texture files alongside the original GLB if they should be referenced in exported `.mtl` files.

### Command-line options

| Flag | Description |
| ---- | ----------- |
| `--input`, `-i` | Alternate directory containing `.glb` files (defaults to `./input`). |
| `--output`, `-o` | Directory to write `.obj` exports (defaults to `./output`). |
| `--recursive` | Search within subdirectories of the input folder. |
| `--overwrite` | Force regeneration of `.obj` files even if they already exist. |
| `--quiet`, `-q` | Suppress informational logging. |

Example converting files in a custom directory and forcing overwrites:

```bash
python convert.py --input assets/glb --output build/obj --recursive --overwrite
```

## Workflow

1. Place your `.glb` files into the `input/` directory (create subfolders as
   needed).
2. Run `python convert.py`.
3. Collect the generated `.obj` (and `.mtl`) files from the `output/`
   directory. The folder structure mirrors what you placed under `input/`.

## Notes

- The converter relies on [`trimesh`](https://trimsh.org/); conversion quality depends on what that library supports.
- When the input folder is missing, the CLI creates it and exits with a helpful warning so you can drop your models in before running again.
- The API stores job outputs in memory; for long-lived history or large outputs you may want to stream results to object storage instead.

## Deploying to Render (free tier friendly)

1. Push this repository to GitHub.
2. In Render, create a **Web Service** and point it at the repo.
3. Use `uvicorn app:app --host 0.0.0.0 --port $PORT` as the start command.
4. Set `PYTHON_VERSION`, `WORKER_CONCURRENCY`, or `JOB_TIMEOUT_SECONDS` in Render if the defaults do not match your workload.
5. Deploy. Render automatically rebuilds when new commits land on the tracked branch.

Render free tier tips:

- Services spin down when idle; allow for a cold-start hit on the first request.
- Keep uploads modest; free instances have limited memory. If you need larger conversions, increase the instance size or add a queue with durable storage.
