"""Polarion ALMAdapter implementation — maps generic adapter interface to Polarion REST API."""

from __future__ import annotations

from typing import Any

import structlog

from app.adapters.base import (
    ALMAdapter,
    ALMSchema,
    AdapterConfig,
    WorkItemCreate,
    WorkItemResult,
    WorkItemUpdate,
)
from app.adapters.polarion.client import PolarionClient

logger = structlog.get_logger(__name__)


class PolarionAdapter(ALMAdapter):
    """ALMAdapter implementation for Siemens Polarion ALM."""

    def __init__(self, config: AdapterConfig):
        super().__init__(config)
        self._client = PolarionClient(config)

    async def close(self) -> None:
        await self._client.close()

    async def get_schema(self, project_id: str) -> ALMSchema:
        raw = await self._client.get_project_schema(project_id)

        workitem_types = []
        for wt in raw.get("workitem_types", []):
            attrs = wt.get("attributes", wt)
            workitem_types.append({
                "id": wt.get("id", attrs.get("id", "")),
                "name": attrs.get("name", attrs.get("id", "")),
                "fields": attrs.get("fields", []),
            })

        link_roles = []
        for lr in raw.get("link_roles", []):
            attrs = lr.get("attributes", lr)
            link_roles.append({
                "id": lr.get("id", attrs.get("id", "")),
                "name": attrs.get("name", ""),
                "direction": attrs.get("direction", "both"),
            })

        custom_fields = []
        for cf in raw.get("custom_fields", []):
            attrs = cf.get("attributes", cf)
            custom_fields.append({
                "id": cf.get("id", attrs.get("id", "")),
                "name": attrs.get("name", ""),
                "type": attrs.get("type", "string"),
                "allowed_values": attrs.get("enumValues", []),
            })

        return ALMSchema(
            workitem_types=workitem_types,
            link_roles=link_roles,
            custom_fields=custom_fields,
        )

    async def create_workitems(
        self, project_id: str, items: list[WorkItemCreate]
    ) -> list[WorkItemResult]:
        results = []
        for item in items:
            payload = {
                "type": "workitems",
                "attributes": {
                    "type": item.type,
                    "title": item.title,
                    "description": {"type": "text/html", "value": item.description},
                    **item.fields,
                },
            }
            if item.parent_id:
                payload["relationships"] = {
                    "parent": {
                        "data": {"type": "workitems", "id": item.parent_id}
                    }
                }

            resp = await self._client.create_workitem(project_id, payload)
            data = resp.get("data", {})
            wi_id = data.get("id", "")
            results.append(
                WorkItemResult(
                    id=wi_id,
                    external_id=item.title,  # use title as tracking reference
                    url=f"{self.config.base_url}/polarion/#/project/{project_id}/workitem?id={wi_id}",
                )
            )

        logger.info("polarion_workitems_created", project=project_id, count=len(results))
        return results

    async def get_workitems(
        self, project_id: str, module_id: str | None = None
    ) -> list[dict[str, Any]]:
        raw_items = await self._client.get_workitems(project_id, module_id=module_id)
        result = []
        for item in raw_items:
            attrs = item.get("attributes", {})
            desc = attrs.get("description", {})
            result.append({
                "id": item.get("id", ""),
                "type": attrs.get("type", ""),
                "title": attrs.get("title", ""),
                "description": desc.get("value", "") if isinstance(desc, dict) else str(desc),
                "status": attrs.get("status", {}).get("id", "") if isinstance(attrs.get("status"), dict) else str(attrs.get("status", "")),
                "fields": {k: v for k, v in attrs.items() if k not in ("type", "title", "description", "status")},
            })
        return result

    async def update_workitems(
        self, project_id: str, updates: list[WorkItemUpdate]
    ) -> int:
        count = 0
        for update in updates:
            try:
                await self._client.update_workitem(project_id, update.id, update.fields)
                count += 1
            except Exception as e:
                logger.error(
                    "polarion_update_failed",
                    workitem_id=update.id,
                    error=str(e),
                )
        logger.info("polarion_workitems_updated", project=project_id, count=count)
        return count

    async def create_links(
        self, project_id: str, links: list[dict[str, Any]]
    ) -> None:
        for link in links:
            try:
                await self._client.create_link(
                    project_id,
                    source_id=link["source_id"],
                    target_id=link["target_id"],
                    role=link["role"],
                )
            except Exception as e:
                logger.error("polarion_link_failed", link=link, error=str(e))
        logger.info("polarion_links_created", project=project_id, count=len(links))
