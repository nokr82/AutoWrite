"""티스토리 자동 포스팅 어댑터.

주의: 티스토리는 카카오계정 로그인 및 에디터 UI가 종종 개편된다.
아래 셀렉터는 작성 시점 기준 일반적인 구조를 가정한 '최선의 추정치'이며,
사이트가 바뀌면 깨질 수 있다. 그럴 때는:
  1) SiteAdapter(debug=True)로 실행해서 Playwright Inspector로 실제 셀렉터를 확인하고
  2) config.json 의 "selectors"."tistory" 에 덮어쓰기(override) 값을 넣어 고치면 된다.
   (직접 코드를 고쳐도 된다.)
"""
from __future__ import annotations

import re

from playwright.sync_api import Page

from config import load_config
from .base import PostContent, SiteAdapter

DEFAULT_SELECTORS = {
    "title_input": "#post-title-inp",
    # 에디터 상단 '첨부' 버튼 — 실제 클릭 대상은 role="button" aria-label="첨부"가 붙은
    # div이고, 안의 <button>은 role="presentation"(장식용)이라 진짜 핸들러가 아니다.
    # 페이지에 aria-label="첨부"인 요소가 여러 개(숨겨진 것 포함) 있어서 :visible로 제한한다.
    "attach_menu_button": "[aria-label='첨부']:visible",
    # 드롭다운 메뉴의 '사진' 항목. Tistory 쪽에서 고정으로 부여한 id라 안정적이다.
    "attach_image_menu_item": "#attach-image:visible",
    "image_toolbar_button": "button[title='사진']",
    "image_file_input": "input[type='file']",
    "publish_open_button": ":text-is('완료'):visible",
    # 발행 모달의 '공개' 라디오. 기본값이 '비공개'라 이걸 먼저 선택해야 공개로 올라간다.
    "publish_visibility_public": ":text-is('공개'):visible",
    # 공개 라디오를 선택해야 버튼 라벨이 '공개 발행'(공백 있음)으로 바뀐다.
    "publish_confirm_button": "button:has-text('발행'):visible",
    "category_select": "#category-btn",
}


class TistoryAdapter(SiteAdapter):
    site_id = "tistory"
    site_name = "티스토리"

    @property
    def login_url(self) -> str:
        return "https://www.tistory.com/auth/login"

    def _selectors(self) -> dict:
        cfg = load_config()
        overrides = cfg.get("selectors", {}).get("tistory", {})
        return {**DEFAULT_SELECTORS, **overrides}

    def _upload_single_image(self, page: Page, sel: dict, image_path) -> None:
        path = str(image_path)

        # 첨부 버튼 클릭 → 드롭다운 메뉴에서 '사진' 클릭 → OS 파일 선택창이 뜬다 (확인됨).
        try:
            with page.expect_file_chooser(timeout=5000) as fc_info:
                page.click(sel["attach_menu_button"])
                page.locator(sel["attach_image_menu_item"]).click(timeout=3000)
            fc_info.value.set_files(path)
            page.wait_for_timeout(1800)
            return
        except Exception:
            pass  # 아래 폴백 방식으로 재시도

        # 폴백: 숨겨진 <input type="file">을 Locator로 직접 찾아 파일을 지정한다.
        try:
            file_input = page.locator(sel["image_file_input"]).first
            file_input.wait_for(state="attached", timeout=5000)
            file_input.set_input_files(path)
            page.wait_for_timeout(1800)
            return
        except Exception as e:
            raise RuntimeError(
                f"이미지 업로드에 실패했습니다 ({e}). debug=True 로 재실행해서 첨부 버튼과 "
                f"파일 input의 실제 셀렉터를 확인한 뒤 config.json 의 "
                f"selectors.tistory.attach_menu_button / image_file_input 에 지정하세요."
            )

    # Tistory는 이미지를 업로드해도 <img> 태그가 아니라 자체 숏코드로 담는다:
    # [##_Image|kage@xxxx...|CDM|1.3|{"originWidth":200,...}_##]
    # 이 숏코드를 그대로 최종 본문에 넣어야 실제 이미지로 렌더링된다.
    _IMAGE_SHORTCODE_RE = re.compile(r"\[##_Image\|.*?_##\]", re.DOTALL)

    def _upload_images_and_get_tags(self, page: Page, sel: dict, image_paths: list) -> list[str]:
        """이미지를 하나씩 실제로 업로드하고, Tistory가 만들어준 이미지 숏코드를
        순서대로 반환한다. (자리표시자를 이걸로 바꿔치기하면 진짜 이미지가 들어간다)
        """
        img_tags: list[str] = []
        for image_path in image_paths:
            before = page.evaluate("() => window.tinymce.activeEditor.getContent()")
            self._upload_single_image(page, sel, image_path)
            after = page.evaluate("() => window.tinymce.activeEditor.getContent()")

            before_imgs = set(self._IMAGE_SHORTCODE_RE.findall(before))
            after_imgs = self._IMAGE_SHORTCODE_RE.findall(after)
            new_tag = next((t for t in after_imgs if t not in before_imgs), None)
            if new_tag is None:
                new_tag = after_imgs[-1] if after_imgs else ""
            img_tags.append(new_tag)
        return img_tags

    def _do_post(self, page: Page, content: PostContent) -> str:
        cfg = load_config()
        blog_name = cfg["tistory"]["blog_name"]
        if not blog_name or "여기에" in blog_name:
            raise RuntimeError("config.json 의 tistory.blog_name 을 먼저 설정하세요.")
        # 실수로 전체 URL("https://xxx.tistory.com")을 넣어도 서브도메인만 추출해서 사용
        blog_name = (
            blog_name.replace("https://", "").replace("http://", "").split(".")[0].strip("/")
        )
        category_name = cfg["tistory"].get("category_name", "")
        sel = self._selectors()

        page.goto(f"https://{blog_name}.tistory.com/manage/newpost/?type=post")
        page.wait_for_load_state("networkidle")

        # '이어서 작성하시겠습니까' 같은 임시저장 복구 팝업이 뜨면 새 글로 진행
        try:
            page.get_by_text("취소", exact=True).click(timeout=3000)
        except Exception:
            pass

        # 제목 입력
        page.fill(sel["title_input"], content.title)

        # 이미지를 하나씩 실제로 업로드해서 Tistory가 만들어준 진짜 <img> 태그를 받아온다.
        # (에디터가 비어있는 상태에서 업로드하므로 이 시점엔 이미지들이 순서대로 쌓인다 —
        # 최종 위치는 아래에서 body_html의 자리표시자를 이 태그로 바꿔치기해서 잡는다)
        real_img_tags = self._upload_images_and_get_tags(page, sel, content.image_paths)

        # 사용자가 에디터에서 꾸민 서식(HTML)에서 사진 자리표시자를 실제 <img> 태그로 교체.
        body_html = content.body
        for idx, tag in enumerate(real_img_tags):
            body_html = body_html.replace(f'<img src="__AUTOWRITE_IMAGE_{idx}__">', tag)

        # 본문 삽입: 이 에디터는 TinyMCE 기반이라 window.tinymce.activeEditor의
        # 표준 API로 직접 넣는 게 가장 안정적이다 (버튼 클릭으로 HTML 모드를 여는 방식은
        # 실제로 내부 상태만 바뀌고 화면이 전환되지 않아 쓸 수 없었다).
        # setContent()는 에디터 내용을 통째로 덮어쓰므로, 이 한 번의 호출로 이미지가
        # 원래 서식에서 있던 자리 그대로 최종 배치된다.
        try:
            page.evaluate(
                "(html) => window.tinymce.activeEditor.setContent(html)",
                body_html,
            )
        except Exception as e:
            raise RuntimeError(
                f"본문 입력 단계에서 실패했습니다 ({e}). "
                f"debug=True 로 재실행해 window.tinymce.activeEditor 가 존재하는지 확인하세요."
            )

        # 카테고리 지정 (선택)
        if category_name:
            try:
                page.click(sel["category_select"])
                page.get_by_text(category_name, exact=True).click(timeout=3000)
            except Exception:
                print(f"[{self.site_name}] 카테고리 '{category_name}' 선택 실패 — 기본 카테고리로 진행합니다.")

        # 발행 (기본값이 '비공개'라 '공개'를 먼저 선택해야 공개로 올라간다)
        page.click(sel["publish_open_button"])
        page.wait_for_timeout(500)
        page.click(sel["publish_visibility_public"])
        page.wait_for_timeout(300)
        page.click(sel["publish_confirm_button"])
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(1000)  # 발행 반영 대기

        # 발행해도 현재 탭은 글쓰기 페이지에 그대로 남아있어 page.url을 쓸 수 없다.
        # 글 목록에서 방금 올린 제목으로 실제 게시글 주소를 찾는다.
        page.goto(f"https://{blog_name}.tistory.com/manage/posts/")
        page.wait_for_load_state("networkidle")
        try:
            href = page.get_by_text(content.title, exact=False).first.get_attribute(
                "href", timeout=5000
            )
            if href:
                return href if href.startswith("http") else f"https://{blog_name}.tistory.com{href}"
        except Exception:
            pass
        return f"https://{blog_name}.tistory.com/manage/posts/"
