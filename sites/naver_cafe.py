"""네이버 카페 자동 포스팅 어댑터.

실제 계정(club_id/menu_id 설정 완료 상태)으로 검증된 내용:
- 네이버 카페 글쓰기 에디터(SmartEditor ONE)는 티스토리(TinyMCE)/디시인사이드(Summernote)와
  달리 "완성된 HTML을 통째로 주입"하는 방식이 통하지 않는다. 제목은 실제로는 contenteditable이
  아니라 평범한 `<textarea class="textarea_input">`이고, 본문은 각 문단/이미지가 별도의
  "컴포넌트"(블록)로 관리되는 구조라 클립보드 paste 이벤트를 합성해서 던져도 무시된다
  (실제로 시도해봤고 DOM에 전혀 반영되지 않는 것을 확인함).
- 대신 실제 사용자처럼 "타이핑"하는 방식은 정상 동작한다: 본문 문단을 한 번 클릭해 포커스를
  잡은 뒤 `page.keyboard.type()`으로 텍스트를 입력하고, `Enter`로 문단을 나누고,
  `Control+B`/`Control+I`를 토글해서 굵게/기울임을 반영할 수 있다.
- 사진은 툴바의 '사진' 버튼(`[data-name='image']`)을 누르면 OS 파일 선택창이 뜨고,
  파일을 넣으면 **현재 커서 위치에 바로 삽입**되면서 그 아래에 새 빈 문단이 자동으로 생기고
  포커스도 그리로 자동 이동한다 — 그래서 텍스트→이미지→텍스트 순서로 그냥 이어서
  타이핑/업로드를 반복하면 사용자가 원래 편집기에서 배치한 순서 그대로 재현된다.
  (다른 두 어댑터처럼 "일단 다 업로드하고 나중에 자리표시자를 치환"하는 방식이 아니라,
  본문을 순서대로 훑으면서 텍스트는 타이핑, 이미지는 그 자리에서 바로 업로드하는 방식.)
- 이미지 업로드 직후에는 방금 삽입한 이미지 주변에 뜨는 플로팅 서식 툴바
  (`.se-flayer-unified-toolbar`)가 다음 문단 위치를 가려 마우스 클릭을 방해할 수 있다
  (Playwright의 클릭 액션어빌리티 체크에서 "intercepts pointer events"로 실패함).
  하지만 파일 선택 직후에는 별도로 클릭하지 않아도 포커스가 이미 새 문단에 가 있어서
  바로 타이핑이 먹힌다 — 그래서 이 어댑터는 최초 1회(첫 문단)를 제외하면 본문 입력 중
  추가로 클릭하지 않는다(클릭했다가 플로팅 툴바에 막히는 문제를 아예 피하기 위함).
- 등록 버튼은 `<button>`이 아니라 `<a role="button">`이라 CSS로 `button:has-text(...)`를
  쓰면 못 찾는다. `page.get_by_role("button", name="등록", exact=True)`처럼 접근성 role
  기반으로 찾아야 한다(exact=True가 없으면 "임시등록"도 같이 매치되어 버린다).

이런 사정 때문에, 사용자가 웹 UI 에디터(Summernote)에서 굵게/기울임/문단/사진으로 꾸민 HTML을
`html.parser.HTMLParser`로 순서대로 훑어서 "타이핑 동작들의 시퀀스"로 변환한 뒤 재생하는
방식으로 구현했다(목록 항목은 각각 새 문단으로, 링크는 텍스트만 남고 하이퍼링크 자체는
유지되지 않는 등 일부 서식은 단순화된다).
"""
from __future__ import annotations

import re
from html.parser import HTMLParser

from playwright.sync_api import Page

from config import load_config
from .base import PostContent, SiteAdapter

DEFAULT_SELECTORS = {
    # 제목 입력창은 SmartEditor 영역이 아니라 일반 textarea다.
    "title_input": "textarea.textarea_input",
    # 본문 영역의 첫 문단 (최초 포커스를 잡기 위한 용도)
    "body_first_paragraph": ".se-components-wrap .se-text-paragraph",
    # 툴바의 '사진' 버튼 — 누르면 OS 파일 선택창이 뜨고, 선택하면 현재 커서 위치에 삽입된다.
    "image_toolbar_button": "[data-name='image']",
    # 등록 버튼은 <a role="button">이라 get_by_role(name=이 값)으로 찾는다.
    "submit_button_text": "등록",
    "captcha_hint": "img[id*='captcha'], [id*='ncaptcha'], .captcha",
}

_PLACEHOLDER_RE = re.compile(r"__AUTOWRITE_IMAGE_(\d+)__")


class _BodyOpsParser(HTMLParser):
    """본문 HTML을 (문단 나누기 / 텍스트 타이핑 / 이미지 삽입) 순서열로 변환한다."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.ops: list[tuple] = []
        self._bold_depth = 0
        self._italic_depth = 0

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in ("b", "strong"):
            self._bold_depth += 1
        elif tag in ("i", "em"):
            self._italic_depth += 1
        elif tag == "br":
            self.ops.append(("break",))
        elif tag == "img":
            src = dict(attrs).get("src") or ""
            m = _PLACEHOLDER_RE.search(src)
            if m:
                self.ops.append(("image", int(m.group(1))))

    def handle_endtag(self, tag: str) -> None:
        if tag in ("b", "strong"):
            self._bold_depth = max(0, self._bold_depth - 1)
        elif tag in ("i", "em"):
            self._italic_depth = max(0, self._italic_depth - 1)
        elif tag in ("p", "div", "li"):
            self.ops.append(("break",))

    def handle_data(self, data: str) -> None:
        if not data.strip():
            return
        self.ops.append(("text", data, self._bold_depth > 0, self._italic_depth > 0))


class NaverCafeAdapter(SiteAdapter):
    site_id = "naver_cafe"
    site_name = "네이버 카페"

    def __init__(self, session_dir, debug: bool = False, board: dict | None = None):
        super().__init__(session_dir, debug=debug)
        # 게시 대상 게시판(club_id/menu_id). 넘기지 않으면(로그인 등 게시판과 무관한
        # 용도) _write_url()이 config.json의 첫 게시판으로 폴백한다.
        self.board = board

    @property
    def login_url(self) -> str:
        return "https://nid.naver.com/nidlogin.login"

    def _selectors(self) -> dict:
        cfg = load_config()
        overrides = cfg.get("selectors", {}).get("naver_cafe", {})
        return {**DEFAULT_SELECTORS, **overrides}

    def _write_url(self) -> str:
        board = self.board
        if board is None:
            boards = load_config()["naver_cafe"]["boards"]
            board = boards[0] if boards else {}
        club_id = board.get("club_id", "")
        menu_id = board.get("menu_id", "")
        if not club_id or "여기에" in club_id:
            raise RuntimeError("config.json 의 naver_cafe.boards 에 club_id 를 먼저 설정하세요.")
        if not menu_id or "여기에" in menu_id:
            raise RuntimeError("config.json 의 naver_cafe.boards 에 menu_id 를 먼저 설정하세요.")
        return f"https://cafe.naver.com/ca-fe/cafes/{club_id}/menus/{menu_id}/articles/write"

    def _upload_image_at_cursor(self, page: Page, sel: dict, image_path) -> None:
        """현재 커서 위치에 사진을 삽입한다. 업로드가 끝나면 에디터가 알아서 새 빈 문단을
        만들고 포커스를 그리로 옮겨주므로, 호출 쪽에서 별도로 다시 클릭할 필요가 없다.
        """
        try:
            with page.expect_file_chooser(timeout=5000) as fc_info:
                page.click(sel["image_toolbar_button"])
            fc_info.value.set_files(str(image_path))
            page.wait_for_timeout(2000)
        except Exception as e:
            raise RuntimeError(
                f"이미지 업로드에 실패했습니다 ({e}). debug=True 로 재실행해서 "
                f"image_toolbar_button 셀렉터를 확인한 뒤 config.json 의 "
                f"selectors.naver_cafe.image_toolbar_button 에 지정하세요."
            )

    def _type_body(self, page: Page, sel: dict, content: PostContent) -> None:
        parser = _BodyOpsParser()
        parser.feed(content.body)

        page.click(sel["body_first_paragraph"])

        for op in parser.ops:
            kind = op[0]
            if kind == "break":
                page.keyboard.press("Enter")
            elif kind == "text":
                _, text, bold, italic = op
                if bold:
                    page.keyboard.press("Control+B")
                if italic:
                    page.keyboard.press("Control+I")
                page.keyboard.type(text)
                if italic:
                    page.keyboard.press("Control+I")
                if bold:
                    page.keyboard.press("Control+B")
            elif kind == "image":
                idx = op[1]
                if 0 <= idx < len(content.image_paths):
                    self._upload_image_at_cursor(page, sel, content.image_paths[idx])

    def _do_post(self, page: Page, content: PostContent) -> str:
        sel = self._selectors()

        page.goto(self._write_url())
        page.wait_for_load_state("networkidle")

        # 임시저장 이어쓰기 확인 팝업이 뜨면 새 글로 진행 (있을 때만)
        try:
            page.get_by_text("취소", exact=True).click(timeout=3000)
        except Exception:
            pass

        try:
            page.fill(sel["title_input"], content.title)
        except Exception as e:
            raise RuntimeError(
                f"제목 입력 단계에서 실패했습니다 ({e}). "
                f"debug=True 로 재실행해 title_input 셀렉터를 확인하세요."
            )

        try:
            self._type_body(page, sel, content)
        except Exception as e:
            raise RuntimeError(
                f"본문 입력 단계에서 실패했습니다 ({e}). "
                f"debug=True 로 재실행해 body_first_paragraph 셀렉터를 확인하세요."
            )

        # 캡차(자동입력 방지)가 떴는지 확인 — 뜨면 우회하지 않고 사람이 직접 풀도록 대기
        try:
            if page.locator(sel["captcha_hint"]).first.is_visible(timeout=2000):
                print(
                    f"[{self.site_name}] 자동입력 방지(캡차)가 감지되었습니다. "
                    f"브라우저 창에서 직접 해결한 뒤 이 터미널에서 Enter를 누르세요."
                )
                input()
        except Exception:
            pass  # 캡차 요소가 없으면 정상 진행

        # 방금 삽입한 사진 주변의 플로팅 서식 툴바가 등록 버튼과 겹칠 일은 없지만,
        # 혹시 남아있는 팝업(글감 검색 등)을 닫아두고 등록한다.
        page.keyboard.press("Escape")
        page.get_by_role("button", name=sel["submit_button_text"], exact=True).click()
        page.wait_for_load_state("networkidle")

        return page.url
