"""사이트별 '오늘 이미 게시했는지' 기록. 하루 사이트당 1건 제한을 강제하기 위한 용도."""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from config import POST_LOG_PATH, load_config


def _load() -> dict:
    if not POST_LOG_PATH.exists():
        return {}
    with open(POST_LOG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _save(data: dict) -> None:
    POST_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(POST_LOG_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def today_str() -> str:
    return dt.date.today().isoformat()


def last_posted_date(site_id: str) -> str | None:
    return _load().get(site_id)


def can_post_today(site_id: str) -> bool:
    if load_config().get("daily_limit", "Y") != "Y":
        return True  # config.json 의 daily_limit 이 "N"이면 하루 제한 없이 게시 가능
    return last_posted_date(site_id) != today_str()


def mark_posted(site_id: str) -> None:
    data = _load()
    data[site_id] = today_str()
    _save(data)
