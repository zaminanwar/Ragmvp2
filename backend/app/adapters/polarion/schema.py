"""Polarion-specific data models for API request/response shapes."""

from __future__ import annotations

from pydantic import BaseModel, Field


# ── API Response Models ──────────────────────────────────────────────────────


class PolarionField(BaseModel):
    id: str
    label: str
    field_type: str = Field(alias="type")
    required: bool = False
    enum_values: list[str] = []


class PolarionWorkItemType(BaseModel):
    id: str
    name: str
    fields: list[PolarionField] = []


class PolarionLinkRole(BaseModel):
    id: str
    name: str
    direction: str = "both"  # "forward", "backward", "both"


class PolarionCustomField(BaseModel):
    id: str
    name: str
    field_type: str = Field(alias="type")
    allowed_values: list[str] = []


class PolarionSchemaResponse(BaseModel):
    workitem_types: list[PolarionWorkItemType] = []
    link_roles: list[PolarionLinkRole] = []
    custom_fields: list[PolarionCustomField] = []


# ── API Request Models ───────────────────────────────────────────────────────


class PolarionWorkItemCreate(BaseModel):
    type: str
    title: str
    description: str = ""
    fields: dict = {}
    parent_id: str | None = None


class PolarionWorkItemUpdate(BaseModel):
    id: str
    fields: dict = {}


class PolarionLinkCreate(BaseModel):
    source_id: str
    target_id: str
    role: str


# ── API Data Models (items returned from Polarion) ───────────────────────────


class PolarionWorkItem(BaseModel):
    id: str
    type: str
    title: str
    description: str = ""
    status: str = ""
    fields: dict = {}
    url: str = ""
    parent_id: str | None = None
