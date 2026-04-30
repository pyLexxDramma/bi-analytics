# -*- coding: utf-8 -*-
"""
Офлайн-сравнение пайплайна БДДС и БДР с логикой dashboards/finance_from_1c.py
(как при fallback из *_dannye.json), без Streamlit.

Помогает понять: пустой график, «нулевые» месяцы, неверные суммы, сужение по проектам MSP.

Запуск из корня проекта (где лежит папка dashboards/):
  python scripts/compare_bdd_s_bdr_pipeline.py --web web
  python scripts/compare_bdd_s_bdr_pipeline.py --web web --project "Дмитровский-1"
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import warnings
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

# Корень репозитория: .../bi-analytics-v-5-main
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from dashboards.finance_from_1c import (  # noqa: E402
    _coerce_1c_money_series,
    _pick_col,
    try_synthetic_bdr_from_1c_dannye,
    try_synthetic_budget_from_1c_dannye,
)
from dashboards._renderers import _project_filter_norm_key  # noqa: E402


def _find_dannye_json(web_dir: Path) -> Path:
    found = sorted(web_dir.glob("*dannye.json"))
    if not found:
        found = sorted(web_dir.glob("*dannye*.json"))
    if not found:
        raise FileNotFoundError(f"В {web_dir} не найден файл *dannye.json")
    return found[0]


def _read_json_records(path: Path) -> pd.DataFrame:
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "utf-8", "cp1251"):
        try:
            text = raw.decode(enc)
            data = json.loads(text)
            break
        except (UnicodeDecodeError, json.JSONDecodeError):
            data = None
    else:
        raise ValueError(f"Не удалось прочитать JSON: {path}")
    if not isinstance(data, list):
        raise ValueError("Ожидался JSON-массив объектов")
    return pd.DataFrame(data)


def _msp_slug_from_filename(fp: Path) -> str:
    stem = fp.stem
    if not stem.casefold().startswith("msp_"):
        return ""
    rest = stem[4:]
    parts = rest.rsplit("_", 1)
    if (
        len(parts) == 2
        and re.match(r"\d{2}-\d{2}-\d{4}(?:_\d{2}-\d{2}-\d{2})?$", parts[1])
    ):
        return parts[0].strip().casefold()
    return rest.strip().casefold()


def _load_msp_project_names(web_dir: Path, limit_files: int = 40) -> tuple[set[str], int]:
    """Имена проектов как в приложении (имя файла msp_<slug>_… + MSP_PROJECT_NAME_MAP)."""
    names: set[str] = set()
    try:
        from config import MSP_PROJECT_NAME_MAP
    except Exception:
        MSP_PROJECT_NAME_MAP = {}

    all_msp = sorted(web_dir.rglob("msp_*.csv"))
    files = all_msp[:limit_files]

    from_filename: set[str] = set()

    def _slug_to_label(slug: str) -> Optional[str]:
        if not slug:
            return None
        return MSP_PROJECT_NAME_MAP.get(slug) or MSP_PROJECT_NAME_MAP.get(
            slug.replace(" ", ""),
            None,
        )

    for fp in files:
        slug = _msp_slug_from_filename(fp)
        if slug:
            label = _slug_to_label(slug)
            if label:
                from_filename.add(label)
            else:
                from_filename.add(slug)

    names |= from_filename
    for fp in files:
        raw = fp.read_bytes()
        for enc in ("utf-8-sig", "cp1251", "utf-8"):
            try:
                df = pd.read_csv(fp, encoding=enc, nrows=5000, low_memory=False)
                break
            except Exception:
                df = None
        else:
            continue
        for col in ("project name", "Проект", "Project", "project"):
            if col in df.columns:
                for v in df[col].dropna().astype(str).unique().tolist()[:800]:
                    s = str(v).strip()
                    if s and s.casefold() not in {"nan", "none"}:
                        names.add(s)
                break
    return names, len(all_msp)


def _agg_bdd_s_month(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    use = df.copy()
    if "plan_month" not in use.columns:
        return pd.DataFrame()
    g = (
        use.groupby("plan_month", dropna=False, sort=True)
        .agg({"budget plan": "sum", "budget fact": "sum"})
        .reset_index()
    )
    g["period"] = g["plan_month"].astype(str)
    return g


def _agg_bdr_month(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    use = df.copy()
    if "plan_month" not in use.columns:
        return pd.DataFrame()
    g = (
        use.groupby("plan_month", dropna=False, sort=True)
        .agg({"bdr_income": "sum", "bdr_expense": "sum"})
        .reset_index()
    )
    g["bdr_saldo"] = pd.to_numeric(g["bdr_income"], errors="coerce").fillna(0.0) - pd.to_numeric(
        g["bdr_expense"], errors="coerce"
    ).fillna(0.0)
    g["period"] = g["plan_month"].astype(str)
    return g


def _filter_by_projects(syn: pd.DataFrame, msp_projects: set[str]) -> pd.DataFrame:
    if syn is None or syn.empty or not msp_projects:
        return syn
    keys = {_project_filter_norm_key(x) for x in msp_projects}
    keys.discard("")
    if not keys:
        return syn
    return syn[syn["project name"].map(_project_filter_norm_key).isin(keys)].copy()


def _filter_one_project(syn: pd.DataFrame, project_label: str) -> pd.DataFrame:
    if syn is None or syn.empty:
        return syn
    k = _project_filter_norm_key(project_label)
    return syn[syn["project name"].map(_project_filter_norm_key) == k].copy()


def _parse_gap_bdd_s(ref: pd.DataFrame) -> dict[str, Any]:
    """Сколько сумм в БДДС теряется из-за pd.to_numeric вместо robust-parse."""
    amt = _pick_col(
        ref,
        ("Сумма", "amount", "суммаоборот", "сумма оборот", "суммавруб", "суммавруб"),
    )
    if not amt or amt not in ref.columns:
        return {"amount_col": None}
    raw = ref[amt]
    naive = pd.to_numeric(raw, errors="coerce")
    robust = _coerce_1c_money_series(raw)
    n = int(len(ref))
    na_naive = int(naive.isna().sum())
    loss = float(
        np.nan_to_num(robust.fillna(0.0).to_numpy(), nan=0.0).sum()
        - np.nan_to_num(naive.fillna(0.0).to_numpy(), nan=0.0).sum()
    )
    return {
        "amount_col": amt,
        "rows": n,
        "naive_parse_nan_count": na_naive,
        "sum_abs_delta_naive_vs_robust": loss,
    }


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Сравнение пайплайна БДДС/БДР с данными web/*dannye.json"
    )
    ap.add_argument(
        "--web",
        type=Path,
        default=_ROOT / "web",
        help="Папка с *_dannye.json и msp_*.csv",
    )
    ap.add_argument(
        "--project",
        type=str,
        default="",
        help='Имя проекта как в UI (например "Дмитровский-1"); пусто = все проекты из синтетики',
    )
    ap.add_argument(
        "--hide-zero-eps",
        type=float,
        default=0.5,
        help="Порог «скрыть нулевые месяцы» как в чекбоксе (сумма план+факт в базовых единицах)",
    )
    args = ap.parse_args()
    web_dir = args.web.resolve()
    if not web_dir.is_dir():
        print(f"Нет папки: {web_dir}", file=sys.stderr)
        return 2

    path = _find_dannye_json(web_dir)
    warnings.filterwarnings("ignore", category=UserWarning)

    ref = _read_json_records(path)
    print("=== Источник ===")
    print(f"Файл: {path.name}")
    print(f"Строк: {len(ref)}, колонок: {len(ref.columns)}")

    gap = _parse_gap_bdd_s(ref)
    if gap.get("amount_col"):
        print("\n--- Парсинг «Сумма» для БДДС (pd.to_numeric vs robust) ---")
        print(
            f"Колонка: {gap['amount_col']}; NaN после pd.to_numeric: {gap['naive_parse_nan_count']}/{gap['rows']}"
        )
        print(
            f"Разница сумм (robust − naive), абс. значение: {gap['sum_abs_delta_naive_vs_robust']:.2f}"
        )

    msp_projects, msp_nfiles = _load_msp_project_names(web_dir)
    print(f"\nФайлов msp_*.csv (рекурсивно): {msp_nfiles}")
    print(f"Проекты из MSP (уникальные, выборка файлов): {len(msp_projects)}")
    if msp_projects:
        print(f"  → {', '.join(sorted(msp_projects))}")

    bdds = try_synthetic_budget_from_1c_dannye(reference_1c_dannye=ref)
    bdr = try_synthetic_bdr_from_1c_dannye(reference_1c_dannye=ref)

    print("\n=== БДДС (try_synthetic_budget_from_1c_dannye) ===")
    if bdds is None or bdds.empty:
        print("Синтетика None/пусто: fallback на дашборде не даст таблицы (или не загружен 1С).")
    else:
        print(f"Строк синтетики: {len(bdds)}")
        s_plan = pd.to_numeric(bdds["budget plan"], errors="coerce").fillna(0.0).sum()
        s_fact = pd.to_numeric(bdds["budget fact"], errors="coerce").fillna(0.0).sum()
        print(f"Итого budget plan (все строки): {s_plan:.2f}")
        print(f"Итого budget fact (все строки): {s_fact:.2f}")
        gm = _agg_bdd_s_month(bdds)
        if not gm.empty:
            gm_m = gm.rename(columns={"budget plan": "plan", "budget fact": "fact"})
            print("\nПо месяцам (все проекты в синтетике):")
            print(gm_m.to_string(index=False))

        bdds_ms = _filter_by_projects(bdds, msp_projects)
        print(f"\nПосле сужения до проектов из MSP: строк {len(bdds_ms)}")
        if bdds_ms.empty and not bdds.empty:
            print(
                "  ВНИМАНИЕ: пересечение имён MSP и «Проект» из 1С пустое — на дашборде fallback может отключиться!"
            )

        bdds_fin = bdds_ms if not args.project.strip() else _filter_one_project(bdds_ms, args.project.strip())
        if args.project.strip():
            print(f'\nФильтр как в UI («{args.project.strip()}»): строк {len(bdds_fin)}')

        gm2 = _agg_bdd_s_month(bdds_fin)
        zero_months = 0
        if not gm2.empty:
            zp = gm2["budget plan"].fillna(0).abs()
            zf = gm2["budget fact"].fillna(0).abs()
            zm = (zp + zf) <= float(args.hide_zero_eps)
            zero_months = int(zm.sum())
            gm2_disp = gm2.loc[~zm].copy() if zm.any() else gm2.copy()
            print("\nИтог по месяцам (как источник графика «По месяцам», после фильтров):")
            print(gm2.to_string(index=False))
            print(
                f"\nМесяцев где |план|+|факт| ≤ {args.hide_zero_eps} (при включённом «скрыть нули»): {zero_months}"
            )
            print(f"Месяцев останется для графика: {len(gm2_disp)}")
            if gm2_disp.empty:
                print("→ График пуст при включённом скрытии нулевых месяцев.")

    print("\n=== БДР (try_synthetic_bdr_from_1c_dannye) ===")
    if bdr is None or bdr.empty:
        print("Синтетика None/пусто.")
    else:
        approx = bool(getattr(bdr, "attrs", {}).get("bdr_approx_by_rd_split", False))
        print(f"Строк синтетики: {len(bdr)}, «аппроксимация по РасходДоход»: {approx}")
        bdr_ms = _filter_by_projects(bdr, msp_projects)
        print(f"После сужения до проектов из MSP: строк {len(bdr_ms)}")
        bdr_fin = bdr_ms if not args.project.strip() else _filter_one_project(bdr_ms, args.project.strip())
        if args.project.strip():
            print(f'После фильтра проекта: строк {len(bdr_fin)}')

        gx = _agg_bdr_month(bdr_fin if len(bdr_fin) else bdr_ms)
        if gx.empty:
            gx = _agg_bdr_month(bdr)
        if gx.empty:
            print("Нет помесячной агрегации.")
        else:
            print("\nПо месяцам (доходы / расходы / сальдо):")
            print(gx.to_string(index=False))
            di = gx["bdr_income"].fillna(0).abs()
            de = gx["bdr_expense"].fillna(0).abs()
            zm2 = (di + de) <= float(args.hide_zero_eps)
            print(
                f"\nМесяцев где |доходы|+|расходы| ≤ {args.hide_zero_eps} (БДР чекбокс скрыть нули): {int(zm2.sum())}"
            )
            if zm2.all() and len(gx) > 0:
                print("→ Все месяцы могут быть скрыты; график пуст.")

    print("\n=== Возможные причины расхождений с экраном ===")
    print(
        "- БДДС: суммы в синтетике идут через pd.to_numeric(«Сумма»); формат «110,000.00» может давать ошибки против robust-парсера."
    )
    print(
        "- БДДР: включён фильтр «Скрыть нулевые месяцы» — при сумме≈0 по месяцу столбцы исчезают со графика."
    )
    print(
        "- Даты: строки без разобранного «Период» исключаются; диапазон календаря на дашборде отрезает plan end."
    )
    print(
        "- Проекты: fallback сужается к именам из MSP; при несовпадении написания с 1С синтетика обнуляется."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
