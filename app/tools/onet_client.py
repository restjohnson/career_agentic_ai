# app/tools/onet_client.py
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

import requests


class OnetClient:
    """
    Minimal O*NET Web Services client (API key auth).
    Base URL examples in docs: services.onetcenter.org + reference manual.
    """

    def __init__(self) -> None:
        self.base = os.getenv("ONET_API_BASE", "https://api-v2.onetcenter.org").rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({
            "Accept": "application/json",
            "X-API-Key": os.environ["ONET_API_KEY"],
        })

    def _get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        url = f"{self.base}/{path.lstrip('/')}"
        r = self.session.get(url, params=params or {}, timeout=30)
        r.raise_for_status()
        return r.json()

    def search_occupations(self, keywords: str, *, limit: int = 5) -> List[Dict[str, Any]]:
        """
        Keyword search occupations.
        """
        data = self._get("/online/search", params={"keyword": keywords})
        occs = data.get("occupation", []) or data.get("occupations", []) or []
        return occs[:limit]

    def get_occupation_summary(self, onet_code: str) -> Dict[str, Any]:
        """
        Pull occupation summary/details from O*NET Online services.
        """
        details = self._get(f"/online/occupations/{onet_code}/")
        summary = details.get("description")
        return summary

    #edited to return only skills
    '''def get_occupation_tasks(self, onet_code: str) -> Dict[str, Any]:
        return self._get(f"/online/occupations/{onet_code}/summary/tasks", params={"start": 1, "end": 10})

    def get_occupation_skills(self, onet_code: str) -> Dict[str, Any]:
        return self._get(f"/online/occupations/{onet_code}/summary/skills", params={"start": 1, "end": 15})'''

    def get_occupation_technology(self, onet_code: str) -> Dict[str, Any]:
        occupation_info = self._get(f"/online/occupations/{onet_code}/summary/technology_skills")
        categories = occupation_info.get("category", [])
        skills_by_category = {}
        for category in categories:
            category_title = category.get("title")
            examples = [item.get("title") for item in category.get("example", [])]
            skills_by_category[category_title] = examples
        return skills_by_category

    def get_hot_technology_skills(self, onet_code: str) -> Dict[str, Any]:
        return self._get(f"/online/occupations/{onet_code}/hot_technology")

    def get_onet_version(self) -> Optional[str]:
        data = self._get("/about/")
        version = data.get("api_version")
        return str(version) if version is not None else None


