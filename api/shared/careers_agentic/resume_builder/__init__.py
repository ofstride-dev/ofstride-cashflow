"""Resume Builder — AI-tailored resume + ATS scoring for the careers admin.

Phase 1 surface:
  - Parse an uploaded master resume (PDF/DOCX) into structured ResumeData.
  - Tailor the master resume to a pasted job description (diff-based changes).
  - Compute an ATS-style score breakdown (keyword / skills / section).
  - Persist master resumes + tailored versions with history.

Replatformed from the open-source Resume-Matcher (Apache-2.0) onto our
existing shared infrastructure (llm_factory, blob_rest, careers stores).
"""

from __future__ import annotations

from .resume_schema import (
    AdditionalInfo,
    CustomSection,
    CustomSectionItem,
    Education,
    Experience,
    ImproveDiffResult,
    PersonalInfo,
    Project,
    ResumeChange,
    ResumeData,
    SectionMeta,
    SectionType,
    DEFAULT_SECTION_META,
    normalize_resume_data,
)
from .ats_scorer import compute_ats_score
from .resume_parser import parse_resume_document, parse_resume_to_json
from .resume_tailor import tailor_resume_to_jd, TailorResult

__all__ = [
    "AdditionalInfo",
    "CustomSection",
    "CustomSectionItem",
    "Education",
    "Experience",
    "ImproveDiffResult",
    "PersonalInfo",
    "Project",
    "ResumeChange",
    "ResumeData",
    "SectionMeta",
    "SectionType",
    "DEFAULT_SECTION_META",
    "normalize_resume_data",
    "compute_ats_score",
    "parse_resume_document",
    "parse_resume_to_json",
    "tailor_resume_to_jd",
    "TailorResult",
]
