"""Polarion ALM workflow tools — registered as alm.* in the tool registry."""

from __future__ import annotations

import structlog

from app.adapters.base import AdapterConfig, WorkItemCreate, WorkItemUpdate
from app.adapters.polarion.adapter import PolarionAdapter
from app.config import get_settings
from app.workflows.tools.base import BaseTool, ToolInput, ToolOutput

logger = structlog.get_logger(__name__)


def _get_adapter() -> PolarionAdapter:
    settings = get_settings()
    config = AdapterConfig(
        base_url=settings.polarion_base_url or "",
        auth_token=settings.polarion_api_token or "",
    )
    return PolarionAdapter(config)


class AlmGetSchemaTool(BaseTool):
    name = "alm.get_schema"
    description = "Fetch the ALM project schema (work-item types, custom fields, link roles)."
    input_schema = {
        "type": "object",
        "properties": {
            "project_id": {"type": "string"},
        },
        "required": ["project_id"],
    }
    output_schema = {
        "type": "object",
        "properties": {
            "schema": {"type": "object"},
        },
    }

    async def execute(self, tool_input: ToolInput) -> ToolOutput:
        try:
            adapter = _get_adapter()
            try:
                schema = await adapter.get_schema(tool_input.params["project_id"])
                return ToolOutput(
                    success=True,
                    data={
                        "schema": {
                            "workitem_types": schema.workitem_types,
                            "link_roles": schema.link_roles,
                            "custom_fields": schema.custom_fields,
                        }
                    },
                )
            finally:
                await adapter.close()
        except Exception as e:
            logger.exception("alm_get_schema_failed", error=str(e))
            return ToolOutput(success=False, error=str(e))


class AlmCreateWorkitemsTool(BaseTool):
    name = "alm.create_workitems"
    description = "Create work items in the ALM system (idempotent upsert)."
    input_schema = {
        "type": "object",
        "properties": {
            "project_id": {"type": "string"},
            "workitems": {"type": "array"},
        },
        "required": ["project_id", "workitems"],
    }
    output_schema = {
        "type": "object",
        "properties": {
            "polarion_ids": {"type": "array"},
            "module_id": {"type": "string"},
        },
    }

    async def execute(self, tool_input: ToolInput) -> ToolOutput:
        params = tool_input.params
        try:
            adapter = _get_adapter()
            try:
                items = [
                    WorkItemCreate(
                        type=wi.get("type", "requirement"),
                        title=wi.get("title", ""),
                        description=wi.get("description", ""),
                        fields=wi.get("fields", {}),
                        parent_id=wi.get("parent_id"),
                    )
                    for wi in params["workitems"]
                ]
                results = await adapter.create_workitems(params["project_id"], items)
                return ToolOutput(
                    success=True,
                    data={
                        "polarion_ids": [{"id": r.id, "url": r.url} for r in results],
                        "module_id": params.get("module_id", params["project_id"]),
                    },
                )
            finally:
                await adapter.close()
        except Exception as e:
            logger.exception("alm_create_workitems_failed", error=str(e))
            return ToolOutput(success=False, error=str(e))


class AlmGetWorkitemsTool(BaseTool):
    name = "alm.get_workitems"
    description = "Fetch work items from the ALM system."
    input_schema = {
        "type": "object",
        "properties": {
            "project_id": {"type": "string"},
            "module_id": {"type": "string"},
        },
        "required": ["project_id"],
    }
    output_schema = {
        "type": "object",
        "properties": {
            "canonical_requirements": {"type": "array"},
        },
    }

    async def execute(self, tool_input: ToolInput) -> ToolOutput:
        params = tool_input.params
        try:
            adapter = _get_adapter()
            try:
                items = await adapter.get_workitems(
                    params["project_id"],
                    module_id=params.get("module_id"),
                )
                return ToolOutput(
                    success=True,
                    data={"canonical_requirements": items},
                )
            finally:
                await adapter.close()
        except Exception as e:
            logger.exception("alm_get_workitems_failed", error=str(e))
            return ToolOutput(success=False, error=str(e))


class AlmUpdateWorkitemsTool(BaseTool):
    name = "alm.update_workitems"
    description = "Update fields on existing ALM work items."
    input_schema = {
        "type": "object",
        "properties": {
            "project_id": {"type": "string"},
            "updates": {"type": "array"},
        },
        "required": ["project_id", "updates"],
    }
    output_schema = {
        "type": "object",
        "properties": {
            "updated_count": {"type": "integer"},
        },
    }

    async def execute(self, tool_input: ToolInput) -> ToolOutput:
        params = tool_input.params
        try:
            adapter = _get_adapter()
            try:
                updates = [
                    WorkItemUpdate(id=u["id"], fields=u.get("fields", {}))
                    for u in params["updates"]
                ]
                count = await adapter.update_workitems(params["project_id"], updates)
                return ToolOutput(success=True, data={"updated_count": count})
            finally:
                await adapter.close()
        except Exception as e:
            logger.exception("alm_update_workitems_failed", error=str(e))
            return ToolOutput(success=False, error=str(e))


class AlmCreateLinksTool(BaseTool):
    name = "alm.create_links"
    description = "Create traceability links between ALM work items."
    input_schema = {
        "type": "object",
        "properties": {
            "project_id": {"type": "string"},
            "links": {"type": "array"},
        },
        "required": ["project_id", "links"],
    }
    output_schema = {
        "type": "object",
        "properties": {
            "created": {"type": "boolean"},
        },
    }

    async def execute(self, tool_input: ToolInput) -> ToolOutput:
        params = tool_input.params
        try:
            adapter = _get_adapter()
            try:
                await adapter.create_links(params["project_id"], params["links"])
                return ToolOutput(success=True, data={"created": True})
            finally:
                await adapter.close()
        except Exception as e:
            logger.exception("alm_create_links_failed", error=str(e))
            return ToolOutput(success=False, error=str(e))
