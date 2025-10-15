"""Streamlit web UI for converting GLB files to OBJ format."""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from convert import convert_glb_bytes

st.set_page_config(page_title="GLB → OBJ Converter", page_icon="🧊")

st.title("GLB → OBJ Converter")
st.write(
	"Upload a `.glb` asset to receive a ZIP containing the converted `.obj`, `.mtl`, and any referenced textures."
)

with st.sidebar:
	st.header("How it works")
	st.markdown(
		"""
		1. Upload a GLB file using the form below.
		2. The file is processed with the existing batch converter.
		3. Download the generated artefacts as a ZIP archive.

		> ⚠️ Large models may take a while to convert, depending on server resources.
		"""
	)

uploaded = st.file_uploader("Select a GLB file", type=["glb"], accept_multiple_files=False)

if uploaded is not None:
	try:
		with st.spinner("Converting…"):
			archive_bytes, artefacts = convert_glb_bytes(uploaded.getvalue(), uploaded.name or "model.glb")

		display_name = uploaded.name or "model.glb"
		st.success(f"Converted `{display_name}` successfully! {len(artefacts)} artefact(s) generated:")
		st.code("\n".join(artefacts) or "(no files listed)")

		zip_name = f"{Path(display_name).stem or 'model'}.zip"
		st.download_button(
			label="Download OBJ ZIP",
			data=archive_bytes,
			file_name=zip_name,
			mime="application/zip",
		)
	except ValueError as exc:
		st.error(str(exc))
	except RuntimeError as exc:
		st.error(str(exc))
	except Exception as exc:  # noqa: BLE001
		st.exception(exc)
else:
	st.info("Drop a GLB file above to begin.")
