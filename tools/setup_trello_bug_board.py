#!/usr/bin/env python3
"""Настройка доски Trello «Аналитика — баги (клиент)».

Делает через API:
  - нужные колонки и порядок (Анализ первая);
  - метки категорий;
  - карточку с правилами + инструкцией Butler.

Кнопки Butler публичным API не создаются — в конце скрипт печатает чеклист.

Запуск (из корня репо или bi-analytics-v-5-main):
  python tools/setup_trello_bug_board.py
  python tools/setup_trello_bug_board.py --dry-run

Credentials: TRELLO_API_KEY, TRELLO_TOKEN, TRELLO_BOARD_ID
(из env или bi-analytics-v-5-main/.env).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import requests

TRELLO_API = "https://api.trello.com/1"

# Порядок колонок слева направо.
LIST_ORDER = [
    "Анализ",
    "Вопросы",
    "Фичи",
    "UI/UX",
    "Баги",
    "Срочно",
    "Нужно сделать",
    "В работе",
    "На холде",
    "Готово",
    "Инфо",
]

# Алиасы → каноническое имя (если на доске уже есть близкое название).
LIST_ALIASES: dict[str, tuple[str, ...]] = {
    "Анализ": ("анализ", "analysis", "triage", "на разбор"),
    "Вопросы": ("вопросы", "вопрос", "questions"),
    "Фичи": ("фичи", "фича", "features", "feature"),
    "UI/UX": ("ui/ux", "ui", "ux", "ui_improvement"),
    "Баги": ("баги", "баг", "bugs", "bug", "ошибки"),
    "Срочно": ("срочно", "urgent"),
    "Нужно сделать": ("нужно сделать", "to do", "todo", "backlog"),
    "В работе": ("в работе", "in progress", "doing"),
    "На холде": ("на холде", "hold", "on hold", "холд"),
    "Готово": ("готово", "done", "закрыто"),
    "Инфо": ("инфо", "info", "правила"),
}

LABELS = [
    ("Срочно", "red"),
    ("Баг", "orange"),
    ("UI", "sky"),
    ("Фича", "lime"),
    ("Вопрос", "yellow"),
    ("На разбор", "purple"),
    ("Новое", "pink"),
]

RULES_CARD_NAME = "Правила доски багов (авто)"
RULES_CARD_DESC = """## Поток

1. Новые заявки с ai.conall.ru падают в **Анализ** (первая колонка, сверху, оранжевая обложка).
2. После разбора — **кнопкой Butler** в тип: Вопросы / Фичи / UI/UX / Баги / Срочно.
3. Исполнение: **Нужно сделать** → **В работе** → **Готово** (или **На холде**, если ждём).
4. **Инфо** — только справочник, не задачи.

## Кнопки Butler (настроить вручную один раз)

Меню доски → **Автоматизация** → **Кнопки карточки**:

| Кнопка | Действие |
|--------|----------|
| → Вопрос | переместить в список «Вопросы»; убрать обложку |
| → Фича | переместить в список «Фичи»; убрать обложку |
| → UI | переместить в список «UI/UX»; убрать обложку |
| → Баг | переместить в список «Баги»; убрать обложку |
| → Срочно | переместить в список «Срочно»; убрать обложку |
| → В работу | переместить в список «В работе» |
| → Холд | переместить в список «На холде» |
| → Готово | переместить в список «Готово»; убрать обложку |

## Смысл колонок

- **Анализ** — вход с формы, ещё не апрувнуто.
- **Вопросы / Фичи / UI/UX / Баги / Срочно** — тип после анализа.
- **Нужно сделать / В работе / На холде / Готово** — статус исполнения.
- **На холде** — пауза (ждём клиента/данные/блокер), не «готово».
"""


def _load_dotenv() -> None:
    candidates = [
        Path(__file__).resolve().parents[1] / "bi-analytics-v-5-main" / ".env",
        Path(__file__).resolve().parents[1] / ".env",
        Path.cwd() / "bi-analytics-v-5-main" / ".env",
        Path.cwd() / ".env",
    ]
    for path in candidates:
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = val
        print(f"loaded env: {path}")
        return


def _auth() -> dict[str, str]:
    key = (os.environ.get("TRELLO_API_KEY") or "").strip()
    token = (os.environ.get("TRELLO_TOKEN") or "").strip()
    if not key or not token:
        raise SystemExit("Need TRELLO_API_KEY and TRELLO_TOKEN")
    return {"key": key, "token": token}


def _board_id() -> str:
    bid = (os.environ.get("TRELLO_BOARD_ID") or "").strip()
    if not bid:
        raise SystemExit("Need TRELLO_BOARD_ID")
    return bid


def _get(path: str, auth: dict[str, str], **params: object) -> object:
    r = requests.get(f"{TRELLO_API}{path}", params={**auth, **params}, timeout=30)
    r.raise_for_status()
    return r.json()


def _post(path: str, auth: dict[str, str], **params: object) -> object:
    r = requests.post(f"{TRELLO_API}{path}", params={**auth, **params}, timeout=30)
    r.raise_for_status()
    return r.json()


def _put(path: str, auth: dict[str, str], **params: object) -> object:
    r = requests.put(f"{TRELLO_API}{path}", params={**auth, **params}, timeout=30)
    r.raise_for_status()
    return r.json()


def _norm(name: str) -> str:
    return (name or "").strip().casefold()


def _match_list(open_lists: list[dict], canonical: str) -> dict | None:
    aliases = {_norm(canonical), *(_norm(a) for a in LIST_ALIASES.get(canonical, ()))}
    for lst in open_lists:
        if _norm(str(lst.get("name") or "")) in aliases:
            return lst
    for lst in open_lists:
        n = _norm(str(lst.get("name") or ""))
        if any(a in n for a in aliases if len(a) >= 3):
            return lst
    return None


def ensure_lists(auth: dict[str, str], board_id: str, *, dry_run: bool) -> dict[str, str]:
    open_lists = list(
        _get(f"/boards/{board_id}/lists", auth, fields="name,id,closed,pos", filter="open")
    )
    assert isinstance(open_lists, list)
    by_canonical: dict[str, str] = {}

    for name in LIST_ORDER:
        found = _match_list(open_lists, name)
        if found:
            lid = str(found["id"])
            by_canonical[name] = lid
            cur = str(found.get("name") or "")
            if cur != name:
                print(f"  rename list «{cur}» → «{name}»")
                if not dry_run:
                    _put(f"/lists/{lid}", auth, name=name)
                    found["name"] = name
            else:
                print(f"  ok list «{name}» ({lid})")
            continue
        print(f"  create list «{name}»")
        if dry_run:
            by_canonical[name] = f"dry-run-{name}"
            continue
        created = _post("/lists", auth, name=name, idBoard=board_id, pos="bottom")
        assert isinstance(created, dict)
        lid = str(created["id"])
        by_canonical[name] = lid
        open_lists.append({"id": lid, "name": name})

    # Порядок слева направо: Analysis first … Info last.
    print("  reorder lists…")
    if not dry_run:
        # Ставим с конца: last pos=bottom, then previous above it by using increasing pos.
        # Проще: идём слева направо и ставим pos top в обратном порядке.
        for name in reversed(LIST_ORDER):
            lid = by_canonical[name]
            _put(f"/lists/{lid}", auth, pos="top")

    return by_canonical


def ensure_labels(auth: dict[str, str], board_id: str, *, dry_run: bool) -> dict[str, str]:
    labels = list(_get(f"/boards/{board_id}/labels", auth, fields="name,id,color", limit=1000))
    assert isinstance(labels, list)
    by_name = {_norm(str(x.get("name") or "")): x for x in labels if isinstance(x, dict)}
    out: dict[str, str] = {}
    for name, color in LABELS:
        existing = by_name.get(_norm(name))
        if existing:
            lid = str(existing["id"])
            out[name] = lid
            print(f"  ok label «{name}» ({lid})")
            continue
        print(f"  create label «{name}» ({color})")
        if dry_run:
            out[name] = f"dry-run-{name}"
            continue
        created = _post("/labels", auth, name=name, color=color, idBoard=board_id)
        assert isinstance(created, dict)
        out[name] = str(created["id"])
    return out


def ensure_rules_card(
    auth: dict[str, str],
    info_list_id: str,
    *,
    dry_run: bool,
) -> None:
    cards = list(_get(f"/lists/{info_list_id}/cards", auth, fields="name,id,desc"))
    assert isinstance(cards, list)
    existing = next(
        (
            c
            for c in cards
            if isinstance(c, dict)
            and (
                _norm(str(c.get("name") or "")).startswith("правила доски")
                or "0024" in str(c.get("name") or "")
            )
        ),
        None,
    )
    if existing:
        cid = str(existing["id"])
        print(f"  update rules card {cid}")
        if not dry_run:
            _put(f"/cards/{cid}", auth, name=RULES_CARD_NAME, desc=RULES_CARD_DESC)
        return
    print("  create rules card in Инфо")
    if dry_run:
        return
    _post(
        "/cards",
        auth,
        idList=info_list_id,
        name=RULES_CARD_NAME,
        desc=RULES_CARD_DESC,
        pos="top",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    _load_dotenv()
    auth = _auth()
    board_id = _board_id()
    print(f"board={board_id} dry_run={args.dry_run}")

    print("\n== lists ==")
    lists = ensure_lists(auth, board_id, dry_run=args.dry_run)
    print("\n== labels ==")
    labels = ensure_labels(auth, board_id, dry_run=args.dry_run)
    print("\n== rules card ==")
    ensure_rules_card(auth, lists["Инфо"], dry_run=args.dry_run)

    print("\n== IDs for GitHub Secrets / .env ==")
    mapping = {
        "TRELLO_LIST_TRIAGE": lists.get("Анализ"),
        "TRELLO_LIST_QUESTION": lists.get("Вопросы"),
        "TRELLO_LIST_FEATURE": lists.get("Фичи"),
        "TRELLO_LIST_UI": lists.get("UI/UX"),
        "TRELLO_LIST_BUG": lists.get("Баги"),
        "TRELLO_LIST_URGENT": lists.get("Срочно"),
        "TRELLO_LABEL_URGENT": labels.get("Срочно"),
        "TRELLO_LABEL_BUG": labels.get("Баг"),
        "TRELLO_LABEL_UI": labels.get("UI"),
        "TRELLO_LABEL_FEATURE": labels.get("Фича"),
        "TRELLO_LABEL_QUESTION": labels.get("Вопрос"),
        "TRELLO_LABEL_TRIAGE": labels.get("На разбор"),
    }
    print(json.dumps(mapping, ensure_ascii=False, indent=2))

    print(
        """
== Butler (вручную, 1 раз) ==
Меню доски → Автоматизация → Кнопки карточки.
Создайте кнопки из карточки «Правила доски багов (авто)» на доске.
"""
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except requests.HTTPError as exc:
        print(f"HTTP error: {exc} body={getattr(exc.response, 'text', '')[:500]}", file=sys.stderr)
        raise SystemExit(1) from exc
