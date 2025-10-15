# How to Run the GLB → OBJ API

This quick guide shows two ways to submit GLB models to the deployed API at `https://glbobx-api.onrender.com` and retrieve the converted ZIP archive.

## Using curl

1. **Upload the GLB file**

   ```bash
   curl -X POST \
     -F file=@input/oldmodelzaz.glb \
     https://glbobx-api.onrender.com/convert
   ```

   Response example:

   ```json
   {"job_id":"6011e5b21d6043a6b606db844bfc59bb","status":"queued"}
   ```

2. **Poll the job status**

   Replace `<job_id>` with the value returned in step 1.

   ```bash
   curl https://glbobx-api.onrender.com/jobs/<job_id>
   ```

   Once the response contains `"status":"finished"`, note the `download_url`.

3. **Download the ZIP archive**

   ```bash
   curl -L -o output/<job_id>.zip https://glbobx-api.onrender.com/jobs/<job_id>/download
   ```

   Adjust the output path or filename as needed.

## Using FME HTTPCaller

The Safe Software FME HTTPCaller transformer can orchestrate the same three steps inside a workspace.

1. **Create job submission transformer**
   - Add an **HTTPCaller**.
   - Method: `POST`.
   - URL: `https://glbobx-api.onrender.com/convert`.
   - Request Body: choose *Multipart Form Data* and add one part:
     - Name: `file`
     - File Path: attribute or fixed path to your `.glb` file.
   - Response Attribute: store the JSON response in an attribute (e.g. `_job_json`).

2. **Parse the job ID**
   - Add a **JSONExtractor** (or AttributeValueRetriever) to pull `job_id` from `_job_json` into a new attribute, e.g. `_job_id`.

3. **Poll for completion**
   - Use an **HTTPCaller** inside a custom loop (e.g. with a Tester + Delay + Counter pattern) targeting `https://glbobx-api.onrender.com/jobs/@Value(_job_id)`.
   - Parse the `status` field from each response.
   - Continue looping until status equals `finished` (or handle `failed` / `timeout`).

4. **Download the archive**
   - Once finished, call `https://glbobx-api.onrender.com/jobs/@Value(_job_id)/download` with another **HTTPCaller**.
   - Method: `GET`.
   - Enable *Save Response to File* and choose a destination folder/filename (for example `output/@Value(_job_id).zip`).

5. **Optional: Extract file list**
   - The status response contains an `artefacts` array. You can parse it for logging or to drive additional processing steps after the download.

> Tip: Add a small delay (1–2 seconds) between polls to avoid unnecessary traffic while the conversion runs.
