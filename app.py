"""Flask recruiter interface for the InternLoom shortlisting engine."""

from __future__ import annotations

import re
import shutil
import tempfile
from pathlib import Path

from flask import Flask, render_template, request
from werkzeug.utils import secure_filename

from parser import SUPPORTED_RESUME_EXTENSIONS, parse_resumes
from scorer import score_for_jd
from skills_vocab import SKILL_ALIASES


app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 100 * 1024 * 1024
RUN_DIRECTORY = Path(__file__).parent / "web_runs"
RUN_DIRECTORY.mkdir(exist_ok=True)


def _section_after(text: str, labels: tuple[str, ...], stop_labels: tuple[str, ...]) -> str:
    lines = [line.strip(" •-*\t") for line in text.splitlines()]
    start = next((index for index, line in enumerate(lines) if any(label in line.lower() for label in labels)), None)
    if start is None:
        return ""
    collected = []
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


def _save_uploaded_resumes() -> Path:
    uploads = request.files.getlist("resumes")
    destination = Path(tempfile.mkdtemp(prefix="run_", dir=RUN_DIRECTORY))
    saved_count = 0
    for upload in uploads:
        filename = secure_filename(upload.filename or "")
        if not filename or Path(filename).suffix.lower() not in SUPPORTED_RESUME_EXTENSIONS:
            continue
        target = destination / filename
        duplicate_number = 2
        while target.exists():
            target = destination / f"{Path(filename).stem}_{duplicate_number}{Path(filename).suffix}"
            duplicate_number += 1
        upload.save(target)
        saved_count += 1
    if not saved_count:
        raise ValueError("Upload at least one PDF, DOCX, or DOC resume, or select a folder containing them.")
    return destination


@app.get("/")
def index():
    return render_template("index.html")


@app.post("/shortlist")
def shortlist():
    upload_directory = None
    try:
        jd = jd_from_text(request.form.get("job_description", ""))
        upload_directory = _save_uploaded_resumes()
        resumes = parse_resumes(upload_directory)
        result = score_for_jd(resumes, jd)
        candidates = result["shortlist"] + result["reserve"]
        return render_template("index.html", result=result, jd_text=request.form.get("job_description", ""), candidates=candidates)
    except ValueError as error:
        return render_template("index.html", error=str(error), jd_text=request.form.get("job_description", "")), 400
    except Exception:
        return render_template("index.html", error="The shortlist could not be generated. Check the uploaded PDFs and try again."), 500
    finally:
        if upload_directory and upload_directory.exists():
            shutil.rmtree(upload_directory)


@app.errorhandler(413)
def upload_too_large(_error):
    return render_template("index.html", error="Uploads exceed the 100 MB limit. Use a smaller folder or fewer PDFs."), 413


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
