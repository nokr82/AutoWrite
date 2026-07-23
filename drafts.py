"""임시 저장된 글(제목+본문) 목록. 최대 MAX_DRAFTS개까지만 보관하며,
그 이상 저장하면 가장 오래된 것부터 지운다 — 같은 글을 다시 쓰지 않고
저장해둔 글을 목록에서 눌러 그대로 불러오기 위한 용도."""
from __future__ import annotations

import datetime as dt
import json
import uuid

from config import DRAFTS_PATH

MAX_DRAFTS = 5


def _load() -> list[dict]:
    if not DRAFTS_PATH.exists():
        return []
    with open(DRAFTS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _save(drafts: list[dict]) -> None:
    DRAFTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(DRAFTS_PATH, "w", encoding="utf-8") as f:
        json.dump(drafts, f, ensure_ascii=False, indent=2)


def list_drafts() -> list[dict]:
    """최근에 저장한 순서로 정렬된 임시 저장 글 목록."""
    return sorted(_load(), key=lambda d: d["saved_at"], reverse=True)


def get_draft(draft_id: str) -> dict | None:
    for d in _load():
        if d["id"] == draft_id:
            return d
    return None


def save_draft(title: str, content: str) -> dict:
    drafts = _load()
    new_draft = {
        "id": uuid.uuid4().hex,
        "title": title,
        "content": content,
        "saved_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    drafts.append(new_draft)
    # 오래된 것부터 지워서 최대 MAX_DRAFTS개만 유지한다.
    drafts.sort(key=lambda d: d["saved_at"])
    drafts = drafts[-MAX_DRAFTS:]
    _save(drafts)
    return new_draft


def delete_draft(draft_id: str) -> None:
    drafts = [d for d in _load() if d["id"] != draft_id]
    _save(drafts)
