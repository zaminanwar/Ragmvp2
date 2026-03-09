"""ALM adapter interface — all external ALM systems implement this contract."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


# ── Data classes ─────────────────────────────────────────────────────────────


@dataclass
class ALMSchema:
    """Schema describing an ALM project's work-item types, fields, and link roles."""

    workitem_types: list[dict[str, Any]]
    # [{id, name, fields: [{id, type, enum_values}]}]
    link_roles: list[dict[str, Any]]
    # [{id, name, direction}]
    custom_fields: list[dict[str, Any]]
    # [{id, name, type, allowed_values}]


@dataclass
class WorkItemCreate:
    """Payload to create a single work item in an ALM."""

    type: str
    title: str
    description: str
    fields: dict[str, Any] = field(default_factory=dict)
    parent_id: str | None = None


@dataclass
class WorkItemResult:
    """Result returned after creating a work item."""

    id: str            # ALM-assigned ID
    external_id: str   # our tracking ID
    url: str           # link to item in ALM UI


@dataclass
class WorkItemUpdate:
    """Payload to update fields on an existing work item."""

    id: str
    fields: dict[str, Any] = field(default_factory=dict)


@dataclass
class AdapterConfig:
    """Connection config for an ALM adapter instance."""

    base_url: str
    auth_token: str
    extra: dict[str, Any] = field(default_factory=dict)


# ── Abstract adapter ─────────────────────────────────────────────────────────


class ALMAdapter(ABC):
    """Abstract base for all ALM integrations (Polarion, DOORS, Jira, etc.)."""

    def __init__(self, config: AdapterConfig):
        self.config = config

    @abstractmethod
    async def get_schema(self, project_id: str) -> ALMSchema:
        """Fetch the project's work-item types, fields, and link roles."""
        ...

    @abstractmethod
    async def create_workitems(
        self, project_id: str, items: list[WorkItemCreate]
    ) -> list[WorkItemResult]:
        """Create work items (idempotent upsert where possible)."""
        ...

    @abstractmethod
    async def get_workitems(
        self, project_id: str, module_id: str | None = None
    ) -> list[dict[str, Any]]:
        """Fetch work items, optionally filtered by module."""
        ...

    @abstractmethod
    async def update_workitems(
        self, project_id: str, updates: list[WorkItemUpdate]
    ) -> int:
        """Update fields on existing work items. Returns count updated."""
        ...

    @abstractmethod
    async def create_links(
        self, project_id: str, links: list[dict[str, Any]]
    ) -> None:
        """Create links/traceability between work items."""
        ...
