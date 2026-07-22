# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 프로젝트 개요

사용자가 직접 작성한 글(사진 + 텍스트)을 입력하면 선택한 사이트(티스토리, 디시인사이드)의
**본인 계정**으로 그대로 게시해주는 로컬 FastAPI 웹앱. 글쓰기 자체는 AI가 하지 않으며,
사용자가 입력한 내용을 Playwright로 브라우저를 조작해 그대로 업로드하는 역할만 한다.

## 실행 / 개발 명령어

```bash
# 설치
pip install -r requirements.txt
playwright install chromium

# 최초 1회: 사이트별 로그인(쿠키 세션 저장) — storage/sessions/*.json 에 저장됨
python scripts/login_tistory.py
python scripts/login_dcinside.py

# 앱 실행 (http://127.0.0.1:8000)
python autowrite.py
```

- `config.json`이 없으면 `autowrite.py`/`config.py`가 기본 템플릿을 자동 생성하고 채워달라는
  `RuntimeError`를 콘솔에 출력만 하고 서버는 계속 뜬다 (`autowrite.py`의 try/except 참고).
- 이 저장소에는 별도의 lint/test 명령이 구성되어 있지 않다 (테스트 스위트 없음).

## 아키텍처

**설정(`config.py` / `config.json`)**: 블로그 이름, 갤러리 ID 등 사이트별 설정을 담당.
비밀번호는 절대 저장하지 않으며, `config.json`의 `"selectors"` 키로 사이트별 CSS 셀렉터를
코드 수정 없이 덮어쓸 수 있다 (사이트 UI 개편으로 자동화가 깨졌을 때의 1차 대응 수단).
`config.json`은 `.gitignore`에 포함되어 커밋되지 않는다.

**어댑터 패턴(`sites/`)**: `sites/base.py`의 `SiteAdapter` 추상 클래스가 로그인 세션 저장/재사용,
게시 시 에러 스크린샷 저장(`storage/error_screenshots/`) 등 공통 로직을 담당하고,
각 사이트(`sites/tistory.py`, `sites/dcinside.py`)는 `login_url` 프로퍼티와 `_do_post()`
메서드만 구현하면 된다. 새 사이트를 추가하려면 이 인터페이스를 상속한 어댑터를 만들고
`sites/__init__.py`의 `SITE_ADAPTERS` 딕셔너리에 등록하기만 하면 된다.

- 로그인은 Playwright의 `context.storage_state()`로 쿠키 세션만 저장하고 재사용한다
  (비밀번호 미저장). 세션 파일: `storage/sessions/{site_id}.json`.
- 게시(`post()`)는 기본적으로 `headless=False`로 실제 브라우저 창을 띄운다 — 디시인사이드 등
  일부 사이트는 게시 시 캡차가 뜰 수 있고, 이 프로그램은 캡차를 자동으로 우회하지 않는다
  (감지되면 사람이 직접 풀도록 `input()`으로 대기).
- 각 어댑터 생성자에 `debug=True`를 넘기면 `page.pause()`로 Playwright Inspector가 열려
  실제 셀렉터를 단계별로 확인할 수 있다. 셀렉터가 깨졌을 때의 표준 디버깅 절차.
- 에디터별로 본문 삽입 방식이 다르다: 티스토리는 TinyMCE(`window.tinymce.activeEditor.setContent()`),
  디시인사이드는 Summernote(`$('#memo').summernote('code', html)`). 둘 다 버튼 클릭으로
  HTML 모드를 여는 방식이 아니라 JS API로 직접 주입하는 방식이 안정적임이 확인되어 있다.
- 이미지 처리 흐름: 웹 UI 에디터(Summernote, `templates/index.html`)가 사진을 base64 `<img>`로
  전송 → `autowrite.py`의 `_extract_embedded_images()`가 이를 실제 파일로 빼내고
  `__AUTOWRITE_IMAGE_{n}__` 자리표시자로 치환 → 각 어댑터가 이미지를 실제로 하나씩 업로드해서
  사이트가 만들어준 진짜 태그(티스토리는 `[##_Image|...|_##]` 숏코드, 디시인사이드는 실제
  `<img src="https://dcimg...">`)를 받아온 뒤 → 자리표시자를 순서대로 치환해 서식과 사진
  위치를 그대로 유지한 최종 HTML을 만든다.

**일일 게시 제한(`postlog.py`)**: 사이트당 하루 1건 게시 제한을 `storage/post_log.json`에
기록해 강제한다. `config.json`의 `"daily_limit"`을 `"N"`으로 두면 이 제한을 끌 수 있다.

**웹 레이어(`autowrite.py`)**: FastAPI 앱. `GET /`에서 사이트별 상태(세션 유무, 오늘 게시
가능 여부)를 보여주고, `POST /post`에서 선택된 사이트마다 세션 확인 → 일일 제한 확인 →
`adapter.post()` 호출 순으로 처리하며 사이트별 성공/실패 메시지를 모아 다시 렌더링한다.

## 보안 관련 주의사항

- `storage/`(세션 쿠키, 업로드 이미지, 게시 로그, 에러 스크린샷)와 `config.json`(블로그 이름,
  갤러리 ID 등 개인 설정)은 `.gitignore`에 포함되어 있다 — 커밋하거나 외부에 공유하지 않는다.
- 셀렉터/로직을 수정할 때도 비밀번호를 코드나 설정 파일에 저장하는 방식은 도입하지 않는다
  (로그인은 항상 브라우저 쿠키 세션 재사용 방식 유지).
