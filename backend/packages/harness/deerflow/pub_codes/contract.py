"""HTTP contracts for the generic code-table (pub_codes) API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class PubCodeEntryResponse(BaseModel):
    id: str
    domain: str
    type_key: str
    code: str
    label: str = ""
    parent_code: str = ""
    attrs: dict[str, Any] = Field(default_factory=dict)
    sort_order: int = 0
    enabled: bool = True


class CodeTableFlatBundleResponse(BaseModel):
    """Flat pub_codes rows for a domain (legal, etc.)."""

    domain: str
    items: list[PubCodeEntryResponse] = Field(default_factory=list)


class CodeTableDomainSummaryResponse(BaseModel):
    domain: str
    type_key: str = ""
    label: str = ""
    parent_code: str = ""
    entry_count: int = 0


class CreateCodeTableDomainRequest(BaseModel):
    domain: str = Field(min_length=1)
    code: str = Field(min_length=1)
    label: str = ""
    type_key: str = ""
    attrs: dict[str, Any] = Field(default_factory=dict)


class UpdateCodeTableDomainRequest(BaseModel):
    type_key: str = Field(min_length=1)
    label: str = Field(min_length=1)
    new_type_key: str = ""


class CodeTableDomainsListResponse(BaseModel):
    items: list[CodeTableDomainSummaryResponse] = Field(default_factory=list)
    domains: list[str] = Field(default_factory=list)


class DeleteCodeTableDomainResponse(BaseModel):
    domain: str
    deleted: int = 0


class UpsertCodeTableEntryRequest(BaseModel):
    type_key: str = Field(min_length=1)
    code: str = Field(min_length=1)
    label: str = Field(min_length=1)
    parent_code: str = ""
    attrs: dict[str, Any] = Field(default_factory=dict)


class UpdateCodeTableEntryRequest(BaseModel):
    type_key: str = Field(min_length=1)
    label: str = Field(min_length=1)
    parent_code: str = ""
    attrs: dict[str, Any] = Field(default_factory=dict)
