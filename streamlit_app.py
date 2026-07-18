"""Streamlit Community Cloud entry point for InternLoom."""

from __future__ import annotations

import csv
import shutil
import tempfile
from io import StringIO
from pathlib import Path

import streamlit as st
from werkzeug.utils import secure_filename

from app import MAX_RESUME_COUNT, _available_path, _download_drive_resumes, jd_from_text, jds_from_hiring_plan
from parser import SUPPORTED_RESUME_EXTENSIONS, parse_resumes
from scorer import score_for_jd


def _save_streamlit_uploads(uploaded_files, destination: Path) -> int:
    saved_count = 0
    for uploaded_file in uploaded_files:
        filename = secure_filename(uploaded_file.name)
        if not filename or Path(filename).suffix.lower() not in SUPPORTED_RESUME_EXTENSIONS:
            continue
        target = _available_path(destination / filename)
        target.write_bytes(uploaded_file.getbuffer())
        saved_count += 1
    return saved_count


def _to_csv(candidates: list[dict]) -> str:
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["Candidate", "File", "Score", "Confidence", "Parse Quality", "Reasoning"])
    for candidate in candidates:
        writer.writerow([
            candidate["name"],
            candidate["file"],
            candidate["score"],
            candidate["confidence"],
            candidate["parse_quality"],
            " | ".join(candidate["reasoning"]),
        ])
    return output.getvalue()


def _run_shortlist(uploaded_files, drive_link: str, single_jd: str, hiring_plan: str) -> list[dict]:
    with tempfile.TemporaryDirectory(prefix="internloom_") as temporary_directory:
        destination = Path(temporary_directory)
        saved_count = _save_streamlit_uploads(uploaded_files, destination)
        if drive_link.strip():
            saved_count += _download_drive_resumes(drive_link.strip(), destination)
        if not saved_count:
            raise ValueError("Upload resumes or paste a public Google Drive file or folder link.")
        if saved_count > MAX_RESUME_COUNT:
            raise ValueError(f"A review can include up to {MAX_RESUME_COUNT} resumes.")
        jds = jds_from_hiring_plan(hiring_plan) if hiring_plan.strip() else [jd_from_text(single_jd)]
        resumes = parse_resumes(destination)
        return [score_for_jd(resumes, jd) for jd in jds]


def _show_role_result(result: dict) -> None:
    candidates = result["shortlist"] + result["reserve"]
    st.subheader(result["jd_role"])
    first, second, third = st.columns(3)
    first.metric("Shortlisted", result["candidates_shortlisted"])
    second.metric("Cutoff score", result["score_cutoff_used"] if result["score_cutoff_used"] is not None else "—")
    third.metric("Parse flags", result["parse_failures"])
    rows = []
    for candidate in candidates:
        rows.append({
            "Candidate": candidate["name"],
            "Score": candidate["score"],
            "Confidence": candidate["confidence"],
            "Parse quality": candidate["parse_quality"],
            "Decision": "Shortlist" if candidate in result["shortlist"] else "Reserve",
            "Reasoning": "\n".join(candidate["reasoning"]),
        })
    st.dataframe(rows, use_container_width=True, hide_index=True)
    st.download_button(
        f"Download {result['jd_role']} CSV",
        _to_csv(candidates),
        file_name=f"{result['jd_role'].lower().replace(' ', '_')}_shortlist.csv",
        mime="text/csv",
    )
    if result["failed_parses"]:
        st.warning(f"{result['parse_failures']} resume(s) require manual review because parsing failed.")


st.set_page_config(page_title="InternLoom Recruiter Console", page_icon="IL", layout="wide")
st.title("InternLoom Resume Shortlisting Engine")
st.caption("Deterministic, explainable resume shortlists for up to 200 resumes per review.")

with st.sidebar:
    st.header("Review setup")
    uploaded_files = st.file_uploader(
        "Upload resumes",
        type=["pdf", "docx", "doc", "txt", "xml"],
        accept_multiple_files=True,
        help="Upload up to 200 supported resume documents.",
    )
    drive_link = st.text_input("Or import a public Google Drive link", placeholder="https://drive.google.com/drive/folders/...")
    st.caption("Files are processed temporarily and removed after scoring.")

single_jd = st.text_area(
    "Single job description",
    placeholder="Frontend Developer\nRequired: React, JavaScript, REST API, Git\nPreferred: TypeScript, Jest\nCGPA minimum: 6.5\nSlots: 5",
    height=180,
)
hiring_plan = st.text_area(
    "Multi-role hiring plan (optional)",
    placeholder="Web Developer | 10 | HTML, CSS, JavaScript, React, Git\nFrontend Developer | 5 | React, JavaScript, REST API, Git | TypeScript, Jest | 6.5",
    help="Format: Role | slots | required skills | preferred skills (optional) | CGPA minimum (optional)",
    height=150,
)

if st.button("Generate shortlists", type="primary", use_container_width=True):
    try:
        with st.spinner("Downloading, parsing, and scoring resumes…"):
            st.session_state["internloom_results"] = _run_shortlist(uploaded_files, drive_link, single_jd, hiring_plan)
    except ValueError as error:
        st.error(str(error))
    except Exception:
        st.error("The shortlist could not be generated. Verify the documents and try again.")

results = st.session_state.get("internloom_results")
if results:
    st.divider()
    st.header("Role-by-role shortlists")
    tabs = st.tabs([result["jd_role"] for result in results])
    for tab, result in zip(tabs, results):
        with tab:
            _show_role_result(result)
