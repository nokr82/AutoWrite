"""사이트별 설정(블로그 주소, 갤러리 ID 등)을 config.json에서 읽어온다.

비밀번호는 저장하지 않는다. 로그인은 브라우저 세션(쿠키) 저장 방식만 사용한다.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# PyInstaller로 exe를 만들면 onefile 모드에서 __file__은 실행할 때마다 새로 풀리는
# 임시 폴더(_MEIPASS)를 가리켜서 실행할 때마다 사라진다. config.json / storage/ 처럼
# 계속 남아있어야 하는 데이터는 실제 exe 파일이 있는 폴더를 기준으로 잡아야 한다.
if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).resolve().parent
else:
    BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.json"
SESSION_DIR = BASE_DIR / "storage" / "sessions"
UPLOAD_DIR = BASE_DIR / "storage" / "uploads"
POST_LOG_PATH = BASE_DIR / "storage" / "post_log.json"

DEFAULT_CONFIG = {
    # "Y"면 사이트당 하루 1건 제한을 적용, "N"이면 제한 없이 몇 번이든 게시 가능.
    "daily_limit": "Y",
    "tistory": {
        # 예: 블로그 주소가 https://myblog.tistory.com 이면 "myblog"
        "blog_name": "여기에_티스토리_블로그이름_입력",
        "category_name": "",  # 비워두면 기본 카테고리 사용
    },
    "dcinside": {
        # 갤러리 주소의 id 파라미터. 예: gall.dcinside.com/board/lists/?id=programming
        "gallery_id": "여기에_갤러리ID_입력",
        # 마이너 갤러리면 "minor", 정식 갤러리면 "major"
        "gallery_type": "major",
    },
    # 사이트별 셀렉터를 덮어쓰고 싶을 때 사용 (사이트 개편으로 셀렉터가 깨졌을 때 여기만 수정)
    "selectors": {},
}


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        save_config(DEFAULT_CONFIG)
        raise RuntimeError(
            f"config.json이 없어서 기본 템플릿을 생성했습니다.\n"
            f"{CONFIG_PATH} 파일을 열어 blog_name, gallery_id 등을 채운 뒤 다시 실행하세요."
        )
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_config(cfg: dict) -> None:
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
