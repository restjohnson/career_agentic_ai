from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from app.state import GapItem, LearningResource, StudentConstraints
from app.tools.supabase_repo import SupabaseRepo

# ---------------------------------------------------------------------------
# Academic level bucketing (for cache key grouping)
# ---------------------------------------------------------------------------

_LEVEL_BUCKET: Dict[str, str] = {
    "freshman":             "early_undergrad",
    "sophomore":            "early_undergrad",
    "junior":               "late_undergrad",
    "senior":               "late_undergrad",
    "grad":                 "graduate",
    "bootcamp":             "professional",
    "self_taught":          "professional",
    "working_professional": "professional",
}

def _bucket(level: str) -> str:
    return _LEVEL_BUCKET.get(level, "professional")


# ---------------------------------------------------------------------------
# Cache key
# ---------------------------------------------------------------------------

def _cache_key(skill_summary: str, resource_type: str, academic_level: str) -> str:
    raw = f"{skill_summary.lower().strip()}|{resource_type}|{_bucket(academic_level)}"
    return hashlib.sha256(raw.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Internship eligibility
# ---------------------------------------------------------------------------

def _internship_eligible(gap: GapItem, constraints: StudentConstraints) -> bool:
    level = constraints.academic_level
    if level == "working_professional":
        return False
    if level in ("freshman", "sophomore"):
        return gap.gap_type == "partial"
    if level in ("junior", "senior"):
        return gap.proficiency >= 2
    if level == "grad":
        return gap.gap_type not in ("no_evidence", "met")
    if level in ("bootcamp", "self_taught"):
        return gap.gap_type == "partial" and gap.proficiency >= 2
    return False


# ---------------------------------------------------------------------------
# Resource type selection per gap
# ---------------------------------------------------------------------------

def determine_resource_types(gap: GapItem, constraints: StudentConstraints) -> List[str]:
    """Select which resource types to retrieve based on gap characteristics and constraints."""
    types: List[str] = []
    mode  = constraints.preferred_learning_mode
    level = constraints.academic_level

    if gap.gap_type == "no_evidence":
        types.append("online_course" if mode == "structured" else "tutorial")
        types.append("project")
    elif gap.gap_type == "claimed_only":
        types.append("project")
    elif gap.gap_type == "partial":
        types.append("project")
    elif gap.gap_type == "optional_gap":
        types.append("tutorial")
    elif gap.gap_type == "met":
        return []

    if level in ("junior", "senior", "grad") and "project" in types:
        types.append("open_source")

    if level == "working_professional":
        types.append("certification")

    if _internship_eligible(gap, constraints):
        types.append("internship")

    return types


def determine_prereq_resource_types(constraints: StudentConstraints) -> List[str]:
    """Foundational prerequisites are always concept-focused."""
    return ["online_course" if constraints.preferred_learning_mode == "structured" else "tutorial"]


# ---------------------------------------------------------------------------
# LLM-based resource generation
# ---------------------------------------------------------------------------

class _ResourceRaw(BaseModel):
    title: str
    provider: Optional[str] = None
    url: Optional[str] = None
    estimated_hours: Optional[int] = None
    is_free: Optional[bool] = None


_LEVEL_LABELS: Dict[str, str] = {
    "early_undergrad": "beginner undergraduate",
    "late_undergrad":  "intermediate undergraduate",
    "graduate":        "graduate-level",
    "professional":    "professional / post-graduate",
}

_GENERATE_SYSTEM = """\
You are a learning resource curator with expert knowledge of online education platforms.

Recommend ONE specific, real learning resource for the given skill and resource type.
Use your knowledge of well-known platforms: Coursera, edX, freeCodeCamp, MDN, YouTube,
Khan Academy, MIT OpenCourseWare, Codecademy, fast.ai, The Odin Project, GitHub, etc.

Rules:
- title: the actual title of the resource (not a generic description)
- provider: the platform or publisher (e.g. "Coursera", "freeCodeCamp", "YouTube")
- url: the real URL if you are confident it exists; otherwise null
- estimated_hours: realistic total learning time in hours (null if unclear)
- is_free: true if free, false if paid, null if unknown
- Do NOT invent resources. If you cannot name a specific real resource for this combination,
  return the most applicable well-known resource you do know exists.
"""


def _generate_resource(
    skill_summary: str,
    resource_type: str,
    constraints: StudentConstraints,
    proficiency: int,
) -> Optional[LearningResource]:
    level_label = _LEVEL_LABELS.get(_bucket(constraints.academic_level), "intermediate")
    depth       = "beginner" if proficiency <= 1 else "intermediate"

    user_msg = (
        f"Skill: {skill_summary}\n"
        f"Resource type: {resource_type}\n"
        f"Student level: {level_label} ({depth} depth)\n"
        f"Learning mode preference: {constraints.preferred_learning_mode}\n\n"
        f"Recommend the single best real {resource_type} resource for learning '{skill_summary}' "
        f"at {depth} level for a {level_label} student."
    )

    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.0)
    llm_struct = llm.with_structured_output(_ResourceRaw, method="json_schema", strict=True)

    try:
        raw: _ResourceRaw = llm_struct.invoke([
            {"role": "system", "content": _GENERATE_SYSTEM},
            {"role": "user",   "content": user_msg},
        ])
    except Exception:
        return None

    valid_types = {
        "tutorial", "project", "open_source", "workshop",
        "certification", "internship", "online_course", "documentation",
    }
    rtype = resource_type if resource_type in valid_types else "tutorial"

    return LearningResource(
        title=raw.title,
        provider=raw.provider,
        url=raw.url,
        resource_type=rtype,
        estimated_hours=raw.estimated_hours,
        is_free=raw.is_free,
        addresses_gap=skill_summary,
    )


# ---------------------------------------------------------------------------
# Main retrieval function
# ---------------------------------------------------------------------------

def retrieve_resources_for_gap(
    gap_summary: str,
    proficiency: int,
    resource_types: List[str],
    constraints: StudentConstraints,
    repo: SupabaseRepo,
) -> List[LearningResource]:
    """
    Retrieve learning resources for a gap. Checks Supabase cache first;
    falls back to LLM generation on cache miss.
    Failures are non-fatal — missing resources are skipped silently.
    """
    resources: List[LearningResource] = []

    for rtype in resource_types:
        key = _cache_key(gap_summary, rtype, constraints.academic_level)

        # Cache hit
        try:
            cached = repo.get_cached_resource(key)
        except Exception:
            cached = None
        if cached:
            try:
                resources.append(LearningResource(**cached["resource_data"]))
            except Exception:
                pass
            continue

        # LLM generation
        resource = _generate_resource(gap_summary, rtype, constraints, proficiency)
        if not resource:
            continue

        # Persist to cache (30-day TTL)
        expires_at = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
        try:
            repo.upsert_cached_resource(key, resource.model_dump(), expires_at)
        except Exception:
            pass  # cache write failure is non-fatal

        resources.append(resource)

    return resources
