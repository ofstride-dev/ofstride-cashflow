"""Pydantic models for the Resume Builder domain (ported from Resume-Matcher).

Trimmed to the Phase 1 data contract: personal info, summary, work experience,
education, projects, additional info (skills/languages/certs/awards), section
metadata, custom sections, and the diff-based improvement models. The
conversational wizard, cover-letter, and interview-prep models are deferred.

Field names match the frontend `ResumeData` shape so the ATS scorer (which
reads `resume["additional"]["technicalSkills"]`, etc.) works against the
validated `model_dump()` output without translation.
"""

from __future__ import annotations

import copy
import re
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

_TEXT_VALUE_KEYS = (
    "text", "summary", "description", "value", "content",
    "title", "subtitle", "name", "label",
)
_BULLET_PREFIX_RE = re.compile(r"^\s*(?:[-*•]+|\d+[.)])\s*")


def _extract_text_fragments(value: Any, depth: int = 0, max_depth: int = 10) -> list[str]:
    if depth >= max_depth or value is None:
        return []
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, (int, float)):
        return [str(value)]
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            out.extend(_extract_text_fragments(item, depth + 1, max_depth))
        return out
    if isinstance(value, dict):
        out: list[str] = []
        for key in _TEXT_VALUE_KEYS:
            if key in value:
                out.extend(_extract_text_fragments(value.get(key), depth + 1, max_depth))
        if out:
            return out
        for nested in value.values():
            out.extend(_extract_text_fragments(nested, depth + 1, max_depth))
        return out
    return []


def _coerce_text(value: Any, joiner: str = " ") -> str:
    return joiner.join(_extract_text_fragments(value)).strip()


def _coerce_optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = _coerce_text(value)
    return text or None


def _split_description_lines(value: str) -> list[str]:
    items: list[str] = []
    for raw_line in re.split(r"\r?\n+", value):
        line = _BULLET_PREFIX_RE.sub("", raw_line.strip())
        if line:
            items.append(line)
    return items


def _coerce_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return _split_description_lines(value)
    if isinstance(value, list):
        items: list[str] = []
        for entry in value:
            if isinstance(entry, str):
                items.extend(_split_description_lines(entry))
                continue
            coerced = _coerce_text(entry)
            if coerced:
                items.append(coerced)
        return items
    coerced = _coerce_text(value)
    return [coerced] if coerced else []


def _coerce_description_styles(value: Any) -> list[Literal["bullet", "plain"]]:
    if not isinstance(value, list):
        return []
    return ["plain" if entry == "plain" else "bullet" for entry in value]


def _align_description_styles(
    description: list[str],
    description_styles: list[Literal["bullet", "plain"]],
) -> list[Literal["bullet", "plain"]]:
    return [
        description_styles[index] if index < len(description_styles) else "bullet"
        for index, _ in enumerate(description)
    ]


class SectionType(str, Enum):
    PERSONAL_INFO = "personalInfo"
    TEXT = "text"
    ITEM_LIST = "itemList"
    STRING_LIST = "stringList"


class PersonalInfo(BaseModel):
    name: str = ""
    title: str = ""
    email: str = ""
    phone: str = ""
    location: str = ""
    website: str | None = None
    linkedin: str | None = None
    github: str | None = None


class Experience(BaseModel):
    id: int = 0
    title: str = ""
    company: str = ""
    location: str | None = None
    years: str = ""
    description: list[str] = Field(default_factory=list)
    descriptionStyles: list[Literal["bullet", "plain"]] = Field(default_factory=list)

    @field_validator("description", mode="before")
    @classmethod
    def _normalize_description(cls, value: Any) -> list[str]:
        return _coerce_string_list(value)

    @field_validator("descriptionStyles", mode="before")
    @classmethod
    def _normalize_description_styles(cls, value: Any) -> list[Literal["bullet", "plain"]]:
        return _coerce_description_styles(value)

    @model_validator(mode="after")
    def _sync_description_styles(self) -> "Experience":
        self.descriptionStyles = _align_description_styles(self.description, self.descriptionStyles)
        return self


class Education(BaseModel):
    id: int = 0
    institution: str = ""
    degree: str = ""
    years: str = ""
    description: str | None = None

    @field_validator("description", mode="before")
    @classmethod
    def _normalize_description(cls, value: Any) -> str | None:
        return _coerce_optional_text(value)


class Project(BaseModel):
    id: int = 0
    name: str = ""
    role: str = ""
    years: str = ""
    github: str | None = None
    website: str | None = None
    description: list[str] = Field(default_factory=list)
    descriptionStyles: list[Literal["bullet", "plain"]] = Field(default_factory=list)

    @field_validator("description", mode="before")
    @classmethod
    def _normalize_description(cls, value: Any) -> list[str]:
        return _coerce_string_list(value)

    @field_validator("descriptionStyles", mode="before")
    @classmethod
    def _normalize_description_styles(cls, value: Any) -> list[Literal["bullet", "plain"]]:
        return _coerce_description_styles(value)

    @model_validator(mode="after")
    def _sync_description_styles(self) -> "Project":
        self.descriptionStyles = _align_description_styles(self.description, self.descriptionStyles)
        return self


class AdditionalInfo(BaseModel):
    technicalSkills: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)
    certificationsTraining: list[str] = Field(default_factory=list)
    awards: list[str] = Field(default_factory=list)

    @field_validator(
        "technicalSkills", "languages", "certificationsTraining", "awards", mode="before",
    )
    @classmethod
    def _normalize_string_fields(cls, value: Any) -> list[str]:
        return _coerce_string_list(value)


class SectionMeta(BaseModel):
    id: str
    key: str
    displayName: str
    sectionType: SectionType
    isDefault: bool = True
    isVisible: bool = True
    order: int = 0


class CustomSectionItem(BaseModel):
    id: int = 0
    title: str = ""
    subtitle: str | None = None
    location: str | None = None
    years: str = ""
    description: list[str] = Field(default_factory=list)
    descriptionStyles: list[Literal["bullet", "plain"]] = Field(default_factory=list)

    @field_validator("description", mode="before")
    @classmethod
    def _normalize_description(cls, value: Any) -> list[str]:
        return _coerce_string_list(value)

    @field_validator("descriptionStyles", mode="before")
    @classmethod
    def _normalize_description_styles(cls, value: Any) -> list[Literal["bullet", "plain"]]:
        return _coerce_description_styles(value)

    @model_validator(mode="after")
    def _sync_description_styles(self) -> "CustomSectionItem":
        self.descriptionStyles = _align_description_styles(self.description, self.descriptionStyles)
        return self


class CustomSection(BaseModel):
    sectionType: SectionType
    items: list[CustomSectionItem] | None = None
    strings: list[str] | None = None
    text: str | None = None

    @field_validator("items", mode="before")
    @classmethod
    def _normalize_items(cls, value: Any) -> Any:
        if value is None:
            return None
        if not isinstance(value, list):
            return value
        result = []
        for i, item in enumerate(value):
            if isinstance(item, str):
                result.append({"id": i + 1, "title": item})
            else:
                result.append(item)
        return result

    @field_validator("strings", mode="before")
    @classmethod
    def _normalize_strings(cls, value: Any) -> list[str] | None:
        if value is None:
            return None
        return _coerce_string_list(value)

    @field_validator("text", mode="before")
    @classmethod
    def _normalize_text(cls, value: Any) -> str | None:
        return _coerce_optional_text(value)


DEFAULT_SECTION_META: list[dict[str, Any]] = [
    {"id": "personalInfo", "key": "personalInfo", "displayName": "Personal Info", "sectionType": SectionType.PERSONAL_INFO, "isDefault": True, "isVisible": True, "order": 0},
    {"id": "summary", "key": "summary", "displayName": "Summary", "sectionType": SectionType.TEXT, "isDefault": True, "isVisible": True, "order": 1},
    {"id": "workExperience", "key": "workExperience", "displayName": "Experience", "sectionType": SectionType.ITEM_LIST, "isDefault": True, "isVisible": True, "order": 2},
    {"id": "education", "key": "education", "displayName": "Education", "sectionType": SectionType.ITEM_LIST, "isDefault": True, "isVisible": True, "order": 3},
    {"id": "personalProjects", "key": "personalProjects", "displayName": "Projects", "sectionType": SectionType.ITEM_LIST, "isDefault": True, "isVisible": True, "order": 4},
    {"id": "additional", "key": "additional", "displayName": "Skills & Awards", "sectionType": SectionType.STRING_LIST, "isDefault": True, "isVisible": True, "order": 5},
]


def normalize_resume_data(data: dict[str, Any]) -> dict[str, Any]:
    """Ensure resume data has section metadata (migration helper)."""
    if not data.get("sectionMeta"):
        data["sectionMeta"] = copy.deepcopy(DEFAULT_SECTION_META)
    if "customSections" not in data:
        data["customSections"] = {}
    return data


class ResumeData(BaseModel):
    """Complete structured resume data."""

    personalInfo: PersonalInfo = Field(default_factory=PersonalInfo)
    summary: str = ""
    workExperience: list[Experience] = Field(default_factory=list)
    education: list[Education] = Field(default_factory=list)
    personalProjects: list[Project] = Field(default_factory=list)
    additional: AdditionalInfo = Field(default_factory=AdditionalInfo)
    sectionMeta: list[SectionMeta] = Field(default_factory=list)
    customSections: dict[str, CustomSection] = Field(default_factory=dict)

    @field_validator("summary", mode="before")
    @classmethod
    def _normalize_summary(cls, value: Any) -> str:
        return _coerce_text(value)


class ResumeChange(BaseModel):
    """A single targeted change the LLM wants to make to the resume."""

    path: str = Field(description="Dot+bracket path, e.g. 'workExperience[0].description[1]'")
    action: Literal["replace", "append", "reorder", "add_skill"]
    original: str | list[str] | None = Field(
        default=None,
        description="Current text at path — for verification. May be a list for "
        "the reorder action; only used for text verification of replace/append.",
    )
    value: str | list[str] = Field(description="New content")
    reason: str = Field(description="Why this change helps match the JD")

    @model_validator(mode="after")
    def _list_original_only_for_reorder(self) -> "ResumeChange":
        if isinstance(self.original, list) and self.action != "reorder":
            raise ValueError("'original' may be a list only for the reorder action")
        return self


class ImproveDiffResult(BaseModel):
    """LLM output: a list of targeted resume changes."""

    changes: list[ResumeChange] = Field(default_factory=list)
    strategy_notes: str = Field(default="")



