"""Knowledge base configuration — swap models/stores via `use:` like DeerFlow models/tools."""

from __future__ import annotations

import os
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class KnowledgeTransformConfig(BaseModel):
    """Extra IngestionPipeline TransformComponent assembled via ``use:``."""

    model_config = ConfigDict(extra="allow")

    use: str


class KnowledgeIngestConfig(BaseModel):
    """Chunking / node parser — LlamaIndex only; swap via ``use`` / strategy, no domain hardcoding."""

    model_config = ConfigDict(extra="allow")

    # auto: MarkdownNodeParser when markdown headings/tables; else HierarchicalNodeParser
    # markdown: MarkdownNodeParser | hierarchical: HierarchicalNodeParser | use: honor node_parser_use only
    strategy: str = "auto"
    # Smaller leaves improve precision for policy/SOP docs (industry Small-to-Big).
    chunk_sizes: list[int] = Field(default_factory=lambda: [1024, 256])
    chunk_overlap: int = 64
    # Override parser class, e.g. llama_index.core.node_parser:SentenceSplitter
    node_parser_use: str = ""
    # Prefix document title before embed
    title_prefix: bool = True
    # Strip data-URI / huge base64 blobs before embed (generic media sanitize)
    media_sanitize: bool = True
    # Annotate metadata.block = text|table|image from content shape
    annotate_block: bool = True
    # Optional extra transforms after the node parser
    transforms: list[KnowledgeTransformConfig] = Field(default_factory=list)


def _azure_provider(provider: str = "") -> bool:
    return (provider or "").strip().lower() == "azure"


class KnowledgeEmbedConfig(BaseModel):
    """Embedding via LlamaIndex ``use:`` — ctor kwargs pass through (same idea as models[])."""

    model_config = ConfigDict(extra="allow")

    use: str = ""
    # Only used when ``use`` is empty: azure → AzureOpenAIEmbedding, else OpenAIEmbedding.
    provider: str = ""
    model: str = ""
    embed_dim: int = 1536
    # LlamaIndex OpenAIEmbedding batch size. DashScope compatible APIs cap at 10.
    embed_batch_size: int = 10
    api_key: str = ""
    # Prefer ctor names: api_base (OpenAI) / azure_endpoint (Azure). ``base_url`` is a legacy alias.
    api_base: str = ""
    azure_endpoint: str = ""
    base_url: str = ""
    api_version: str = ""
    deployment_name: str = ""

    def resolved(self) -> KnowledgeEmbedConfig:
        provider = self.provider or os.getenv("EMBEDDING_PROVIDER", "")
        model = self.model or os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
        use = self.use or ("llama_index.embeddings.azure_openai:AzureOpenAIEmbedding" if _azure_provider(provider) else "llama_index.embeddings.openai:OpenAIEmbedding")
        # Class path decides Azure vs OpenAI fields (not EMBEDDING_PROVIDER alone).
        is_azure = "azure_openai" in use.lower()
        api_base = self.api_base
        azure_endpoint = self.azure_endpoint
        if self.base_url:
            if is_azure and not azure_endpoint:
                azure_endpoint = self.base_url
            elif not is_azure and not api_base:
                api_base = self.base_url
        if not api_base and not azure_endpoint:
            env_base = os.getenv("EMBEDDING_BASE_URL", "") or os.getenv("OPENAI_BASE_URL", "")
            if is_azure:
                azure_endpoint = env_base
            else:
                api_base = env_base
        data = self.model_dump()
        data.update(
            {
                "use": use,
                "provider": provider or ("azure" if is_azure else "openai"),
                "model": model,
                "api_key": self.api_key or os.getenv("EMBEDDING_API_KEY", "") or os.getenv("OPENAI_API_KEY", ""),
                "api_base": api_base,
                "azure_endpoint": azure_endpoint,
                "base_url": "",
                "api_version": self.api_version or os.getenv("EMBEDDING_API_VERSION", "") or ("2024-09-01-preview" if is_azure else ""),
                "deployment_name": self.deployment_name or os.getenv("EMBEDDING_DEPLOYMENT", "") or (model if is_azure else ""),
            }
        )
        return KnowledgeEmbedConfig(**data)

    def ctor_kwargs(self) -> dict[str, Any]:
        """Kwargs for LlamaIndex embed class — matches YAML keys to ctor (minus bookkeeping)."""
        cfg = self.resolved()
        data = cfg.model_dump(exclude={"use", "provider", "embed_dim", "base_url"}, exclude_none=True)
        out = {k: v for k, v in data.items() if v != ""}
        use = cfg.use.lower()
        # OpenAIEmbedding validates `model` against an enum; OpenAI-compatible gateways
        # (e.g. DashScope text-embedding-v3) must pass the id via `model_name`.
        if "azure_openai" not in use and "openai" in use and "model" in out:
            out["model_name"] = out.pop("model")
        # Pass vector size so OpenAI-compatible APIs (DashScope) match pgvector column dim.
        if cfg.embed_dim and "dimensions" not in out:
            out["dimensions"] = cfg.embed_dim
        return out


class KnowledgeVectorStoreConfig(BaseModel):
    """Vector backend. Switch with ``type``: chroma | pgvector | milvus.

    Connection fields by type (unused fields are ignored):

    - ``pgvector`` / ``postgres``: ``connection_string`` (preferred) or
      ``host`` / ``port`` / ``database`` / ``user`` / ``password``;
      empty → fall back to ``DATABASE_URL``
    - ``chroma``: ``persist_dir`` (local path under runtime home when relative)
    - ``milvus``: ``uri``, optional ``token``, ``collection_name``
    """

    model_config = ConfigDict(extra="allow")

    type: str = "chroma"  # chroma | postgres | pgvector | milvus
    # Shared / pgvector
    connection_string: str = ""
    host: str = ""
    port: int = 5432
    database: str = ""
    user: str = ""
    password: str = ""
    table_name: str = "knowledge_embed"
    embed_dim: int = 1536
    # Chroma
    persist_dir: str = ""
    # Milvus
    uri: str = ""
    token: str = ""
    collection_name: str = "deerflow_knowledge"


class KnowledgeQueryLlmConfig(BaseModel):
    """Optional LlamaIndex LLM for QueryFusionRetriever rewrite — YAML ``use:`` + ctor kwargs."""

    model_config = ConfigDict(extra="allow")

    enabled: bool = False
    # When true (default), enable multi-query if an API key is resolvable even when enabled=false.
    auto: bool = True
    use: str = "llama_index.llms.openai:OpenAI"
    model: str = "gpt-4o-mini"
    api_key: str = ""
    api_base: str = ""
    azure_endpoint: str = ""
    api_version: str = ""
    deployment_name: str = ""

    def ctor_kwargs(self) -> dict[str, Any]:
        data = self.model_dump(exclude={"use", "enabled", "auto"}, exclude_none=True)
        return {k: v for k, v in data.items() if v != ""}


class KnowledgeRetrievalConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    hybrid: bool = True
    bm25: bool = True
    bm25_tokenizer: str = "jieba"  # jieba | jieba_search | whitespace
    fusion_num_queries: int = 3
    fusion_mode: str = "reciprocal_rerank"
    retrieve_n: int = 40
    rerank: bool = True
    rerank_use: str = "llama_index.postprocessor.dashscope_rerank:DashScopeRerank"
    rerank_model: str = "qwen3-rerank"
    rerank_top_n: int = 0  # 0 = use top_k
    top_k: int = 8
    parent_expand: bool = True
    # Applied after rerank (rerank scores are calibrated). RRF pre-rerank scores are ignored.
    score: float = 0.35
    similarity_cutoff: float | None = None  # legacy alias → score
    # Evidence snippet length (strip media + window around query terms)
    snippet_max_chars: int = 1200
    query_llm: KnowledgeQueryLlmConfig = Field(default_factory=KnowledgeQueryLlmConfig)

    @model_validator(mode="after")
    def _coalesce_retrieval_score(self) -> KnowledgeRetrievalConfig:
        if self.similarity_cutoff is not None:
            self.score = self.similarity_cutoff
        else:
            self.similarity_cutoff = self.score
        return self


class KnowledgeKindConfig(BaseModel):
    """Document content type id (display labels live in frontend i18n)."""

    model_config = ConfigDict(extra="ignore")

    id: str = Field(min_length=1, description="Machine id stored on documents, e.g. policy")


class KnowledgeTagConfig(BaseModel):
    """Tag id for document metadata / lane filters (display labels in frontend i18n)."""

    model_config = ConfigDict(extra="ignore")

    id: str = Field(min_length=1, description="Machine tag id, e.g. statute")


class KnowledgeTagGroupConfig(BaseModel):
    """UI bundle of tags (e.g. national regulations lane); labels in frontend i18n."""

    model_config = ConfigDict(extra="ignore")

    id: str = Field(min_length=1, description="Tag group id for UI toggles, e.g. national")
    tags: list[str] = Field(default_factory=list, description="Member tag ids")


class ScenarioLaneConfig(BaseModel):
    """One parallel retrieval lane within a scenario."""

    model_config = ConfigDict(extra="ignore")

    id: str = ""
    kinds: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    budget: int | None = None
    optional: bool = False

    @model_validator(mode="before")
    @classmethod
    def _legacy_tags_any(cls, value: Any) -> Any:
        if isinstance(value, dict) and "tags_any" in value and "tags" not in value:
            value = dict(value)
            value["tags"] = value.pop("tags_any")
        return value


class KnowledgeScenarioConfig(BaseModel):
    """Retrieval profile for a product scenario (list item with ``type``)."""

    model_config = ConfigDict(extra="ignore")

    description: str = ""
    type: str = Field(min_length=1, description="Scenario pack id, e.g. general-qa")
    top_k: int | None = None
    score: float | None = None
    kinds: list[str] = Field(default_factory=list, description="Shorthand: one lane per kind")
    lanes: list[ScenarioLaneConfig] = Field(default_factory=list)
    merge_mode: str = Field(default="slot_then_rrf", description="score | slot_then_rrf")
    fusion_num_queries: int | None = None
    # Legacy aliases from older YAML
    score_threshold: float | None = None
    similarity_cutoff: float | None = None

    @model_validator(mode="after")
    def _coalesce_score(self) -> KnowledgeScenarioConfig:
        if self.score is None:
            self.score = self.score_threshold if self.score_threshold is not None else self.similarity_cutoff
        if self.score_threshold is None:
            self.score_threshold = self.score
        if self.similarity_cutoff is None:
            self.similarity_cutoff = self.score
        return self

    @property
    def effective_score(self) -> float | None:
        return self.score


def _default_scenarios() -> list[KnowledgeScenarioConfig]:
    """Minimal bootstrap when YAML omits ``knowledge.scenarios``.

    Product packs live in config.yaml (machine ``type`` only). Display labels
    are frontend i18n — never put locale text in Python defaults.
    """
    return [KnowledgeScenarioConfig(type="general-qa", top_k=8, score=0.35)]


def _normalize_scenarios(value: Any) -> list[dict[str, Any] | KnowledgeScenarioConfig]:
    """Accept list[{type,...}] or legacy dict{type: {...}}."""
    if value is None:
        return []
    if isinstance(value, dict):
        out: list[dict[str, Any]] = []
        for key, raw in value.items():
            item = dict(raw or {}) if isinstance(raw, dict) else {}
            item.setdefault("type", str(key))
            out.append(item)
        return out
    if isinstance(value, list):
        return value
    raise TypeError(f"scenarios must be a list or dict, got {type(value)!r}")


class KnowledgeAuthzConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    system_admin_is_space_admin: bool = True
    allow_user_create_space: bool = True


class KnowledgeParseConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    timeout_seconds: int = 120
    model_name: str | None = Field(
        default=None,
        description="config.models slot for document parse (None = default chat model)",
    )


def _normalize_catalog_ids(value: Any, *, field: str) -> list[dict[str, Any] | str]:
    """Accept list[id] or list[{id}] (legacy label fields ignored)."""
    if value is None:
        return []
    if not isinstance(value, list):
        raise TypeError(f"{field} must be a list, got {type(value)!r}")
    out: list[dict[str, Any] | str] = []
    for item in value:
        if isinstance(item, str):
            sid = item.strip()
            if sid:
                out.append({"id": sid})
        elif isinstance(item, dict):
            out.append(item)
        else:
            raise TypeError(f"{field} entries must be str or dict, got {type(item)!r}")
    return out


def _normalize_kinds(value: Any) -> list[dict[str, Any] | KnowledgeKindConfig | str]:
    """Accept list[id] or list[{id}] (legacy label fields ignored)."""
    if value is None:
        return []
    normalized = _normalize_catalog_ids(value, field="kinds")
    out: list[dict[str, Any] | KnowledgeKindConfig | str] = []
    for item in normalized:
        if isinstance(item, KnowledgeKindConfig):
            out.append(item)
        else:
            out.append(item)
    return out


class KnowledgeConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    enabled: bool = True
    parse: KnowledgeParseConfig = Field(default_factory=KnowledgeParseConfig)
    ingest: KnowledgeIngestConfig = Field(default_factory=KnowledgeIngestConfig)
    embed: KnowledgeEmbedConfig = Field(default_factory=KnowledgeEmbedConfig)
    vector_store: KnowledgeVectorStoreConfig = Field(default_factory=KnowledgeVectorStoreConfig)
    retrieval: KnowledgeRetrievalConfig = Field(default_factory=KnowledgeRetrievalConfig)
    kinds: list[KnowledgeKindConfig] = Field(
        default_factory=list,
        description="Optional global kind catalog; empty = no global whitelist (use space/scenario)",
    )
    tags: list[KnowledgeTagConfig] = Field(
        default_factory=list,
        description="Optional global tag catalog; empty = union of tag_groups and scenario lanes",
    )
    tag_groups: list[KnowledgeTagGroupConfig] = Field(
        default_factory=list,
        description="UI tag bundles (machine ids; labels in frontend i18n)",
    )
    scenarios: list[KnowledgeScenarioConfig] = Field(default_factory=_default_scenarios)
    authz: KnowledgeAuthzConfig = Field(default_factory=KnowledgeAuthzConfig)

    @field_validator("scenarios", mode="before")
    @classmethod
    def _scenarios_list(cls, value: Any) -> Any:
        return _normalize_scenarios(value)

    @field_validator("kinds", mode="before")
    @classmethod
    def _kinds_list(cls, value: Any) -> Any:
        return _normalize_kinds(value)

    @field_validator("tags", mode="before")
    @classmethod
    def _tags_list(cls, value: Any) -> Any:
        return _normalize_catalog_ids(value, field="tags")

    def scenario_by_type(self, scenario_type: str | None) -> KnowledgeScenarioConfig | None:
        want = (scenario_type or "").strip()
        if not want:
            return None
        for item in self.scenarios:
            if item.type == want:
                return item
        return None

    def kind_by_id(self, kind_id: str | None) -> KnowledgeKindConfig | None:
        want = (kind_id or "").strip()
        if not want:
            return None
        for item in self.kinds:
            if item.id == want:
                return item
        return None

    def configured_kind_ids(self) -> set[str]:
        return {item.id for item in self.kinds if item.id}

    def configured_tag_ids(self) -> set[str]:
        return {item.id for item in self.tags if item.id}

    def configured_tag_group_ids(self) -> set[str]:
        return {item.id for item in self.tag_groups if item.id}


_knowledge_config: KnowledgeConfig = KnowledgeConfig()


def get_knowledge_config() -> KnowledgeConfig:
    return _knowledge_config


def set_knowledge_config(config: KnowledgeConfig) -> None:
    global _knowledge_config
    _knowledge_config = config


def load_knowledge_config_from_dict(config_dict: dict) -> None:
    set_knowledge_config(KnowledgeConfig.model_validate(config_dict or {}))
