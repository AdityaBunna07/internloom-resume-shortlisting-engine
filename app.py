"""Flask recruiter interface for the InternLoom shortlisting engine."""

from __future__ import annotations

import re
import shutil
import tempfile
import zipfile
from concurrent.futures import ThreadPoolExecutor
from html import unescape
import os
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from flask import Flask, render_template, request
from werkzeug.utils import secure_filename

from parser import SUPPORTED_RESUME_EXTENSIONS, parse_resumes
from scorer import score_for_jd
from skills_vocab import SKILL_ALIASES


app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 500 * 1024 * 1024
MAX_RESUME_COUNT = 200
RUN_DIRECTORY = Path(__file__).parent / "web_runs"
RUN_DIRECTORY.mkdir(exist_ok=True)


def _section_after(text: str, labels: tuple[str, ...], stop_labels: tuple[str, ...]) -> str:
    lines = [line.strip(" •-*\t") for line in text.splitlines()]
    start = next((index for index, line in enumerate(lines) if any(label in line.lower() for label in labels)), None)
    if start is None:
        return ""
    collected = []
    header = lines[start]
    matched_label = next(label for label in labels if label in header.lower())
    inline_content = re.sub(r"^.*?" + re.escape(matched_label) + r"\s*[:=-]?\s*", "", header, flags=re.I).strip()
    if inline_content and inline_content.lower() != matched_label:
        collected.append(inline_content)
    for line in lines[start + 1 :]:
        if any(label in line.lower() for label in stop_labels):
            break
        collected.append(line)
    return "\n".join(collected)


def _skills_in_text(text: str) -> list[str]:
    lowered = text.lower()
    found = []
    for canonical, aliases in SKILL_ALIASES.items():
        for alias in aliases:
            if re.search(r"(?<![a-z0-9+#.])" + re.escape(alias) + r"(?![a-z0-9+#.])", lowered):
                found.append(canonical)
                break
    return sorted(set(found))


def jd_from_text(text: str) -> dict:
    cleaned = text.strip()
    if not cleaned:
        raise ValueError("Paste a job description before running the shortlist.")
    lines = [line.strip() for line in cleaned.splitlines() if line.strip()]
    title_match = re.search(r"(?:role|position|job title)\s*[:=-]\s*([^\n]{3,100})", cleaned, re.I)
    role = title_match.group(1).strip() if title_match else lines[0][:100]
    preferred_text = _section_after(cleaned, ("preferred", "nice to have", "good to have"), ())
    required_text = _section_after(cleaned, ("required", "must have", "minimum qualification"), ("preferred", "nice to have", "good to have"))
    required = _skills_in_text(required_text) if required_text else _skills_in_text(cleaned)
    preferred = _skills_in_text(preferred_text)
    if not required:
        raise ValueError("No supported technical skills were found in the JD. Add skills such as Python, React, SQL, or Docker.")
    cgpa_match = re.search(r"(?:cgpa|gpa)\s*(?:minimum|min)?\s*[:>=-]*\s*(\d(?:\.\d+)?)", cleaned, re.I)
    slots_match = re.search(r"(?:slots?|openings?|positions?)\s*[:=-]?\s*(\d+)", cleaned, re.I)
    return {
        "role": role,
        "required": required,
        "preferred": preferred,
        "cgpa_min": float(cgpa_match.group(1)) if cgpa_match else 0.0,
        "slots": int(slots_match.group(1)) if slots_match else 10,
    }


def jds_from_hiring_plan(text: str) -> list[dict]:
    plans = []
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [part.strip() for part in line.split("|")]
        if len(parts) < 3:
            raise ValueError(f"Hiring plan line {line_number} must use: Role | slots | required skills.")
        role, slot_text, required_text = parts[:3]
        preferred_text = parts[3] if len(parts) > 3 else ""
        cgpa_text = parts[4] if len(parts) > 4 else "0"
        if not role:
            raise ValueError(f"Hiring plan line {line_number} needs a role name.")
        try:
            slots = int(slot_text)
            cgpa_min = float(cgpa_text)
        except ValueError as error:
            raise ValueError(f"Hiring plan line {line_number} has an invalid slot count or CGPA.") from error
        if slots < 1:
            raise ValueError(f"Hiring plan line {line_number} needs at least one slot.")
        required = _skills_in_text(required_text)
        if not required:
            raise ValueError(f"Hiring plan line {line_number} has no supported required skills.")
        plans.append({"role": role, "slots": slots, "required": required, "preferred": _skills_in_text(preferred_text), "cgpa_min": cgpa_min})
    if not plans:
        raise ValueError("Add at least one valid role to the hiring plan, or paste a single JD above.")
    return plans


def _save_uploaded_resumes() -> Path:
    uploads = request.files.getlist("resumes")
    destination = Path(tempfile.mkdtemp(prefix="run_", dir=RUN_DIRECTORY))
    try:
        saved_count = _save_uploads(uploads, destination)
        drive_link = request.form.get("drive_link", "").strip()
        if drive_link:
            saved_count += _download_drive_resumes(drive_link, destination)
        if saved_count > MAX_RESUME_COUNT:
            raise ValueError(f"A review can include up to {MAX_RESUME_COUNT} resumes. Split this batch into smaller groups.")
        if not saved_count:
            raise ValueError("Upload a PDF, DOCX, or DOC resume, choose a folder, or paste a public Google Drive link.")
        return destination
    except Exception:
        shutil.rmtree(destination, ignore_errors=True)
        raise


def _save_uploads(uploads, destination: Path) -> int:
    saved_count = 0
    for upload in uploads:
        filename = secure_filename(upload.filename or "")
        if not filename or Path(filename).suffix.lower() not in SUPPORTED_RESUME_EXTENSIONS:
            continue
        target = _available_path(destination / filename)
        upload.save(target)
        saved_count += 1
    return saved_count


def _available_path(path: Path) -> Path:
    if not path.exists():
        return path
    duplicate_number = 2
    while True:
        candidate = path.with_stem(f"{path.stem}_{duplicate_number}")
        if not candidate.exists():
            return candidate
        duplicate_number += 1


def _detect_document_extension(path: Path) -> str | None:
    signature = path.read_bytes()[:4096]
    if signature.startswith(b"%PDF"):
        return ".pdf"
    if signature.startswith(b"\xd0\xcf\x11\xe0"):
        return ".doc"
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            if "word/document.xml" in archive.namelist():
                return ".docx"
    stripped_signature = signature.lstrip()
    if stripped_signature.startswith(b"<?xml") or stripped_signature.startswith(b"<"):
        return ".xml"
    if signature and b"\x00" not in signature:
        return ".txt"
    return None


def _download_drive_resumes(drive_link: str, destination: Path) -> int:
    parsed_url = urlparse(drive_link)
    host = parsed_url.netloc.lower()
    if host not in {"drive.google.com", "www.drive.google.com", "docs.google.com"}:
        raise ValueError("Use a public Google Drive file or folder link.")
    if "/folders/" in parsed_url.path:
        return _download_public_drive_folder(drive_link, destination)
    file_id = _drive_file_id(parsed_url)
    if not file_id:
        raise ValueError("Use a public Google Drive file link or a shared folder link.")
    temporary_output = destination / "drive_document"
    if not _download_public_drive_file(file_id, temporary_output):
        raise ValueError("The Google Drive file could not be downloaded. Confirm that anyone with the link can view it.")
    extension = _detect_document_extension(temporary_output)
    if not extension:
        temporary_output.unlink(missing_ok=True)
        raise ValueError("The Google Drive file is not a supported PDF, DOCX, DOC, TXT, or XML resume.")
    downloaded_paths = [_available_path(temporary_output.with_suffix(extension))]
    temporary_output.rename(downloaded_paths[0])
    accepted = 0
    for downloaded_path in downloaded_paths:
        path = Path(downloaded_path)
        if not path.exists() or not path.is_file():
            continue
        if path.suffix.lower() not in SUPPORTED_RESUME_EXTENSIONS:
            extension = _detect_document_extension(path)
            if not extension:
                continue
            path = _available_path(path.with_suffix(extension))
            Path(downloaded_path).rename(path)
        accepted += 1
    if not accepted:
        raise ValueError("No supported PDF, DOCX, DOC, TXT, or XML resumes were found in that public Google Drive link.")
    return accepted


def _drive_file_id(parsed_url) -> str | None:
    path_match = re.search(r"/(?:file|document)/d/([A-Za-z0-9_-]+)", parsed_url.path)
    if path_match:
        return path_match.group(1)
    return parse_qs(parsed_url.query).get("id", [None])[0]


def _download_public_drive_folder(drive_link: str, destination: Path) -> int:
    import requests

    folder_id = _drive_folder_id(drive_link)
    api_key = os.getenv("GOOGLE_DRIVE_API_KEY")
    if api_key:
        files = _list_drive_files_with_api(folder_id, api_key)
    else:
        files = _list_drive_files_from_public_page(drive_link, requests)
    if len(files) > MAX_RESUME_COUNT:
        raise ValueError(f"This Drive folder has more than {MAX_RESUME_COUNT} supported resumes. Split it into smaller folders.")
    download_jobs = []
    for filename, file_id in files:
        safe_name = secure_filename(filename) or f"drive_{file_id}.pdf"
        download_jobs.append((file_id, _available_path(destination / safe_name)))
    with ThreadPoolExecutor(max_workers=12) as executor:
        list(executor.map(lambda job: _download_public_drive_file(*job), download_jobs))
    accepted = len([path for path in destination.rglob("*") if path.is_file() and path.suffix.lower() in SUPPORTED_RESUME_EXTENSIONS])
    if not accepted:
        raise ValueError("No supported PDF, DOCX, DOC, TXT, or XML resumes were found in that public Google Drive folder.")
    return accepted


def _drive_folder_id(drive_link: str) -> str:
    match = re.search(r"/folders/([A-Za-z0-9_-]+)", drive_link)
    if not match:
        raise ValueError("The Google Drive folder link is invalid.")
    return match.group(1)


def _list_drive_files_with_api(folder_id: str, api_key: str) -> list[tuple[str, str]]:
    import requests

    files = []
    page_token = None
    while True:
        parameters = {
            "key": api_key,
            "q": f"'{folder_id}' in parents and trashed = false",
            "pageSize": 1000,
            "fields": "nextPageToken,files(id,name,mimeType)",
        }
        if page_token:
            parameters["pageToken"] = page_token
        response = requests.get("https://www.googleapis.com/drive/v3/files", params=parameters, timeout=30)
        if response.status_code in {401, 403}:
            raise ValueError("Google Drive API access was denied. Check GOOGLE_DRIVE_API_KEY and folder sharing permissions.")
        response.raise_for_status()
        payload = response.json()
        for item in payload.get("files", []):
            if Path(item.get("name", "")).suffix.lower() in SUPPORTED_RESUME_EXTENSIONS:
                files.append((item["name"], item["id"]))
        page_token = payload.get("nextPageToken")
        if not page_token:
            return files


def _list_drive_files_from_public_page(drive_link: str, requests) -> list[tuple[str, str]]:
    response = requests.get(drive_link, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
    response.raise_for_status()
    pattern = r'aria-label="([^\"]+\.(?:pdf|docx?|txt|xml))\s+[^\"]*?\s+Shared"[^>]*ssk=\'[^\']+:[^\']+:([A-Za-z0-9_-]+)-0-16\''
    files = []
    seen_ids = set()
    for match in re.finditer(pattern, response.text, re.IGNORECASE):
        filename, file_id = unescape(match.group(1)), match.group(2)
        if file_id not in seen_ids:
            files.append((filename, file_id))
            seen_ids.add(file_id)
    return files


def _download_public_drive_file(file_id: str, output: Path) -> bool:
    import requests

    try:
        response = requests.get(
            "https://drive.usercontent.google.com/download",
            params={"id": file_id, "export": "download", "confirm": "t"},
            headers={"User-Agent": "Mozilla/5.0"},
            stream=True,
            timeout=45,
        )
        response.raise_for_status()
        if "text/html" in response.headers.get("Content-Type", "").lower():
            return False
        with output.open("wb") as file:
            for chunk in response.iter_content(chunk_size=1024 * 128):
                if chunk:
                    file.write(chunk)
        return output.exists() and output.stat().st_size > 0
    except requests.RequestException:
        output.unlink(missing_ok=True)
        return False


@app.get("/")
def index():
    return render_template("index.html")


@app.post("/shortlist")
def shortlist():
    upload_directory = None
    try:
        jd_text = request.form.get("job_description", "")
        hiring_plan = request.form.get("hiring_plan", "")
        jds = jds_from_hiring_plan(hiring_plan) if hiring_plan.strip() else [jd_from_text(jd_text)]
        upload_directory = _save_uploaded_resumes()
        resumes = parse_resumes(upload_directory)
        results = [score_for_jd(resumes, jd) for jd in jds]
        return render_template("index.html", results=results, jd_text=jd_text, hiring_plan=hiring_plan)
    except ValueError as error:
        return render_template("index.html", error=str(error), jd_text=request.form.get("job_description", "")), 400
    except Exception:
        return render_template("index.html", error="The shortlist could not be generated. Check the uploaded PDFs and try again."), 500
    finally:
        if upload_directory and upload_directory.exists():
            shutil.rmtree(upload_directory)


@app.errorhandler(413)
def upload_too_large(_error):
    return render_template("index.html", error="Uploads exceed the 500 MB limit. Use a smaller folder or fewer resumes."), 413


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
