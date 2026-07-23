"""자동 포스팅 로컬 웹앱.

사용자가 직접 작성한 글(사진 + 텍스트)을 입력받아, 선택한 사이트(티스토리 / 디시인사이드)의
본인 계정으로 그대로 게시한다. 글쓰기는 AI가 하지 않는다 — 입력받은 내용을 그대로 올릴 뿐이다.
하루 사이트당 게시글 1건으로 제한한다.

실행: python autowrite.py  (http://127.0.0.1:8000 접속)
사전 준비: scripts/login_tistory.py, scripts/login_dcinside.py 로 각 사이트에 먼저 로그인해둘 것.
"""
from __future__ import annotations

import base64
import os
import re
import sys
import threading
import uuid
from pathlib import Path

from config import BROWSERS_DIR

# Chromium 저장 위치를 exe 옆 고정 폴더로 강제한다. playwright를 import하는 그 무엇보다도
# (sites 패키지든, 아래 _ensure_chromium_installed의 지역 import든) 먼저 설정해야 한다 —
# 안 그러면 onefile exe가 실행마다 새로 만드는 임시 폴더(_MEIPASS) 밑을 기본값으로 써서,
# 실행할 때마다 브라우저를 다시 받아야 하고 다운로드 도중엔 "Executable doesn't exist" 에러가 난다.
os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(BROWSERS_DIR))

if sys.platform == "win32":
    # 한국어 Windows 콘솔 기본 코드페이지(cp949)와 이 파일의 UTF-8 문자열이 어긋나면
    # exe 실행 시 콘솔에 안내 메시지가 깨져 보인다. 콘솔 출력 코드페이지와 stdout/stderr
    # 인코딩을 모두 UTF-8로 맞춰서 어떤 시스템 로케일에서도 한글이 정상 표시되게 한다.
    import ctypes

    ctypes.windll.kernel32.SetConsoleOutputCP(65001)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from config import SESSION_DIR, UPLOAD_DIR, load_config, save_config
from drafts import delete_draft, get_draft, list_drafts, save_draft
from postlog import can_post_today, mark_posted
from sites import SITE_ADAPTERS, PostContent


def _resource_path(relative: str) -> Path:
    """읽기 전용 리소스(templates 등) 경로를 구한다.

    exe(onefile)로 실행 중이면 PyInstaller가 풀어놓은 임시 폴더(_MEIPASS) 안에서 찾고,
    아니면 이 파일이 있는 폴더를 기준으로 찾는다. config.BASE_DIR과 달리 이건 매번
    새로 풀리는 읽기 전용 번들 리소스용이라 exe 폴더가 아니라 _MEIPASS를 봐야 한다.
    """
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / relative


app = FastAPI(title="자동 포스팅")
templates = Jinja2Templates(directory=str(_resource_path("templates")))

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
        request, "index.html", {"sites": _site_status(), "messages": [], "drafts": list_drafts()}
    )


def _load_config_safe() -> dict:
    """설정 화면에서 쓰는 load_config 래퍼.

    config.json이 아직 없으면 load_config()가 기본 템플릿을 만들면서 RuntimeError를
    던지는데(콘솔용 안내 메시지), 설정 화면에서는 그 템플릿을 그냥 다시 읽어서 보여준다.
    """
    try:
        return load_config()
    except RuntimeError:
        return load_config()


@app.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request):
    return templates.TemplateResponse(
        request, "settings.html", {"cfg": _load_config_safe(), "messages": []}
    )


@app.post("/settings", response_class=HTMLResponse)
def settings_save(
    request: Request,
    tistory_blog_name: str = Form(""),
    tistory_category_name: str = Form(""),
    dcinside_gallery_id: str = Form(""),
    dcinside_gallery_type: str = Form("major"),
    naver_cafe_club_id: str = Form(""),
    naver_cafe_menu_id: str = Form(""),
    daily_limit: str = Form("N"),  # 체크박스 미체크 시 폼에서 아예 빠지므로 기본값은 "N"
):
    cfg = _load_config_safe()
    cfg["tistory"]["blog_name"] = tistory_blog_name.strip()
    cfg["tistory"]["category_name"] = tistory_category_name.strip()
    cfg["dcinside"]["gallery_id"] = dcinside_gallery_id.strip()
    cfg["dcinside"]["gallery_type"] = dcinside_gallery_type
    cfg["naver_cafe"]["club_id"] = naver_cafe_club_id.strip()
    cfg["naver_cafe"]["menu_id"] = naver_cafe_menu_id.strip()
    cfg["daily_limit"] = daily_limit
    save_config(cfg)
    return templates.TemplateResponse(
        request,
        "settings.html",
        {"cfg": cfg, "messages": [{"level": "success", "text": "설정을 저장했습니다."}]},
    )


# 사이트별로 "로그인 진행 중" 여부를 들고 있는다. 터미널의 input() 대신, 웹 페이지의
# '로그인 완료' 버튼이 눌리면 이 Event를 set()해서 로그인 창을 열어둔 채 기다리고 있는
# /login/{site_id} 요청(을 처리 중인 스레드)을 깨운다. 일반 사용자는 터미널을 몰라도
# 웹 페이지 버튼만으로 로그인을 끝낼 수 있다.
_pending_logins: dict[str, threading.Event] = {}
LOGIN_TIMEOUT_SECONDS = 300  # 5분 안에 '로그인 완료'를 안 누르면 자동으로 취소하고 창을 닫는다.


@app.post("/login/{site_id}")
def login(site_id: str):
    """웹 UI에서 '로그인하기' 버튼을 누르면 호출된다.

    scripts/login_*.py 를 사용자가 직접 터미널에서 실행하는 대신, 같은 로직
    (SiteAdapter.login_manually)을 서버가 대신 호출해 로그인용 브라우저 창을 띄운다.
    이 요청은 사용자가 (다른 요청인) /login/{site_id}/confirm 을 호출할 때까지, 즉
    웹 페이지의 '로그인 완료' 버튼을 누를 때까지 응답하지 않고 대기한다.
    """
    adapter_cls = SITE_ADAPTERS.get(site_id)
    if adapter_cls is None:
        return JSONResponse({"ok": False, "error": f"알 수 없는 사이트: {site_id}"}, status_code=404)
    if site_id in _pending_logins:
        return JSONResponse({"ok": False, "error": "이미 로그인이 진행 중입니다."}, status_code=409)

    event = threading.Event()
    _pending_logins[site_id] = event
    try:
        adapter = adapter_cls(session_dir=SESSION_DIR)

        def wait_for_user() -> None:
            if not event.wait(timeout=LOGIN_TIMEOUT_SECONDS):
                raise TimeoutError(
                    "시간 안에 '로그인 완료' 버튼이 눌리지 않아 취소되었습니다. 다시 시도해주세요."
                )

        adapter.login_manually(wait_for_user=wait_for_user)
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)
    finally:
        _pending_logins.pop(site_id, None)
    return JSONResponse({"ok": True})


@app.post("/login/{site_id}/confirm")
def login_confirm(site_id: str):
    """웹 페이지의 '로그인 완료' 버튼이 호출한다. 대기 중인 /login/{site_id} 요청을 깨운다."""
    event = _pending_logins.get(site_id)
    if event is None:
        return JSONResponse({"ok": False, "error": "진행 중인 로그인이 없습니다."}, status_code=404)
    event.set()
    return JSONResponse({"ok": True})


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
            request,
            "index.html",
            {"sites": _site_status(), "messages": messages, "drafts": list_drafts()},
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
        request,
        "index.html",
        {"sites": _site_status(), "messages": messages, "drafts": list_drafts()},
    )


@app.post("/drafts")
def create_draft(title: str = Form(""), content: str = Form("")):
    """'임시 저장' 버튼이 호출한다. 최대 5개까지만 보관되고 넘으면 가장 오래된 것부터 지워진다."""
    save_draft(title, content)
    return JSONResponse({"ok": True, "drafts": list_drafts()})


@app.get("/drafts/{draft_id}")
def read_draft(draft_id: str):
    """저장된 글 목록에서 하나를 눌렀을 때 제목/본문을 돌려준다 (에디터에 그대로 채워넣기 위함)."""
    draft = get_draft(draft_id)
    if draft is None:
        return JSONResponse({"ok": False, "error": "찾을 수 없는 임시 저장 글입니다."}, status_code=404)
    return JSONResponse({"ok": True, "draft": draft})


@app.post("/drafts/{draft_id}/delete")
def remove_draft(draft_id: str):
    delete_draft(draft_id)
    return JSONResponse({"ok": True, "drafts": list_drafts()})


def _ensure_chromium_installed() -> None:
    """Chromium 설치 여부를 확인하고, 없으면 최초 1회 내려받는다.

    exe로 배포된 상태에서는 사용자가 터미널에 `playwright install chromium`을
    직접 칠 수 없으므로, 서버 실행 전에 여기서 대신 확인/설치한다. playwright CLI는
    이미 설치돼 있으면 몇 초 안에 그냥 넘어가는 멱등 명령이라 매번 호출해도 괜찮다.
    (executable_path 존재 여부만으로 판단하면 환경에 따라 오탐이 있을 수 있어,
    안내 메시지 출력 여부만 이 값으로 결정하고 실제 설치 확인은 항상 CLI에 맡긴다)
    """
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        already_installed = Path(p.chromium.executable_path).exists()

    if not already_installed:
        print("Chromium 브라우저를 처음 내려받습니다. (인터넷 연결 필요, 몇 분 걸릴 수 있습니다)")

    original_argv = sys.argv
    try:
        sys.argv = ["playwright", "install", "chromium"]
        from playwright.__main__ import main as playwright_cli_main

        playwright_cli_main()
    except SystemExit as e:
        if e.code not in (None, 0):
            print("Chromium 준비에 실패했습니다. 인터넷 연결을 확인한 뒤 다시 실행해주세요.")
            raise
    finally:
        sys.argv = original_argv


def _open_browser_when_ready(url: str) -> None:
    import threading
    import webbrowser

    threading.Timer(1.5, lambda: webbrowser.open(url)).start()


if __name__ == "__main__":
    import uvicorn

    _ensure_chromium_installed()
    _open_browser_when_ready("http://127.0.0.1:8000")
    # 문자열("autowrite:app")로 넘기면 uvicorn이 모듈을 이름으로 다시 import하는데,
    # PyInstaller로 묶은 exe 안에는 "autowrite"라는 이름의 파일이 실제로 없어서 실패한다.
    # app 객체를 직접 넘기면 reload 기능만 못 쓸 뿐(reload=False라 어차피 안 씀) 동일하게 동작한다.
    uvicorn.run(app, host="127.0.0.1", port=8000)
