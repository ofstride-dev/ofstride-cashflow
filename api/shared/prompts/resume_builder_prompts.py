"""Prompt templates for the Resume Builder.

These map the Resume-Matcher prompt surface onto our LLM factory's
``agenerate_json`` (JSON-mode) interface. All prompts force strict JSON output.
"""

from __future__ import annotations

PARSE_SYSTEM_PROMPT = (
    "You are a JSON extraction engine. Output only valid JSON, no explanations "
    "or markdown fences. Extract the resume into the exact schema provided."
)

RESUME_SCHEMA_EXAMPLE = """{
  "personalInfo": {
    "name": "Jane Doe",
    "title": "Senior Backend Engineer",
    "email": "jane@example.com",
    "phone": "+1-555-0100",
    "location": "Bengaluru, IN",
    "website": "https://janedoe.dev",
    "linkedin": "https://linkedin.com/in/janedoe",
    "github": "https://github.com/janedoe"
  },
  "summary": "Backend engineer with 6 years building scalable Python microservices.",
  "workExperience": [
    {
      "id": 1,
      "title": "Senior Backend Engineer",
      "company": "TechCorp",
      "location": "Bengaluru",
      "years": "Jun 2020 - Present",
      "description": ["Built event-driven services handling 5M events/day.", "Led migration to Azure."]
    }
  ],
  "education": [
    {"id": 1, "institution": "IIT Madras", "degree": "B.Tech Computer Science", "years": "2014 - 2018"}
  ],
  "personalProjects": [
    {"id": 1, "name": "OpenRSS", "role": "Creator", "years": "2022", "description": ["Self-hosted RSS reader."]}
  ],
  "additional": {
    "technicalSkills": ["Python", "FastAPI", "PostgreSQL", "Azure", "Docker"],
    "languages": ["English", "Hindi"],
    "certificationsTraining": ["Azure Solutions Architect (AZ-305)"],
    "awards": ["Hackathon Winner 2023"]
  },
  "sectionMeta": [],
  "customSections": {}
}"""

PARSE_RESUME_PROMPT = """You are extracting a structured resume from raw text.

Return ONLY a JSON object matching this exact schema (use empty strings/lists when a field is absent):

{schema}

Rules:
- Preserve exact dates as they appear (e.g. "Jun 2020 - Present"). Do NOT collapse to years only.
- Each workExperience/personalProjects description is a list of concise bullet strings (strip bullet markers).
- technicalSkills is a flat list of skills (lowercase not required).
- Do not invent content not present in the source text.
- If the resume lacks a section, return it as an empty list/string, not null.

Resume text:
---
{resume_text}
---
"""


EXTRACT_JD_KEYWORDS_PROMPT = """Extract structured keywords from this job description.

Return ONLY a JSON object:
{{
  "required_skills": ["..."],
  "preferred_skills": ["..."],
  "job_title": "...",
  "seniority": "...",
  "key_responsibilities": ["..."]
}}

Rules:
- required_skills: hard skills/tools/technologies the candidate must have.
- preferred_skills: nice-to-have skills.
- Keep each skill short (1-3 words). No duplicates.

Job description:
---
{jd_text}
---
"""


IMPROVE_DIFF_PROMPT = """You tailor a resume to match a job description via targeted diffs.

Given the current resume JSON and the JD keywords, return ONLY a JSON object:
{{
  "changes": [
    {{
      "path": "workExperience[0].description[1]",
      "action": "replace",
      "original": "current text at that path (for replace/append verification)",
      "value": "new text",
      "reason": "why this better matches the JD"
    }}
  ],
  "strategy_notes": "one-line summary of the tailoring strategy"
}}

Actions:
- "replace": replace the text at `path` with `value`. `original` MUST equal the current text.
- "append": append `value` to a list at `path` (e.g. workExperience[0].description). `original` is the last current item (string) or null.
- "reorder": for a string-list path, `original` is the full current list and `value` is the reordered list.
- "add_skill": append a skill to additional.technicalSkills (path "additional.technicalSkills"). `value` is the skill string.

Rules:
- NEVER fabricate experience. Only rephrase/reorder/inject keywords that are ALREADY supported by the master resume facts.
- Prefer injecting keywords that appear in the master resume (technicalSkills, descriptions) over rewriting.
- Paths use 0-based indices. Verify `original` exactly matches the current content; if unsure, omit the change.
- Keep 3-10 high-value changes. Quality over quantity.

Current resume JSON:
{resume_json}

JD keywords:
{jd_keywords}
"""
