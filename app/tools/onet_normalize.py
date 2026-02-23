from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Optional

from app.state import RoleModel, RoleRequirement


def _extract_list(payload: Dict[str, Any], keys: List[str]) -> List[Any]:
    """
    Return the first list found at any of the candidate keys.
    """
    for k in keys:
        v = payload.get(k)
        if isinstance(v, list):
            return v
    return []


def _stable_req_id(onet_code: str, req_type: str, label: str, item: Any) -> str:
    raw = json.dumps(item, sort_keys=True, ensure_ascii=True, default=str)
    s = f"ONET::{onet_code}::{req_type}::{label.strip().lower()}::{raw}"
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:24]


def _reqs(
    req_type: str, items: List[Any], label: str, meta_source: str, onet_code: str
) -> List[RoleRequirement]:
    out: List[RoleRequirement] = []
    for it in items:
        out.append(
            RoleRequirement(
                req_type=req_type,
                label=label,
                importance=None,
                source_id=_stable_req_id(onet_code, req_type, label, it),
                metadata={"source": meta_source, "raw": it},
            )
        )
    return out


def normalize_onet_to_role_model(
    *,
    role_title: str,
    onet_code: str,
    version: Optional[str],
    summary: Dict[str, Any],
    skills_payload: Optional[Dict[str, Any]] = None,
    tasks_payload: Optional[Dict[str, Any]] = None,
    tech_payload: Optional[Dict[str, Any]] = None,
    hot_tech_payload: Optional[Dict[str, Any]] = None,
) -> RoleModel:
    reqs: List[RoleRequirement] = []

    if skills_payload:
        items = _extract_list(skills_payload, ["skill", "skills", "element"])
        reqs += _reqs("skill", items, "skills", "onet.skills", onet_code)

    if tasks_payload:
        items = _extract_list(tasks_payload, ["task", "tasks"])
        reqs += _reqs("task", items, "tasks", "onet.tasks", onet_code)

    if tech_payload:
        items = _extract_list(
            tech_payload,
            ["technology_skills", "technology", "tools", "tool", "hot_technology", "hotTechnology"],
        )
        reqs += _reqs("tech", items, "tech", "onet.technology", onet_code)

    if hot_tech_payload:
        items = _extract_list(
            hot_tech_payload,
            ["hot_technology", "hotTechnology", "technology", "tool", "tools"],
        )
        reqs += _reqs("tech", items, "hot_technology", "onet.hot_technology", onet_code)

    return RoleModel(
        role_title=role_title,
        onet_code=onet_code,
        version=version,
        summary=summary,
        requirements=reqs,
    )
