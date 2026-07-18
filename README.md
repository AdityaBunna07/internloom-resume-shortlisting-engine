# InternLoom Resume Shortlisting Engine

A fast, deterministic Python CLI that parses raw PDF, DOCX, DOC, TXT, and XML resumes and produces ranked, explainable shortlists for multiple job descriptions. It has no LLM/API calls while scoring.

## Setup

```powershell
cd internloom_engine
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

For image-only PDFs, install the Tesseract executable separately and ensure `tesseract` is on `PATH`. Text-based PDFs work without it.

## Run

```powershell
python main.py --resumes .\resumes --jds .\jds.json --out .\output
```

## Recruiter Web UI

```powershell
python app.py
```

Open `http://127.0.0.1:5000`, choose one or more PDFs (or a folder in Chrome/Edge), paste a JD, and generate a sortable shortlist. The **Export CSV** button downloads the current scored table. The UI converts detected JD skills into the same deterministic scoring schema used by the CLI.

The web UI also accepts a public Google Drive file or folder link. InternLoom downloads supported PDF, DOCX, DOC, TXT, and XML resumes into a temporary workspace, scores them, then removes the temporary files after the review.

Each web review accepts up to 200 resumes with a total upload size of 500 MB. Parsing runs in parallel to keep large batches responsive.

For public Google Drive folders with more than 50 items, configure a Google Drive API key on the server before starting InternLoom: `set GOOGLE_DRIVE_API_KEY=your_key`. This enables paginated folder listing up to the 200-resume review limit; without the key, Google only exposes the first page of 50 files to anonymous imports.

For separate role quotas, use the **Multi-role hiring plan** field with one role per line: `Role | slots | required skills | preferred skills (optional) | CGPA minimum (optional)`. InternLoom produces a separate shortlist table and CSV export for each role.

## Public Deployment

GitHub Pages cannot run Flask or process PDF uploads. This repository includes `render.yaml` for a hosted Python deployment: create a new **Web Service** in Render, connect the GitHub repository, and Render detects the build and start commands. Uploaded resumes are removed from the server immediately after a shortlist is generated.

The input folder can contain messy or corrupt PDFs, DOCX files, legacy DOC files, TXT files, and XML resume exports. Each supported document remains represented in output: as a scored candidate, reserve candidate, or failed parse requiring manual review. DOCX, TXT, and XML are parsed directly; legacy DOC extraction uses Microsoft Word, LibreOffice, antiword, or catdoc when available.

## Output

The output directory contains one JSON file per job role, `run_summary.json`, and `parse_quality_report.csv`. Candidate JSON includes the computed 100-point score, confidence, parse quality, exact three reasoning bullets, detailed match evidence, shortlist, reserve list, and failed parses.

## Scoring

`required skills 50% + preferred skills 20% + CGPA fit 15% + practical signals 15%`. Exact and vocabulary-synonym matches receive full credit; documented related technology matches receive half credit. Score results are reproducible for the same PDFs, JDs, and vocabulary.
