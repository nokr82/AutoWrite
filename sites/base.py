"""사이트 자동 포스팅 어댑터의 공통 인터페이스.

모든 사이트 어댑터는 이 클래스를 상속해서
- login_url / _do_post 만 구현하면 로그인 세션 저장·재사용, 에러 시 스크린샷 저장이
  공통으로 처리된다.
"""
from __future__ import annotations

import abc
import datetime as dt
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from playwright.sync_api import Page, sync_playwright


@dataclass
class PostContent:
    title: str
    # 에디터(Summernote)가 만든 서식 있는 HTML. 사진이 있던 자리에는
    # <img src="__AUTOWRITE_IMAGE_0__">, __AUTOWRITE_IMAGE_1__ ... 자리표시자가 순서대로
    # 들어있다. 어댑터는 image_paths를 순서대로 실제 업로드한 뒤, 그 결과로 생긴
    # <img> 태그로 해당 자리표시자를 바꿔치기해서 서식과 사진 위치를 그대로 유지한다.
    body: str
    image_paths: list[Path] = field(default_factory=list)


class SiteAdapter(abc.ABC):
    site_id: str
    site_name: str

    def __init__(self, session_dir: Path, debug: bool = False):
        self.session_dir = session_dir
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self.storage_state_path = self.session_dir / f"{self.site_id}.json"
        self.debug = debug  # True면 Playwright Inspector로 일시정지(셀렉터 점검/수정용)

    def has_session(self) -> bool:
        return self.storage_state_path.exists()

    def login_manually(self, wait_for_user: Optional[Callable[[], None]] = None) -> None:
        """브라우저 창을 띄워 사용자가 직접 로그인하게 하고, 완료되면 세션(쿠키)을 저장한다.

        비밀번호는 이 프로그램에 저장되지 않는다 — 로그인 후 쿠키만 저장된다.

        wait_for_user: 로그인 완료 신호를 기다리는 콜백. 넘기지 않으면(터미널에서
        scripts/login_*.py를 직접 실행하는 경우) 기존처럼 콘솔에서 Enter를 누를 때까지
        기다린다. 웹 UI(autowrite.py의 /login/{site_id})에서 호출할 때는 터미널이
        없는 일반 사용자를 위해 "로그인 완료" 버튼 클릭을 기다리는 콜백을 넘겨준다.
        """
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False)
            context = browser.new_context()
            page = context.new_page()
            page.goto(self.login_url)
            try:
                if wait_for_user is not None:
                    wait_for_user()
                else:
                    print(f"[{self.site_name}] 브라우저 창에서 로그인을 완료한 뒤, 이 터미널에서 Enter를 누르세요.")
                    input()
                context.storage_state(path=str(self.storage_state_path))
            finally:
                browser.close()
        print(f"[{self.site_name}] 세션 저장 완료: {self.storage_state_path}")

    def post(self, content: PostContent, headless: bool = False) -> str:
        """저장된 세션으로 글을 게시한다. 성공 시 게시글 URL 문자열을 반환한다.

        headless=False가 기본값이다. 일부 사이트는 게시 시 자동입력 방지(캡차) 등이
        뜰 수 있어, 화면을 보면서 필요하면 직접 처리할 수 있도록 브라우저 창을 띄운다.
        """
        if not self.has_session():
            raise RuntimeError(
                f"[{self.site_name}] 저장된 로그인 세션이 없습니다. 먼저 로그인을 진행하세요."
            )
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=headless, slow_mo=50 if self.debug else 0)
            context = browser.new_context(storage_state=str(self.storage_state_path))
            page = context.new_page()
            try:
                if self.debug:
                    page.pause()  # Playwright Inspector: 셀렉터 확인/수정용
                url = self._do_post(page, content)
            except Exception:
                self._save_error_screenshot(page)
                raise
            finally:
                # 로그인 세션이 갱신됐을 수 있으니 다시 저장해둔다.
                context.storage_state(path=str(self.storage_state_path))
                browser.close()
        return url

    def _save_error_screenshot(self, page: Page) -> None:
        try:
            shot_dir = self.session_dir.parent / "error_screenshots"
            shot_dir.mkdir(parents=True, exist_ok=True)
            ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
            path = shot_dir / f"{self.site_id}_{ts}.png"
            page.screenshot(path=str(path), full_page=True)
            print(f"[{self.site_name}] 오류 발생 — 스크린샷 저장: {path}")
        except Exception:
            pass

    @property
    @abc.abstractmethod
    def login_url(self) -> str:
        ...

    @abc.abstractmethod
    def _do_post(self, page: Page, content: PostContent) -> str:
        """실제 게시 로직(사이트별 구현). 게시된 글의 URL을 반환한다."""
        ...
