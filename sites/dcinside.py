"""디시인사이드 자동 포스팅 어댑터.

실제 계정(마이너 갤러리)으로 검증된 내용:
- 마이너 갤러리는 글쓰기 주소가 board/write 가 아니라 mgallery/board/write 이다.
  (major/minor를 잘못 설정하면 글쓰기 폼 대신 갤러리 목록 페이지로 리다이렉트되고,
  #subject 를 못 찾아 타임아웃난다 — 실제로 겪었던 문제)
- 본문 에디터는 iframe이 아니라 Summernote(jQuery 플러그인)이고, 원본 엘리먼트는
  id="memo" 인 <textarea>다. 티스토리의 TinyMCE와 마찬가지로
  $('#memo').summernote('code', html) 로 직접 넣는 게 가장 안정적이다.
- 툴바의 '이미지' 버튼은 인라인 다이얼로그가 아니라 새 팝업 창
  (window.open('/upload/image', ...))을 띄운다. 그 팝업 안에서
  input[name="files[]"] 에 파일을 넣고 '완료'(button.btn_apply)를 누르면
  팝업이 닫히면서 메인 에디터에 실제 <img src="https://dcimg...*"> 태그가 삽입된다.
- 등록(제출) 버튼은 페이지에 '등록' 텍스트를 가진 버튼이 여러 개 있어(자동짤/AI이미지/
  링크 등록 등) 텍스트만으로는 못 고르고, button.btn_svc.write 로 짚어야 유일하게 잡힌다.

주의: 디시인사이드는 게시글 등록 시 자동입력 방지(캡차)가 뜰 수 있다. 이 프로그램은
캡차를 자동으로 우회/풀지 않는다 — 캡차가 감지되면 브라우저 창에서 사람이
직접 풀 수 있도록 자동으로 일시정지하고 터미널에서 Enter 입력을 기다린다.
"""
from __future__ import annotations

import re

from playwright.sync_api import Page

from config import load_config
from .base import PostContent, SiteAdapter

DEFAULT_SELECTORS = {
    "title_input": "#subject",
    # 본문 에디터(Summernote)의 원본 textarea. $(this).summernote(...) 로 조작한다.
    "editor_textarea_id": "memo",
    # 툴바의 '이미지' 버튼 — 클릭하면 업로드 팝업 창이 새로 뜬다.
    "image_button": "button.note-btn[aria-label='이미지']",
    # 팝업 창 안의 파일 input과 '완료' 버튼
    "popup_file_input": "input[name='files[]']",
    "popup_apply_button": "button.btn_apply",
    # 페이지에 '등록' 버튼이 여러 개라 이 클래스 조합으로 정확히 짚는다.
    "submit_button": "button.btn_svc.write",
    "captcha_hint": "img[id*='captcha'], [id*='kcaptcha'], .captcha",
}


class DcInsideAdapter(SiteAdapter):
    site_id = "dcinside"
    site_name = "디시인사이드"

    @property
    def login_url(self) -> str:
        return "https://www.dcinside.com/"

    def _selectors(self) -> dict:
        cfg = load_config()
        overrides = cfg.get("selectors", {}).get("dcinside", {})
        return {**DEFAULT_SELECTORS, **overrides}

    def _write_url(self) -> str:
        cfg = load_config()
        gallery_id = cfg["dcinside"]["gallery_id"]
        if not gallery_id or "여기에" in gallery_id:
            raise RuntimeError("config.json 의 dcinside.gallery_id 를 먼저 설정하세요.")
        gallery_type = cfg["dcinside"].get("gallery_type", "major")
        path = "mgallery/board/write" if gallery_type == "minor" else "board/write"
        return f"https://gall.dcinside.com/{path}/?id={gallery_id}"

    def _get_editor_content(self, page: Page, sel: dict) -> str:
        return page.evaluate(
            "(id) => $('#' + id).summernote('code')", sel["editor_textarea_id"]
        )

    def _set_editor_content(self, page: Page, sel: dict, html: str) -> None:
        page.evaluate(
            "([id, html]) => $('#' + id).summernote('code', html)",
            [sel["editor_textarea_id"], html],
        )

    def _upload_single_image(self, page: Page, sel: dict, image_path) -> str:
        """이미지 업로드 팝업을 열어 파일을 첨부하고 '완료'를 누른 뒤,
        에디터에 새로 삽입된 실제 <img> 태그를 반환한다.
        """
        before = self._get_editor_content(page, sel)

        with page.context.expect_page(timeout=5000) as popup_info:
            page.click(sel["image_button"])
        popup = popup_info.value
        popup.wait_for_load_state("networkidle")

        try:
            popup.set_input_files(sel["popup_file_input"], str(image_path))
            popup.wait_for_timeout(1500)
            popup.click(sel["popup_apply_button"])
            page.wait_for_timeout(2000)
        except Exception as e:
            if not popup.is_closed():
                popup.close()
            raise RuntimeError(
                f"이미지 업로드 팝업 처리 중 실패했습니다 ({e}). debug=True 로 재실행해 "
                f"popup_file_input / popup_apply_button 셀렉터를 확인하세요."
            )

        after = self._get_editor_content(page, sel)
        before_imgs = set(re.findall(r"<img[^>]*>", before))
        after_imgs = re.findall(r"<img[^>]*>", after)
        new_tag = next((t for t in after_imgs if t not in before_imgs), None)
        return new_tag or (after_imgs[-1] if after_imgs else "")

    def _do_post(self, page: Page, content: PostContent) -> str:
        sel = self._selectors()

        page.goto(self._write_url())
        page.wait_for_load_state("networkidle")

        # 제목
        page.fill(sel["title_input"], content.title)

        # 이미지를 하나씩 실제로 업로드해서 디시인사이드가 만들어준 진짜 <img> 태그를 받는다.
        real_img_tags = [
            self._upload_single_image(page, sel, image_path)
            for image_path in content.image_paths
        ]

        # 사용자가 에디터에서 꾸민 서식(HTML)에서 사진 자리표시자를 실제 <img> 태그로 교체
        body_html = content.body
        for idx, tag in enumerate(real_img_tags):
            if tag:
                body_html = body_html.replace(f'<img src="__AUTOWRITE_IMAGE_{idx}__">', tag)

        # 본문 삽입: Summernote 표준 API로 직접 넣는다 (자리표시자 치환된 최종 HTML을 한 번에 적용)
        try:
            self._set_editor_content(page, sel, body_html)
        except Exception as e:
            raise RuntimeError(
                f"본문 입력 단계에서 실패했습니다 ({e}). "
                f"debug=True 로 재실행해 Summernote(#{sel['editor_textarea_id']}) 존재 여부를 확인하세요."
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

        page.click(sel["submit_button"])
        page.wait_for_load_state("networkidle")

        return page.url
