"""CLI entry point for the InternLoom Resume Shortlisting Engine."""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

from parser import parse_resumes
from scorer import score_for_jd


def _load_jds(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as file:
        data = json.load(file)
    jds = data.get("jobs", []) if isinstance(data, dict) else data
    if not isinstance(jds, list) or not all(isinstance(jd, dict) for jd in jds):
        raise ValueError("JDs must be a JSON list or an object containing a 'jobs' list.")
    return jds


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_") or "unnamed_role"


def _write_parse_report(output_dir: Path, resumes: list[dict]) -> None:
    with (output_dir / "parse_quality_report.csv").open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=["filename", "full_name", "parse_status", "reason"])
        writer.writeheader()
        for resume in resumes:
            writer.writerow({"filename": resume["filename"], "full_name": resume["full_name"] or "", "parse_status": resume["parse_status"], "reason": resume["parse_reason"] or ""})


def main() -> int:
    argument_parser = argparse.ArgumentParser(description="Deterministic resume shortlisting for PDF resumes.")
    argument_parser.add_argument("--resumes", required=True, help="Folder containing PDF resumes")
    argument_parser.add_argument("--jds", required=True, help="Path to JD JSON file")
    argument_parser.add_argument("--out", required=True, help="Output directory")
    args = argument_parser.parse_args()
    try:
        output_dir = Path(args.out)
        output_dir.mkdir(parents=True, exist_ok=True)
        resumes = parse_resumes(args.resumes)
        jds = _load_jds(Path(args.jds))
        _write_parse_report(output_dir, resumes)
        results = []
        for jd in jds:
            result = score_for_jd(resumes, jd)
            results.append(result)
            with (output_dir / f"{_slug(result['jd_role'])}.json").open("w", encoding="utf-8") as file:
                json.dump(result, file, indent=2, ensure_ascii=False)
            print(f"{result['jd_role']}: {result['candidates_shortlisted']} shortlisted, {len(result['reserve'])} reserve, {result['parse_failures']} failed parse(s)")
        with (output_dir / "run_summary.json").open("w", encoding="utf-8") as file:
            json.dump({"resumes_processed": len(resumes), "job_results": results}, file, indent=2, ensure_ascii=False)
        print(f"Processed {len(resumes)} PDF resume(s). Results written to {output_dir}")
        return 0
    except Exception as error:
        print(f"InternLoom could not complete the run: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
