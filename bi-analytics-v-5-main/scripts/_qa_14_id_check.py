"""Эталон для дашборда «Исполнительная документация» (B-14).

ВАЖНО: дашборд работает с объединением ВСЕХ snapshot-файлов (tessa_*-id.csv),
поэтому 1 документ = N строк. Для «текущего состояния» делаем dedup по DocID
(оставляем последнюю запись по `Import_data` / `CreationDate`).

Считает:
  • Всего уникальных документов (по DocID, актуальное состояние)
  • Распределение по статусам (актуальный статус каждого документа)
  • Распределение по типам документов (kindName) — без «Предписаний»
  • Распределение по объектам (ObjectName)
  • Распределение по контрагентам (CONTR)
  • Семантические группы (Принято / Отказ / На согласовании / На доработке)
    с корректным исключением переходных статусов «На согласовании» / «На подписании»

Числа из этого скрипта = эталон, с которым нужно сверить UI после визуальной приёмки.

Запуск:  python scripts/_qa_14_id_check.py
Вывод: scripts/_qa_14_id_check.last.txt
"""
from __future__ import annotations
from pathlib import Path
import re
import sys
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
OUT = Path(__file__).with_suffix(".last.txt")


def _all_id_csvs() -> list[Path]:
    files = sorted(WEB.glob("tessa_*-id.csv"))
    def _key(p: Path) -> tuple:
        m = re.search(r"tessa_(\d{2})-(\d{2})-(\d{4})-(\d{2})-(\d{2})", p.stem)
        if m:
            d, mo, y, h, mi = map(int, m.groups())
            return (y, mo, d, h, mi)
        return (0, 0, 0, 0, 0)
    return sorted(files, key=_key)


def _read_csv_any(fp: Path) -> pd.DataFrame | None:
    for enc in ("utf-8-sig", "utf-8", "cp1251"):
        for sep in (";", ",", "\t"):
            try:
                d = pd.read_csv(fp, encoding=enc, sep=sep, engine="python")
                if d.shape[1] >= 2:
                    return d
            except (UnicodeDecodeError, UnicodeError, pd.errors.ParserError):
                continue
    return None


def main() -> int:
    out: list[str] = []
    def w(s: str = "") -> None:
        print(s)
        out.append(s)

    files = _all_id_csvs()
    if not files:
        w("[FAIL] Не найдено ни одного web/tessa_*-id.csv")
        OUT.write_text("\n".join(out), encoding="utf-8")
        return 1

    w(f"Snapshot файлов: {len(files)}")
    parts = []
    for fp in files:
        d = _read_csv_any(fp)
        if d is None or d.empty:
            w(f"  пропуск: {fp.name}")
            continue
        d.columns = [str(c).strip() for c in d.columns]
        parts.append(d)
        w(f"  {fp.name:50s}  строк={len(d):4d}  колонок={d.shape[1]}")

    if not parts:
        w("[FAIL] Не удалось прочитать ни один файл")
        OUT.write_text("\n".join(out), encoding="utf-8")
        return 1

    df = pd.concat(parts, ignore_index=True, sort=False)
    df.columns = [str(c).strip() for c in df.columns]
    w("")
    w(f"СУММАРНО строк: {len(df)}, колонок: {len(df.columns)}")
    w(f"Колонки: {', '.join(df.columns.tolist())}")
    w("")

    # ---- Найдём ключевые колонки ----
    def _find(*names: str) -> str | None:
        nset = {n.lower() for n in names}
        for c in df.columns:
            if str(c).strip().lower() in nset:
                return c
        for c in df.columns:
            cl = str(c).strip().lower()
            for n in names:
                if n.lower() in cl:
                    return c
        return None

    kind_col = _find("KindName", "kindname", "Вид")
    obj_col = _find("ObjectName", "objectname", "Объект")
    contr_col = _find("CONTR", "Контрагент")
    state_col = _find("KrStateText", "KrState_Text", "KrStateName", "KrState")
    state_id_col = _find("KrStateID", "KrState_ID")
    doc_id_col = _find("DocID", "DocId", "CardID", "CardId")
    creation_col = _find("CreationDate", "creationdate", "Дата создания")

    w(f"  kind_col       = {kind_col}")
    w(f"  obj_col        = {obj_col}")
    w(f"  contr_col      = {contr_col}")
    w(f"  state_col      = {state_col}")
    w(f"  state_id_col   = {state_id_col}")
    w(f"  doc_id_col     = {doc_id_col}")
    w(f"  creation_col   = {creation_col}")
    w("")

    # ---- Исключаем «Предписания» (как в UI) ----
    work = df.copy()
    if kind_col:
        mask_pred = work[kind_col].astype(str).str.contains("Предписан", case=False, na=False)
        n_pred = int(mask_pred.sum())
        work = work[~mask_pred].reset_index(drop=True)
        w(f"  исключено «Предписания»: {n_pred} строк")

    # Чистим пустой ObjectName
    if obj_col:
        before = len(work)
        work = work[
            work[obj_col].notna()
            & (~work[obj_col].astype(str).str.strip().isin(["", "nan", "None", "NaN"]))
        ].reset_index(drop=True)
        n_drop = before - len(work)
        if n_drop:
            w(f"  отброшено пустых ObjectName: {n_drop} строк")
    w(f"  ИТОГО рабочих строк (с историей snapshot): {len(work)}")
    w("")

    # ---- DEDUP: оставляем последний snapshot каждого DocID ----
    work_full = work.copy()
    if doc_id_col and doc_id_col in work.columns:
        sort_keys = []
        if "Import_data" in work.columns:
            work["_imp_dt"] = pd.to_datetime(work["Import_data"], errors="coerce", dayfirst=True)
            sort_keys.append("_imp_dt")
        if creation_col:
            work["_cd"] = pd.to_datetime(work[creation_col], errors="coerce", dayfirst=True)
            sort_keys.append("_cd")
        if sort_keys:
            work = (
                work.sort_values(sort_keys, kind="stable")
                .drop_duplicates(subset=[doc_id_col], keep="last")
                .reset_index(drop=True)
            )
        else:
            work = work.drop_duplicates(subset=[doc_id_col], keep="last").reset_index(drop=True)
        w(f"# После dedup по {doc_id_col} (актуальное состояние): {len(work)} документов")
    else:
        w(f"# Колонка DocID/CardID не найдена — dedup пропущен")
    w("")

    # ---- Распределение по типам ----
    if kind_col:
        w("")
        w(f"# Распределение по типам документов ({kind_col}):")
        vc_kind = work[kind_col].value_counts(dropna=False)
        for k, v in vc_kind.head(20).items():
            w(f"  {str(k):40s} : {int(v):5d}")

    # ---- Распределение по статусам ----
    if state_col and state_col in work.columns:
        w("")
        w(f"# Распределение по статусам ({state_col}):")
        vc_st = work[state_col].astype(str).value_counts(dropna=False)
        for k, v in vc_st.head(20).items():
            w(f"  {str(k):40s} : {int(v):5d}")

        # Семантические группы — С исключением переходных «На согласовании» / «На подписании»
        # (как в исправленном UI)
        sl = work[state_col].astype(str).str.lower()
        is_on_agree = sl.str.contains("на согласовани", na=False)
        is_on_sign = sl.str.contains("на подписани", na=False)
        is_rew = sl.str.contains("доработ", na=False)
        is_decl = sl.str.contains("отказ|не сдан", na=False)
        is_signed = (
            sl.str.contains("подписан|согласован|принят", na=False)
            & (~is_on_agree)
            & (~is_on_sign)
        )
        w("")
        w(f"# Семантические группы (УНИКАЛЬНЫЕ ДОКУМЕНТЫ, как в UI):")
        w(f"  Принято (Подписан/Согласован/Принят финально)   : {int(is_signed.sum())}")
        w(f"  Отказ/Не сдан                                   : {int(is_decl.sum())}")
        w(f"  На согласовании (включая 'На подписании')       : {int((is_on_agree | is_on_sign).sum())}")
        w(f"  У подрядчика (доработка)                        : {int(is_rew.sum())}")
        w(f"  Просрочка подрядчика (=У подрядчика)            : {int(((~is_signed) & (~is_decl) & is_rew).sum())}")
        w(f"  Просрочка заказчика (=На согласовании)          : {int(((~is_signed) & (~is_decl) & (is_on_agree | is_on_sign)).sum())}")
        w(f"  Всего просрочек (П+З)                           : {int(((~is_signed) & (~is_decl) & (is_rew | is_on_agree | is_on_sign)).sum())}")

    # ---- Распределение по объектам ----
    if obj_col:
        w("")
        w(f"# Распределение по объектам ({obj_col}):")
        vc_obj = work[obj_col].astype(str).str.strip().value_counts()
        for k, v in vc_obj.head(20).items():
            w(f"  {str(k):40s} : {int(v):5d}")

    # ---- Распределение по контрагентам ----
    if contr_col:
        w("")
        w(f"# ТОП-10 контрагентов ({contr_col}):")
        vc_c = work[contr_col].astype(str).str.strip().value_counts()
        for k, v in vc_c.head(10).items():
            w(f"  {str(k):40s} : {int(v):5d}")
        w(f"  ИТОГО уникальных контрагентов: {int(vc_c.shape[0])}")

    # ---- Дата создания и распределение по месяцам ----
    if creation_col:
        w("")
        cd = pd.to_datetime(work[creation_col], errors="coerce", dayfirst=True)
        n_dt = int(cd.notna().sum())
        w(f"# Колонка даты создания ({creation_col}): {n_dt} распарсено / {len(cd)} всего")
        if n_dt:
            w(f"  диапазон: {cd.min()} — {cd.max()}")
            mvc = cd.dt.to_period("M").value_counts().sort_index()
            w(f"  по месяцам:")
            for m, n in mvc.items():
                w(f"    {m} : {int(n)}")

    # ---- Запись в файл ----
    OUT.write_text("\n".join(out), encoding="utf-8")
    w("")
    w(f"[OK] Эталон записан в {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
