"""자동 포스팅 로컬 웹앱.

사용자가 직접 작성한 글(사진 + 텍스트)을 입력받아, 선택한 사이트(티스토리 / 디시인사이드)의
본인 계정으로 그대로 게시한다. 글쓰기는 AI가 하지 않는다 — 입력받은 내용을 그대로 올릴 뿐이다.
하루 사이트당 게시글 1건으로 제한한다.

실행: python autowrite.py  (http://127.0.0.1:8000 접속)
사전 준비: scripts/login_tistory.py, scripts/login_dcinside.py 로 각 사이트에 먼저 로그인해둘 것.
"""
from __future__ import annotations

import base64
import re
import uuid
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from config import SESSION_DIR, UPLOAD_DIR, load_config
from postlog import can_post_today, mark_posted
from sites import SITE_ADAPTERS, PostContent

app = FastAPI(title="자동 포스팅")
templates = Jinja2Templates(directory="templates")

# 에디터(Summernote)가 사진을 base64로 <img>에 직접 담아 보낸다.
# 실제 사이트에는 진짜 파일로 업로드해야 하므로, 여기서 base64를 파일로 빼내고
# 그 자리엔 자리표시자만 남겨서 각 사이트 어댑터가 실제 업로드 후 끼워넣게 한다.
_DATA_URI_IMG_RE = re.compile(r'<img[^>]*?src="data:(image/\w+);base64,([^"]+)"[^>]*?>')


def _extract_embedded_images(html: str, dest_dir: Path) -> tuple[str, list[Path]]:
    image_paths: list[Path] = []

    def _replace(match: re.Match) -> str:
        mime, b64data = match.group(1), match.group(2)
        ext = mime.split("/")[-1].replace("jpeg", "jpg")
        idx = len(image_paths)
        dest_dir.mkdir(parents=True, exist_ok=True)
        path = dest_dir / f"image_{idx}.{ext}"
        path.write_bytes(base64.b64decode(b64data))
        image_paths.append(path)
        return f'<img src="__AUTOWRITE_IMAGE_{idx}__">'

    processed = _DATA_URI_IMG_RE.sub(_replace, html)
    return processed, image_paths

try:
    load_config()
except RuntimeError as e:
    # config.json이 없으면 기본 템플릿이 생성된다. 서버는 계속 띄우되 콘솔에 안내만 출력한다.
    print(e)


def _site_status() -> list[dict]:
    statuses = []
    for site_id, adapter_cls in SITE_ADAPTERS.items():
        adapter = adapter_cls(session_dir=SESSION_DIR)
        statuses.append(
            {
                "id": site_id,
                "name": adapter.site_name,
                "has_session": adapter.has_session(),
                "can_post": can_post_today(site_id),
            }
        )
    return statuses


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(
        request, "index.html", {"sites": _site_status(), "messages": []}
    )


@app.post("/post", response_class=HTMLResponse)
def post(
    request: Request,
    title: str = Form(...),
    content: str = Form(...),
    sites: list[str] = Form(default=[]),
):
    messages: list[dict] = []

    if not sites:
        messages.append({"level": "error", "text": "게시할 사이트를 하나 이상 선택하세요."})
        return templates.TemplateResponse(
            request, "index.html", {"sites": _site_status(), "messages": messages}
        )

    # 에디터가 사진을 base64로 담아 보낸 <img>를 실제 파일로 빼내고 자리표시자로 치환
    req_dir = UPLOAD_DIR / uuid.uuid4().hex
    body_html, image_paths = _extract_embedded_images(content, req_dir)
    post_content = PostContent(title=title, body=body_html, image_paths=image_paths)

    for site_id in sites:
        adapter_cls = SITE_ADAPTERS.get(site_id)
        if adapter_cls is None:
            messages.append({"level": "error", "text": f"알 수 없는 사이트: {site_id}"})
            continue

        adapter = adapter_cls(session_dir=SESSION_DIR)

        if not adapter.has_session():
            messages.append(
                {"level": "error", "text": f"[{adapter.site_name}] 로그인 세션이 없습니다. 먼저 로그인 스크립트를 실행하세요."}
            )
            continue
        if not can_post_today(site_id):
            messages.append({"level": "error", "text": f"[{adapter.site_name}] 오늘 이미 게시했습니다 (사이트당 하루 1건)."})
            continue

        try:
            url = adapter.post(post_content, headless=False)
            mark_posted(site_id)
            messages.append(
                {"level": "success", "text": f"[{adapter.site_name}] 게시 완료: <a href='{url}' target='_blank'>{url}</a>"}
            )
        except Exception as e:
            messages.append({"level": "error", "text": f"[{adapter.site_name}] 게시 실패: {e}"})

    return templates.TemplateResponse(
        request, "index.html", {"sites": _site_status(), "messages": messages}
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("autowrite:app", host="127.0.0.1", port=8000, reload=False)
