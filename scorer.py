"""Rule-based, explainable resume scoring."""

from __future__ import annotations

import re
from typing import Any

from skills_vocab import PARTIAL_RELATIONS, SKILL_ALIASES


def _canonical_terms(text: str) -> set[str]:
    lowered = text.lower()
    terms = set()
    for canonical, aliases in SKILL_ALIASES.items():
        if any(re.search(r"(?<![a-z0-9+#.])" + re.escape(alias) + r"(?![a-z0-9+#.])", lowered) for alias in aliases):
            terms.add(canonical)
    if "cloud" in lowered:
        terms.add("cloud")
    if "backend language" in lowered or "backend" in lowered and "language" in lowered:
        terms.add("backend language")
    if "auth" in lowered:
        terms.add("authentication")
    return terms


def _match_requirement(requirement: str, candidate_skills: set[str]) -> tuple[float, str, list[str]]:
    terms = _canonical_terms(requirement)
    if "+" in requirement and len(terms) >= 2:
        evidence = sorted(terms & candidate_skills)
        if len(evidence) == len(terms):
            return 1.0, "exact", evidence
        if evidence:
            return 0.5, "partial", evidence
    if terms & candidate_skills:
        return 1.0, "exact", sorted(terms & candidate_skills)
    related = set().union(*(PARTIAL_RELATIONS.get(term, set()) for term in terms)) if terms else set()
    if "backend language" in terms and related & candidate_skills:
        return 1.0, "exact", sorted(related & candidate_skills)
    if related & candidate_skills:
        return 0.5, "partial", sorted(related & candidate_skills)
    return 0.0, "none", []


def _score_group(requirements: list[str], candidate_skills: set[str]) -> tuple[float, list[dict[str, Any]]]:
    if not requirements:
        return 100.0, []
    matches = []
    for requirement in requirements:
        credit, match_type, evidence = _match_requirement(requirement, candidate_skills)
        matches.append({"requirement": requirement, "credit": credit, "match_type": match_type, "evidence": evidence})
    return 100 * sum(item["credit"] for item in matches) / len(matches), matches


def _reasoning(required_matches: list[dict[str, Any]], cgpa: float | None, cgpa_min: float, practical_score: float, resume: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    exact = [item for item in required_matches if item["match_type"] == "exact"]
    partial = [item for item in required_matches if item["match_type"] == "partial"]
    missing = [item["requirement"] for item in required_matches if item["match_type"] == "none"]
    if exact:
        names = ", ".join(item["requirement"] for item in exact[:3])
        reasons.append(f"Matches required skills: {names}.")
    if partial:
        names = ", ".join(item["requirement"] for item in partial[:2])
        reasons.append(f"Partial match for {names}; verify depth during interview.")
    if missing:
        reasons.append(f"Missing required evidence for: {', '.join(missing[:2])}.")
    if cgpa is None:
        reasons.append("CGPA was not extracted, so academic fit receives no credit.")
    elif cgpa >= cgpa_min:
        reasons.append(f"CGPA {cgpa:.2f}/10 meets the {cgpa_min:.1f} minimum.")
    else:
        reasons.append(f"CGPA {cgpa:.2f}/10 is below the {cgpa_min:.1f} minimum.")
    project_count, experience_count = len(resume["projects"]), len(resume["experience"])
    if practical_score:
        reasons.append(f"Practical signal: {project_count} project(s) and {experience_count} experience entry(s).")
    else:
        reasons.append("No project or experience entries were reliably extracted.")
    if cgpa and cgpa >= 8.5 and project_count == 0:
        reasons.append("Signal conflict: strong academic record, weak practical evidence.")
    elif cgpa and cgpa < cgpa_min and project_count >= 2:
        reasons.append("Signal conflict: strong practical evidence, weaker academic fit.")
    degree = (resume.get("degree_branch") or "").lower()
    technical = any(word in degree for word in ("computer", "information", "software", "electronics", "technology"))
    if len(exact) == len(required_matches) and degree and not technical:
        reasons.append("Signal conflict: strong role fit but degree background may be unrelated.")
    return reasons[:3] if len(reasons) >= 3 else reasons + ["Limited extracted evidence; validate the original resume manually."] * (3 - len(reasons))


def score_resume(resume: dict[str, Any], jd: dict[str, Any]) -> dict[str, Any]:
    if resume["parse_status"] == "Failed":
        return {"name": resume.get("full_name") or resume["filename"], "file": resume["filename"], "score": None, "confidence": "None", "parse_quality": "Failed", "reasoning": ["Failed Parse — recommend manual review."] * 3}
    skills = set(resume.get("skills", []))
    required_pct, required_matches = _score_group(jd.get("required", []), skills)
    preferred_pct, preferred_matches = _score_group(jd.get("preferred", []), skills)
    cgpa = resume.get("cgpa")
    cgpa_min = float(jd.get("cgpa_min", 0))
    cgpa_score = 0.0 if cgpa is None or cgpa < cgpa_min else min(100.0, 70.0 + (cgpa - cgpa_min) / max(0.1, 10 - cgpa_min) * 30.0)
    practical_score = min(100.0, len(resume.get("projects", [])) * 25.0 + len(resume.get("experience", [])) * 35.0)
    score = round(required_pct * 0.50 + preferred_pct * 0.20 + cgpa_score * 0.15 + practical_score * 0.15, 2)
    ambiguous = any(item["match_type"] == "partial" for item in required_matches + preferred_matches)
    confidence = "Medium" if resume["parse_status"] == "Partial" or ambiguous else "High"
    return {
        "name": resume.get("full_name") or resume["filename"],
        "file": resume["filename"],
        "score": score,
        "confidence": confidence,
        "parse_quality": resume["parse_status"],
        "reasoning": _reasoning(required_matches, cgpa, cgpa_min, practical_score, resume),
        "match_details": {"required": required_matches, "preferred": preferred_matches, "cgpa_fit_score": round(cgpa_score, 2), "practical_signal_score": round(practical_score, 2)},
    }


def score_for_jd(resumes: list[dict[str, Any]], jd: dict[str, Any]) -> dict[str, Any]:
    scored = [score_resume(resume, jd) for resume in resumes]
    failures = [{"file": item["file"], "reason": "Failed Parse — recommend manual review."} for item in scored if item["score"] is None]
    ranked = sorted((item for item in scored if item["score"] is not None), key=lambda item: item["score"], reverse=True)
    slots = max(0, int(jd.get("slots", 0)))
    shortlist, reserve = ranked[:slots], ranked[slots:]
    return {
        "jd_role": jd.get("role", "Unnamed role"),
        "candidates_evaluated": len(resumes),
        "candidates_shortlisted": len(shortlist),
        "score_cutoff_used": shortlist[-1]["score"] if shortlist else None,
        "parse_failures": len(failures),
        "shortlist": shortlist,
        "reserve": reserve,
        "failed_parses": failures,
    }
