# -*- coding: utf-8 -*-
"""Kontr index for GDRS AI scripts (mirrors dashboards.gdrs_resursi)."""
from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

_NAME_NOISE_RE = re.compile(r"[\s\.,\-_/\\\"'«»()\[\]]+")
_NAME_LEGAL_RE = re.compile(
    r"\b(ооо|ао|зао|пао|оао|ип|оу|ук|нко|спк|кфх|апсх|нпф|чоп|снт|тсж)\b",
    re.IGNORECASE,
)
_NAME_REG_ID_RE = re.compile(
    r"\b(?:инн|огрн|кпп)\s*[:№#]?\s*\d{9,15}\b",
    re.IGNORECASE,
)


def normalize_name(s: object) -> str:
    t = str(s or "").strip()
    if not t:
        return ""
    t = re.sub(r"\(.*?\)", " ", t)
    t = re.sub(r"_+", " ", t)
    t = _NAME_REG_ID_RE.sub(" ", t)
    t = t.casefold()
    t = _NAME_LEGAL_RE.sub(" ", t)
    t = _NAME_NOISE_RE.sub(" ", t)
    return " ".join(t.split())


@dataclass(frozen=True)
class KontrIndex:
    ids: frozenset[str]
    norm_names: frozenset[str]


def _kontr_from_records(records: Iterable[dict]) -> KontrIndex:
    ids: set[str] = set()
    norm_names: set[str] = set()
    for r in records:
        if not isinstance(r, dict):
            continue
        cid = str(r.get("ID_Контрагента") or "").strip()
        cname = str(r.get("Наименование_Контрагента") or r.get("Наименование") or "").strip()
        nn = normalize_name(cname) if cname else ""
        if cid:
            ids.add(cid)
        if nn:
            norm_names.add(nn)
    return KontrIndex(frozenset(ids), frozenset(norm_names))


def load_kontr_index_from_db(conn: sqlite3.Connection, version_id: int) -> KontrIndex:
    rows = conn.execute(
        """
        SELECT row_data FROM web_data
        WHERE version_id = ? AND file_type = 'kontr_json'
        """,
        (int(version_id),),
    ).fetchall()
    records = []
    for (row_json,) in rows:
        try:
            rec = json.loads(row_json)
        except Exception:
            continue
        if isinstance(rec, dict):
            records.append(rec)
    return _kontr_from_records(records)


def load_kontr_index(web_dir: Path) -> KontrIndex:
    """Legacy: чтение из каталога web/. Предпочтительно load_kontr_index_from_db."""
    ids: set[str] = set()
    norm_names: set[str] = set()
    for p in sorted(web_dir.glob("*_Kontr.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(data, list):
            continue
        idx = _kontr_from_records(data)
        ids |= set(idx.ids)
        norm_names |= set(idx.norm_names)
    return KontrIndex(frozenset(ids), frozenset(norm_names))


def contractor_in_kontr(contractor_id: str, contractor_name: str, kontr: Optional[KontrIndex]) -> bool:
    if kontr is None or (not kontr.ids and not kontr.norm_names):
        return True
    cid = str(contractor_id or "").strip()
    if cid and cid in kontr.ids:
        return True
    nn = normalize_name(contractor_name)
    return bool(nn and nn in kontr.norm_names)
