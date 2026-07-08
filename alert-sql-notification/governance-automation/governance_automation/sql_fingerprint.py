"""SQL normalization and fingerprint generation.

The implementation is intentionally conservative. It keeps table names,
column names, joins, and predicate shape while masking values that commonly
change between repeated runs.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass


FINGERPRINT_VERSION = "v1"


@dataclass(frozen=True)
class SqlFingerprint:
    fingerprint: str
    normalized_sql: str
    version: str = FINGERPRINT_VERSION


def strip_sql_comments(sql: str) -> str:
    """Remove common SQL comments without trying to be a full SQL parser."""
    sql = re.sub(r"/\*.*?\*/", " ", sql or "", flags=re.DOTALL)
    sql = re.sub(r"--[^\n\r]*", " ", sql)
    sql = re.sub(r"#[^\n\r]*", " ", sql)
    return sql


def normalize_sql(sql: str) -> str:
    text = strip_sql_comments(sql)
    text = text.lower()
    text = re.sub(r"\bdate\s*\(\s*'[^']*'\s*\)", "date(?)", text)
    text = re.sub(r"\btimestamp\s*'[^']*'", "timestamp ?", text)
    text = re.sub(r"\bdate\s*'[^']*'", "date ?", text)
    text = re.sub(r"'(?:''|[^'])*'", "?", text)
    text = re.sub(r'"(?:""|[^"])*"', "?", text)
    text = re.sub(r"\b\d{4}-\d{1,2}-\d{1,2}\b", "?", text)
    text = re.sub(r"\b\d+(?:\.\d+)?\b", "?", text)
    text = re.sub(r"\bin\s*\((?:[^()]|\([^()]*\))*\)", "in (?)", text)
    text = re.sub(r"\s+", " ", text)
    text = text.strip().rstrip(";").strip()
    return text


def build_sql_fingerprint(sql: str) -> SqlFingerprint:
    normalized = normalize_sql(sql)
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return SqlFingerprint(fingerprint=digest[:32], normalized_sql=normalized)

