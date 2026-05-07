"""09 «Утверждённый бюджет план/факт» (бывш. 08 «Бюджет план/факт»).
Golden по точной формуле заказчика (скрин ТЗ от 2026-05-07):

  Утверждённый бюджет (=План)
      = строки  ТипСтатьи == «БДДС»
              ∧ Сценарий  == «ПЛАН»
              ∧ «Статья оборотов»  БЕЗ маркера «(БДР)»
        SUM(Сумма) × 1000   (1С отдаёт в тыс.руб → приводим к руб)

  Фактические расходы (=Факт)
      = строки  ТипСтатьи == «БДДС»
              ∧ Сценарий  == «ФАКТ»
        SUM(Сумма) × 1000

  Отклонение = Факт − План  (в Streamlit-таблице: <0 → красный, >0 → зелёный).

Источник — АКТИВНАЯ версия `web/web_data.db` (`web_data` rows из всех `1с_*_dannye.json`).
"""
from __future__ import annotations
import json as _json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402

from dashboards.finance_from_1c import _coerce_1c_money_series, try_approved_budget_from_1c_dannye  # noqa: E402
from web_schema import WEB_DB_PATH, get_active_version_id  # noqa: E402


def _pick(d: pd.DataFrame, *names: str) -> str | None:
    cols_norm = {str(c).strip().casefold().replace(" ", ""): c for c in d.columns}
    for n in names:
        k = n.strip().casefold().replace(" ", "")
        if k in cols_norm:
            return cols_norm[k]
    return None


def _load_active_dannye_df() -> pd.DataFrame:
    db = Path(str(WEB_DB_PATH))
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    try:
        v = get_active_version_id()
        cur = conn.cursor()
        cur.execute(
            "SELECT id, file_name FROM web_files WHERE version_id = ? ORDER BY file_name",
            (v,),
        )
        files = cur.fetchall()
        dannye_ids = [r["id"] for r in files if "dannye" in str(r["file_name"]).lower()]
        if not dannye_ids:
            return pd.DataFrame()
        dannye_names = [r["file_name"] for r in files if "dannye" in str(r["file_name"]).lower()]
        placeholders = ",".join("?" * len(dannye_ids))
        cur.execute(
            f"SELECT row_data FROM web_data WHERE version_id = ? AND file_id IN ({placeholders})",
            (v, *dannye_ids),
        )
        rows = []
        for r in cur.fetchall():
            try:
                rows.append(_json.loads(r["row_data"]))
            except Exception:
                pass
        print(f"[active version_id={v}] dannye files: {dannye_names} → {len(rows)} rows")
        return pd.DataFrame(rows)
    finally:
        conn.close()


def main() -> int:
    df = _load_active_dannye_df()
    if df.empty:
        print("FAIL: пусто")
        return 1

    c_typ = _pick(df, "ТипСтатьи", "Тип статьи", "article_type")
    c_scen = _pick(df, "Сценарий", "scenario")
    c_art = _pick(df, "СтатьяОборотов", "Статья оборотов", "article")
    c_amt = _pick(df, "Сумма", "amount")
    c_proj = _pick(df, "Проект", "project", "ИмяПроекта")
    print(f"[cols] type={c_typ!r}, scen={c_scen!r}, art={c_art!r}, amt={c_amt!r}, proj={c_proj!r}")
    if not all([c_typ, c_scen, c_art, c_amt]):
        print("FAIL: нужных колонок нет")
        return 1

    typ_norm = df[c_typ].astype(str).str.strip().str.casefold()
    bdds = df[typ_norm.eq("бддс")].copy()
    print(f"[mask] ТипСтатьи=БДДС: {len(bdds)} / {len(df)} строк")
    if bdds.empty:
        print("FAIL: нет строк БДДС")
        return 1

    scen = bdds[c_scen].astype(str).str.strip().str.casefold()
    art_norm = (
        bdds[c_art]
        .astype(str)
        .str.replace("\xa0", " ", regex=False)
        .str.replace("\u200b", "", regex=False)
        .str.strip()
        .str.casefold()
    )
    has_bdr_marker = art_norm.str.contains(r"\(бдр\)", regex=True, na=False) | art_norm.eq("бдр")

    amt = _coerce_1c_money_series(bdds[c_amt]).fillna(0.0) * 1000.0  # руб

    plan_mask = scen.eq("план") & ~has_bdr_marker
    fact_mask = scen.eq("факт")  # ТЗ: «БДДС: факт = признаком "Сценарий": "ФАКТ"»

    plan_total = float(amt[plan_mask].sum())
    fact_total = float(amt[fact_mask].sum())
    dev = fact_total - plan_total
    over_pct = (dev / plan_total * 100.0) if plan_total > 0 else 0.0

    print()
    print("=== Сводный KPI «Утверждённый бюджет план/факт» (фильтр «Все») ===")
    print(f"  План=ПЛАН (без (БДР))   : {plan_total/1e9:>10.3f} млрд  ({plan_total/1e6:>10.2f} млн)")
    print(f"  Факт=ФАКТ                : {fact_total/1e9:>10.3f} млрд  ({fact_total/1e6:>10.2f} млн)   delta={over_pct:+.1f}%")
    print(f"  Отклонение (Ф−П)         : {dev/1e6:>+10.2f} млн")

    if not c_proj:
        print("WARN: нет колонки 'Проект' — пропускаем разбивку")
        return 0

    print()
    print("=== Разбивка по проектам (млн руб) ===")
    bdds = bdds.assign(_amt=amt, _plan=plan_mask.astype(float), _fact=fact_mask.astype(float))
    bdds["_plan_amt"] = bdds["_amt"] * bdds["_plan"]
    bdds["_fact_amt"] = bdds["_amt"] * bdds["_fact"]
    g = (
        bdds.groupby(c_proj, dropna=False)
        .agg(plan_mln=("_plan_amt", "sum"), fact_mln=("_fact_amt", "sum"))
        .reset_index()
        .rename(columns={c_proj: "Проект"})
    )
    g["plan_mln"] /= 1e6
    g["fact_mln"] /= 1e6
    g["dev_mln"] = g["fact_mln"] - g["plan_mln"]
    g["%"] = g.apply(
        lambda r: f"{(r['fact_mln'] - r['plan_mln']) / r['plan_mln'] * 100:+.1f}%"
        if r["plan_mln"] > 0 else "—",
        axis=1,
    )
    print(g.to_string(index=False, formatters={
        "plan_mln": lambda x: f"{x:>10.2f}",
        "fact_mln": lambda x: f"{x:>10.2f}",
        "dev_mln":  lambda x: f"{x:>+10.2f}",
    }))

    print()
    print("=== Уникальные значения «Сценарий» / «ТипСтатьи» (для контроля) ===")
    print("Сценарий:", sorted(set(df[c_scen].astype(str).str.strip().str.casefold().unique())))
    print("ТипСтатьи:", sorted(set(df[c_typ].astype(str).str.strip().str.casefold().unique())))

    print()
    print("=== Кросс-проверка через try_approved_budget_from_1c_dannye() ===")
    syn = try_approved_budget_from_1c_dannye(reference_1c_dannye=df)
    if syn is None or syn.empty:
        print("FAIL: try_approved_budget_from_1c_dannye вернула пусто")
    else:
        sp = float(pd.to_numeric(syn["budget plan"], errors="coerce").fillna(0.0).sum())
        sf = float(pd.to_numeric(syn["budget fact"], errors="coerce").fillna(0.0).sum())
        match_p = abs(sp - plan_total) < 1.0
        match_f = abs(sf - fact_total) < 1.0
        print(f"  Σplan(syn)={sp/1e6:.2f} млн   match={match_p}")
        print(f"  Σfact(syn)={sf/1e6:.2f} млн   match={match_f}")
        print(syn.assign(
            plan_mln=lambda d: pd.to_numeric(d["budget plan"], errors="coerce") / 1e6,
            fact_mln=lambda d: pd.to_numeric(d["budget fact"], errors="coerce") / 1e6,
        )[["project name", "plan_mln", "fact_mln"]].to_string(index=False))

    print()
    print("=== Сравнение со старым golden (с фильтром лот/подлот) ===")
    print(f"  Старый (с лот/подлот, B-2.2): План=5242.83 / Факт=2939.20 / dev=-2303.63 млн")
    print(f"  Новый (по ТЗ заказчика 09)  : План={plan_total/1e6:.2f} / Факт={fact_total/1e6:.2f} / dev={dev/1e6:+.2f} млн")

    return 0


if __name__ == "__main__":
    sys.exit(main())
