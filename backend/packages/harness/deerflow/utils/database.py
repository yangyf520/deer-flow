"""SQLAlchemy DSN helpers and read-only queries for Text-to-SQL skills.

Configure via environment variables:

- ``DB_DSN`` — full SQLAlchemy URL (recommended)
- Or minimal mode: ``DB_TYPE`` + ``DB_HOST`` + ``DB_USERNAME`` + ``DB_PASSWORD``
  (+ optional ``DB_PORT``, ``DB_NAME``)

Supported ``DB_TYPE`` values: ``postgres``, ``mysql``, ``sqlserver``.

Scope / safety:

- ``DB_SCHEMA``, ``DB_TABLE_PREFIXES``, ``DB_TABLE_NAMES`` — limit visible tables
- ``DB_MAX_TABLES``, ``DB_MAX_COLUMNS`` — cap schema introspection size
- Queries must be a single ``SELECT`` / ``WITH`` statement (enforced in ``query()``).
"""

from __future__ import annotations

import hashlib
import logging
import os
import time
from collections.abc import Callable
from datetime import date, datetime
from datetime import time as dt_time
from decimal import Decimal
from typing import Any
from urllib.parse import quote_plus

logger = logging.getLogger(__name__)


def is_business_db_configured() -> bool:
    """True when ``DB_DSN`` or ``DB_TYPE`` is set (business warehouse, not app sqlite)."""
    return bool((os.getenv("DB_DSN") or "").strip() or (os.getenv("DB_TYPE") or "").strip())


def extract_select_sql(text: str) -> str:
    """Extract one SELECT/WITH statement; reject writes and multi-statement SQL."""
    if not text or not str(text).strip():
        raise RuntimeError("Model returned empty SQL.")

    raw = str(text).strip()
    block = raw
    if "```" in raw:
        parts = raw.split("```")
        for idx in range(1, len(parts), 2):
            candidate = parts[idx].strip()
            if candidate.lower().startswith("sql"):
                candidate = candidate[3:].lstrip()
            candidate = candidate.strip()
            if candidate:
                block = candidate
                break

    statement = block.strip().rstrip(";").strip()
    if not statement:
        raise RuntimeError("Model returned empty SQL.")

    upper = statement.upper()
    if not (upper.startswith("SELECT") or upper.startswith("WITH")):
        raise RuntimeError("Model did not produce a SELECT statement.")

    forbidden = (
        "INSERT ",
        "UPDATE ",
        "DELETE ",
        "DROP ",
        "ALTER ",
        "CREATE ",
        "TRUNCATE ",
        "GRANT ",
        "REVOKE ",
        "EXEC ",
        "EXECUTE ",
        "MERGE ",
    )
    for token in forbidden:
        if token in upper:
            raise RuntimeError(f"Forbidden SQL keyword detected: {token.strip()}")

    if ";" in statement:
        raise RuntimeError("Multiple SQL statements are not allowed.")

    return f"{statement};"

_DSN_BUILDERS: dict[str, Callable[[], str]] = {}


def int_env(name: str, default: int | None = None) -> int | None:
    """Parse an integer env var; return ``default`` when unset/blank/invalid."""
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def sql_fingerprint(sql: str) -> str:
    """Fingerprint SQL for logs without leaking full text."""
    return hashlib.sha256(sql.encode("utf-8", errors="ignore")).hexdigest()[:16]


def _minimal_params() -> dict[str, str]:
    host = (os.getenv("DB_HOST") or "").strip()
    user = (os.getenv("DB_USERNAME") or "").strip()
    password = os.getenv("DB_PASSWORD") or ""
    if not host or not user or not password:
        raise RuntimeError(
            "Database not configured. Set DB_DSN, or DB_TYPE with DB_HOST, "
            "DB_USERNAME, DB_PASSWORD (optional DB_PORT, DB_NAME)."
        )
    port = (os.getenv("DB_PORT") or "").strip()
    name = (os.getenv("DB_NAME") or os.getenv("DB_DATABASE") or "").strip()
    return {"host": host, "user": user, "password": password, "port": port, "name": name}


def _dsn_postgres() -> str:
    p = _minimal_params()
    port = p["port"] or "5432"
    name = p["name"] or "postgres"
    user = quote_plus(p["user"])
    password = quote_plus(p["password"])
    return f"postgresql+psycopg://{user}:{password}@{p['host']}:{port}/{name}"


def _dsn_mysql() -> str:
    p = _minimal_params()
    port = p["port"] or "3306"
    name = p["name"] or ""
    user = quote_plus(p["user"])
    password = quote_plus(p["password"])
    base = f"mysql+pymysql://{user}:{password}@{p['host']}:{port}"
    return f"{base}/{name}" if name else base


def _dsn_sqlserver() -> str:
    p = _minimal_params()
    port = p["port"] or "1433"
    name = p["name"]
    if not name:
        raise RuntimeError("DB_NAME is required for DB_TYPE=sqlserver (set DB_DSN to override).")
    user = quote_plus(p["user"])
    password = quote_plus(p["password"])
    return f"mssql+pytds://{user}:{password}@{p['host']}:{port}/{name}"


_DSN_BUILDERS = {
    "postgres": _dsn_postgres,
    "postgresql": _dsn_postgres,
    "pg": _dsn_postgres,
    "mysql": _dsn_mysql,
    "sqlserver": _dsn_sqlserver,
    "mssql": _dsn_sqlserver,
}


def build_dsn() -> str:
    """Return DSN from ``DB_DSN`` or ``DB_TYPE`` + ``_DSN_BUILDERS``."""
    explicit = (os.getenv("DB_DSN") or os.getenv("DEERFLOW_DB_DEFAULT_DSN") or "").strip()
    if explicit:
        return explicit

    db_type = (os.getenv("DB_TYPE") or "").strip().lower()
    if not db_type:
        raise RuntimeError(
            "Set DB_DSN or DB_TYPE (postgres|mysql|sqlserver). See deerflow.utils.database."
        )
    builder = _DSN_BUILDERS.get(db_type)
    if builder is None:
        supported = ", ".join(sorted({k for k in _DSN_BUILDERS if k not in {"pg", "mssql"}}))
        raise RuntimeError(f"Unsupported DB_TYPE={db_type!r}. Supported: {supported}, or set DB_DSN.")
    return builder()


def mssql_skip_schema(schema: str) -> bool:
    """Return True for SQL Server system schemas."""
    upper = schema.upper()
    return upper in {"INFORMATION_SCHEMA", "GUEST", "SYS"}


def mssql_allowed_schemas() -> list[str] | None:
    raw = (os.getenv("DB_SCHEMA") or "").strip()
    if not raw:
        return None
    return [s.strip() for s in raw.split(",") if s.strip()]


def allowed_table_prefixes() -> list[str] | None:
    raw = (os.getenv("DB_TABLE_PREFIXES") or "").strip()
    if not raw:
        return None
    return [s.strip() for s in raw.split(",") if s.strip()]


def allowed_table_names() -> list[str] | None:
    raw = (os.getenv("DB_TABLE_NAMES") or "").strip()
    if not raw:
        return None
    names = [s.strip() for s in raw.split(",") if s.strip()]
    if len(names) == 1 and names[0].isdigit():
        logger.warning("DB_TABLE_NAMES looks numeric (%r); ignoring. Use DB_MAX_TABLES for limits.", names[0])
        return None
    return names


def table_matches_name(table: str, allowlist: list[str]) -> bool:
    lower = table.lower()
    return any(lower == name.lower() for name in allowlist)


def table_matches_prefix(table: str, prefixes: list[str]) -> bool:
    lower = table.lower()
    return any(lower.startswith(prefix.lower()) for prefix in prefixes)


def effective_schema_table_cap() -> int | None:
    """Tables to include in schema introspection: env cap, allowlist size, or unlimited."""
    env_cap = int_env("DB_MAX_TABLES")
    if env_cap is not None:
        return env_cap
    explicit = allowed_table_names()
    if explicit:
        return len(explicit)
    return None


def _ensure_sqlalchemy_dialect(dsn: str) -> None:
    """Import third-party SQLAlchemy dialect packages when needed."""
    if dsn.startswith("mssql+pytds"):
        try:
            import sqlalchemy_pytds  # noqa: F401
        except ImportError as e:
            raise ImportError(
                "SQL Server requires sqlalchemy-pytds. "
                "Install: cd backend && uv sync --all-packages --extra text2sql"
            ) from e


def load_schema_summary(*, max_columns_per_table: int | None = None) -> str:
    """Return a compact schema listing for LLM prompts."""
    try:
        from sqlalchemy import create_engine, inspect
    except ImportError as e:
        raise ImportError("Missing dependency: sqlalchemy (install deerflow-harness)") from e

    max_cols = max_columns_per_table if max_columns_per_table is not None else (int_env("DB_MAX_COLUMNS") or 200)
    max_tables = effective_schema_table_cap()
    prefixes = allowed_table_prefixes()
    explicit_names = allowed_table_names()
    db_schema = mssql_allowed_schemas()

    dsn = build_dsn()
    started = time.monotonic()
    _ensure_sqlalchemy_dialect(dsn)
    engine = create_engine(dsn, pool_pre_ping=True)
    inspector = inspect(engine)
    dialect_name = getattr(getattr(engine, "dialect", None), "name", "") or ""

    logger.info(
        "schema_filters: dialect=%s db_schema=%s table_prefixes=%s table_names=%s max_tables=%s max_cols=%s",
        dialect_name,
        db_schema,
        prefixes,
        explicit_names,
        max_tables,
        max_cols,
    )

    lines: list[str] = []
    if dialect_name.startswith("mssql"):
        lines.append(
            "SQL Server: use qualified names [schema].[table]; bracket identifiers with "
            "non-ASCII characters or spaces."
        )

    table_full_names: list[str] = []

    if dialect_name.startswith("mssql"):
        schemas = db_schema if db_schema else [s for s in inspector.get_schema_names() if not mssql_skip_schema(s)]
        for schema in schemas:
            for table in inspector.get_table_names(schema=schema):
                full = f"{schema}.{table}"
                if prefixes and not table_matches_prefix(table, prefixes):
                    continue
                if explicit_names and not table_matches_name(table, explicit_names):
                    continue
                table_full_names.append(full)
    else:
        for table in inspector.get_table_names():
            if prefixes and not table_matches_prefix(table, prefixes):
                continue
            if explicit_names and not table_matches_name(table, explicit_names):
                continue
            table_full_names.append(table)

    table_full_names.sort()
    if max_tables is not None:
        table_full_names = table_full_names[:max_tables]

    if explicit_names:
        matched = {t.split(".")[-1].lower() for t in table_full_names}
        missing = [n for n in explicit_names if n.lower() not in matched]
        if missing:
            logger.warning("schema_tables missing from DB_TABLE_NAMES: %s", missing[:20])

    logger.info(
        "schema_tables: total=%s sample=%s",
        len(table_full_names),
        table_full_names[:10],
    )

    for full_name in table_full_names:
        if "." in full_name and dialect_name.startswith("mssql"):
            schema, table = full_name.split(".", 1)
            cols = inspector.get_columns(table, schema=schema)
        else:
            cols = inspector.get_columns(full_name)

        col_parts: list[str] = []
        for col in cols[:max_cols]:
            name = col.get("name", "?")
            ctype = str(col.get("type", "?"))
            nullable = col.get("nullable", True)
            suffix = "" if nullable else " NOT NULL"
            col_parts.append(f"{name} ({ctype}{suffix})")
        if len(cols) > max_cols:
            col_parts.append(f"... +{len(cols) - max_cols} more columns")

        lines.append(f"\nTable: {full_name}")
        lines.append(f"  Columns: {', '.join(col_parts) if col_parts else '(none)'}")

    engine.dispose()

    if not table_full_names:
        body = "No tables found."
    else:
        body = "\n".join(lines)

    elapsed_ms = (time.monotonic() - started) * 1000
    logger.info(
        "schema_summary: dialect=%s tables=%s chars=%s elapsed_ms=%.1f",
        dialect_name,
        len(table_full_names),
        len(body),
        elapsed_ms,
    )
    return body


def _json_safe_value(value: Any) -> Any:
    if isinstance(value, (datetime, date, dt_time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def query(sql: str, *, max_rows: int = 500) -> tuple[list[dict[str, Any]], bool]:
    """Run read-only SQL via SQLAlchemy; truncate after ``max_rows`` dict rows."""
    try:
        from sqlalchemy import create_engine, text
    except ImportError as e:
        raise ImportError("Missing dependency: sqlalchemy (install deerflow-harness)") from e

    safe_sql = extract_select_sql(sql)
    fp = sql_fingerprint(safe_sql)
    started = time.monotonic()
    dsn = build_dsn()
    _ensure_sqlalchemy_dialect(dsn)
    engine = create_engine(dsn, pool_pre_ping=True)

    rows: list[dict[str, Any]] = []
    truncated = False
    try:
        with engine.connect() as conn:
            result = conn.execute(text(safe_sql))
            if result.returns_rows:
                mappings = result.mappings()
                for idx, row in enumerate(mappings):
                    if idx >= max_rows:
                        truncated = True
                        break
                    rows.append({k: _json_safe_value(v) for k, v in dict(row).items()})
            else:
                logger.info("query: returns_rows=false sql_fp=%s elapsed_ms=%.1f", fp, (time.monotonic() - started) * 1000)
    except Exception:
        logger.exception("query failed: sql_fp=%s", fp)
        raise
    finally:
        engine.dispose()

    elapsed_ms = (time.monotonic() - started) * 1000
    logger.info(
        "query: rows=%s truncated=%s sql_fp=%s elapsed_ms=%.1f",
        len(rows),
        truncated,
        fp,
        elapsed_ms,
    )
    return rows, truncated
