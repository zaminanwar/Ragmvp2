"""Polarion REST API async client with connection pooling, auth, and retry."""

from __future__ import annotations

from typing import Any

import httpx
import structlog

from app.adapters.base import AdapterConfig

logger = structlog.get_logger(__name__)

# Polarion REST API v3 base path
API_BASE = "/polarion/rest/v1"


class PolarionClient:
    """Async HTTP client for the Polarion ALM REST API."""

    def __init__(self, config: AdapterConfig):
        self.config = config
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.config.base_url.rstrip("/"),
                headers={
                    "Authorization": f"Bearer {self.config.auth_token}",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
                timeout=httpx.Timeout(30.0, connect=10.0),
            )
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    # ── Generic request with retry ───────────────────────────────────────

    async def _request(
        self,
        method: str,
        path: str,
        json: dict | None = None,
        params: dict | None = None,
        max_retries: int = 2,
    ) -> dict[str, Any]:
        client = await self._get_client()
        url = f"{API_BASE}{path}"

        for attempt in range(max_retries + 1):
            try:
                response = await client.request(method, url, json=json, params=params)
                response.raise_for_status()
                return response.json() if response.content else {}
            except httpx.HTTPStatusError as e:
                logger.warning(
                    "polarion_http_error",
                    status=e.response.status_code,
                    url=url,
                    attempt=attempt,
                )
                if e.response.status_code >= 500 and attempt < max_retries:
                    import asyncio
                    await asyncio.sleep(2 ** attempt)
                    continue
                raise
            except httpx.RequestError as e:
                logger.warning("polarion_request_error", error=str(e), attempt=attempt)
                if attempt < max_retries:
                    import asyncio
                    await asyncio.sleep(2 ** attempt)
                    continue
                raise

    # ── Convenience methods ──────────────────────────────────────────────

    async def get(self, path: str, params: dict | None = None) -> dict:
        return await self._request("GET", path, params=params)

    async def post(self, path: str, json: dict | None = None) -> dict:
        return await self._request("POST", path, json=json)

    async def patch(self, path: str, json: dict | None = None) -> dict:
        return await self._request("PATCH", path, json=json)

    async def delete(self, path: str) -> dict:
        return await self._request("DELETE", path)

    # ── High-level Polarion operations ───────────────────────────────────

    async def get_project_schema(self, project_id: str) -> dict:
        """Fetch work-item types, custom fields, and link roles for a project."""
        types_resp = await self.get(f"/projects/{project_id}/workitem-types")
        fields_resp = await self.get(f"/projects/{project_id}/workitem-custom-fields")
        links_resp = await self.get(f"/projects/{project_id}/workitem-link-roles")
        return {
            "workitem_types": types_resp.get("data", []),
            "custom_fields": fields_resp.get("data", []),
            "link_roles": links_resp.get("data", []),
        }

    async def create_workitem(self, project_id: str, payload: dict) -> dict:
        """Create a single work item."""
        return await self.post(f"/projects/{project_id}/workitems", json={"data": payload})

    async def get_workitems(
        self, project_id: str, module_id: str | None = None, query: str | None = None
    ) -> list[dict]:
        """Fetch work items, optionally filtered by module or query."""
        params = {}
        if query:
            params["query"] = query
        if module_id:
            resp = await self.get(
                f"/projects/{project_id}/spaces/{module_id}/workitems",
                params=params,
            )
        else:
            resp = await self.get(f"/projects/{project_id}/workitems", params=params)
        return resp.get("data", [])

    async def update_workitem(self, project_id: str, workitem_id: str, fields: dict) -> dict:
        """Update fields on an existing work item."""
        payload = {
            "data": {
                "type": "workitems",
                "id": workitem_id,
                "attributes": fields,
            }
        }
        return await self.patch(f"/projects/{project_id}/workitems/{workitem_id}", json=payload)

    async def create_link(
        self, project_id: str, source_id: str, target_id: str, role: str
    ) -> dict:
        """Create a link between two work items."""
        payload = {
            "data": {
                "type": "workitem-links",
                "attributes": {"role": role},
                "relationships": {
                    "target": {"data": {"type": "workitems", "id": target_id}},
                },
            }
        }
        return await self.post(
            f"/projects/{project_id}/workitems/{source_id}/links", json=payload
        )
