"""디시인사이드 자동 포스팅 어댑터.

주의:
- 아래 셀렉터는 일반적인 갤러리 글쓰기 폼 구조를 가정한 '최선의 추정치'다.
  실제 갤러리(정식/마이너)에 따라 UI가 조금씩 다를 수 있으니
  SiteAdapter(debug=True)로 먼저 한 번 확인해보는 걸 권장한다.
- 이미지를 하나씩 올리고 에디터에 실제로 삽입되는지 diff로 확인하는 방식은
  티스토리에서는 실제 계정으로 검증됐지만, 디시인사이드는 아직 실제 계정으로
  검증하지 못했다. 갤러리 에디터가 파일 첨부 시 본문에 자동으로 이미지를
  삽입해주지 않는 구조라면(첨부파일로만 붙는 방식이라면) 동작이 다를 수 있다.
- 디시인사이드는 게시글 등록 시 자동입력 방지(캡차)가 뜰 수 있다. 이 프로그램은
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
    "content_iframe": "#write_iframe, iframe[name='innerIframe']",
    "file_input": "input[type='file']",
    "submit_button": "button:has-text('등록'), #dc_submit",
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

    def _do_post(self, page: Page, content: PostContent) -> str:
        sel = self._selectors()

        page.goto(self._write_url())
        page.wait_for_load_state("networkidle")

        # 제목
        page.fill(sel["title_input"], content.title)

        # 이미지를 하나씩 첨부하고, 에디터 본문에 실제로 들어간 <img> 태그를 diff로 확인한다.
        # (첨부 즉시 본문에 이미지가 삽입되는 SmartEditor류 UI를 가정 — 검증되지 않음)
        real_img_tags: list[str] = []
        if content.image_paths:
            try:
                frame = page.frame_locator(sel["content_iframe"])
                body_el = frame.locator("body")
                for image_path in content.image_paths:
                    before = body_el.evaluate("el => el.innerHTML")
                    page.set_input_files(sel["file_input"], str(image_path))
                    page.wait_for_timeout(1500)
                    after = body_el.evaluate("el => el.innerHTML")

                    before_imgs = set(re.findall(r"<img[^>]*>", before))
                    after_imgs = re.findall(r"<img[^>]*>", after)
                    new_tag = next((t for t in after_imgs if t not in before_imgs), None)
                    real_img_tags.append(new_tag or "")
            except Exception as e:
                raise RuntimeError(
                    f"이미지 첨부 단계에서 실패했습니다 ({e}). debug=True 로 재실행해 셀렉터를 확인하세요."
                )

        # 사용자가 에디터에서 꾸민 서식(HTML)에서 사진 자리표시자를 실제 <img> 태그로 교체
        body_html = content.body
        for idx, tag in enumerate(real_img_tags):
            if tag:
                body_html = body_html.replace(f'<img src="__AUTOWRITE_IMAGE_{idx}__">', tag)

        # 본문 삽입 (에디터가 iframe 안 contenteditable 인 경우가 많음)
        try:
            frame = page.frame_locator(sel["content_iframe"])
            body_el = frame.locator("body")
            body_el.click()
            body_el.evaluate("(el, html) => { el.innerHTML = html; }", body_html)
        except Exception as e:
            raise RuntimeError(
                f"본문 입력 단계에서 실패했습니다 ({e}). debug=True 로 재실행해 셀렉터를 확인하세요."
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
