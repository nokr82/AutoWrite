# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 프로젝트 개요

사용자가 직접 작성한 글(사진 + 텍스트)을 입력하면 선택한 사이트(티스토리, 디시인사이드,
네이버 카페)의 **본인 계정**으로 그대로 게시해주는 로컬 FastAPI 웹앱. 글쓰기 자체는 AI가 하지 않으며,
사용자가 입력한 내용을 Playwright로 브라우저를 조작해 그대로 업로드하는 역할만 한다.
일반 사용자에게 배포하기 위해 PyInstaller로 단일 exe(Windows)로도 패키징할 수 있다.

## 실행 / 개발 명령어

```bash
# 설치
pip install -r requirements.txt
playwright install chromium

# 앱 실행 (http://127.0.0.1:8000) — config.json 없으면 최초 실행 시 템플릿 자동 생성
python autowrite.py

# 로그인(터미널 방식) — 웹 UI의 "로그인하기" 버튼으로도 가능(아래 아키텍처 참고)
python scripts/login_tistory.py
python scripts/login_dcinside.py
python scripts/login_naver_cafe.py

# exe로 빌드 (dist/AutoWrite.exe 하나만 생성됨, Windows 대상)
pip install pyinstaller
pyinstaller build.spec
```

- `config.json`이 없으면 `config.py`의 `load_config()`가 기본 템플릿을 생성하며 `RuntimeError`를
  던진다. `autowrite.py` 모듈 최상단 import 시점에 이걸 try/except로 잡아 콘솔에만 출력하고
  서버는 계속 띄운다 — 설정은 웹 UI의 `/settings` 페이지에서 채우면 된다(직접 JSON 편집 불필요).
- 이 저장소에는 별도의 lint/test 명령이 구성되어 있지 않다 (테스트 스위트 없음). 변경 검증은
  보통 `python -m py_compile <file>`과 Jinja2 템플릿을 직접 렌더링해보는 식으로 했다
  (실제 Playwright 브라우저/로그인은 자동화 테스트로 흉내내기 어려움).

## 아키텍처

**설정(`config.py` / `config.json`)**: 블로그 이름, 갤러리 ID 등 사이트별 설정을 담당.
비밀번호는 절대 저장하지 않으며, `config.json`의 `"selectors"` 키로 사이트별 CSS 셀렉터를
코드 수정 없이 덮어쓸 수 있다 (사이트 UI 개편으로 자동화가 깨졌을 때의 1차 대응 수단).
`config.json`은 `.gitignore`에 포함되어 커밋되지 않는다. `BASE_DIR`은 `sys.frozen` 여부로
분기한다 — exe(onefile)로 실행 중이면 `sys.executable`의 부모 폴더(exe 파일이 실제로 있는 곳)를,
아니면 이 파일의 부모 폴더를 쓴다. onefile은 `__file__`이 실행마다 사라지는 임시 폴더를
가리키므로, 이 분기가 없으면 exe 재시작 때마다 설정이 날아간다. `load_config()`는 기존
`config.json`에 없는 최상위 키(예: 나중에 추가된 `naver_cafe`)를 `DEFAULT_CONFIG` 값으로
채워 자동 저장한다 — 새 사이트가 추가돼도 이전에 생성된 `config.json`을 쓰는 사용자가
설정 화면(`cfg.naver_cafe.club_id` 등)에서 에러 없이 계속 쓸 수 있게 하기 위함.

**어댑터 패턴(`sites/`)**: `sites/base.py`의 `SiteAdapter` 추상 클래스가 로그인 세션 저장/재사용,
게시 시 에러 스크린샷 저장(`storage/error_screenshots/`) 등 공통 로직을 담당하고,
각 사이트(`sites/tistory.py`, `sites/dcinside.py`, `sites/naver_cafe.py`)는 `login_url`
프로퍼티와 `_do_post()` 메서드만 구현하면 된다. 새 사이트를 추가하려면 이 인터페이스를
상속한 어댑터를 만들고 `sites/__init__.py`의 `SITE_ADAPTERS` 딕셔너리에 등록하기만 하면
된다 — 등록만 하면 `templates/index.html`의 사이트 목록, 로그인 버튼, `/post` 처리까지
전부 자동으로 반영된다(`autowrite.py`가 `SITE_ADAPTERS`를 순회하는 구조라 사이트별 분기가
따로 없음).

- 로그인은 Playwright의 `context.storage_state()`로 쿠키 세션만 저장하고 재사용한다
  (비밀번호 미저장). 세션 파일: `storage/sessions/{site_id}.json`.
- 게시(`post()`)는 기본적으로 `headless=False`로 실제 브라우저 창을 띄운다 — 디시인사이드 등
  일부 사이트는 게시 시 캡차가 뜰 수 있고, 이 프로그램은 캡차를 자동으로 우회하지 않는다
  (감지되면 사람이 직접 풀도록 대기).
- 각 어댑터 생성자에 `debug=True`를 넘기면 `page.pause()`로 Playwright Inspector가 열려
  실제 셀렉터를 단계별로 확인할 수 있다. 셀렉터가 깨졌을 때의 표준 디버깅 절차.
- 에디터별로 본문 삽입 방식이 다르다: 티스토리는 TinyMCE(`window.tinymce.activeEditor.setContent()`),
  디시인사이드는 Summernote(`$('#memo').summernote('code', html)`) — 둘 다 완성된 HTML을
  한 번에 통째로 주입하는 방식이 안정적임이 확인되어 있다. **네이버 카페(SmartEditor ONE)는
  이 방식이 통하지 않는다** — 제목은 contenteditable이 아니라 평범한 `textarea.textarea_input`
  이고, 본문은 문단/이미지가 각각 독립된 "컴포넌트"로 관리되는 구조라 클립보드 `paste`
  이벤트를 합성해서 던져도 무시된다(실측 결과 DOM에 전혀 반영 안 됨). 대신 실제 사용자처럼
  `page.keyboard.type()`으로 타이핑하고 `Enter`/`Control+B`/`Control+I`로 문단·서식을
  반영하는 방식만 통한다 — `sites/naver_cafe.py`의 `_BodyOpsParser`(`html.parser.HTMLParser`
  기반)가 본문 HTML을 (텍스트 타이핑 / 문단 나누기 / 이미지 삽입) 순서열로 변환하고
  `_type_body()`가 이를 그대로 재생한다. 등록 버튼도 `<button>`이 아니라
  `<a role="button">`이라 `page.get_by_role("button", name="등록", exact=True)`처럼
  접근성 role 기반으로 찾아야 한다("임시등록" 버튼과 이름이 겹치므로 `exact=True` 필수).
- 이미지 처리 흐름은 사이트마다 다르다. 티스토리/디시인사이드는 자리표시자
  (`__AUTOWRITE_IMAGE_{n}__`) 방식 — 이미지를 먼저 다 업로드해서 사이트가 만들어준 진짜
  태그(티스토리는 `[##_Image|...|_##]` 숏코드, 디시인사이드는 실제 `<img src="...">`,
  업로드 전/후 내용을 비교해 새로 생긴 태그를 찾음)를 받아온 뒤, 한 번에 완성된 HTML을
  주입할 때 자리표시자를 그 태그로 치환한다. 네이버 카페는 애초에 한 번에 주입하는 게
  불가능하므로 자리표시자 방식을 안 쓴다 — `_BodyOpsParser`가 본문을 순서대로 훑다가
  이미지 자리(`<img src="__AUTOWRITE_IMAGE_n__">`)를 만나면 그 즉시 커서 위치에 업로드한다.
  실측 결과 이미지 업로드가 끝나면 에디터가 알아서 새 빈 문단을 만들고 포커스도 그리로
  옮겨줘서, 별도 클릭 없이 바로 다음 텍스트를 이어 타이핑해도 순서가 그대로 유지된다.

**터미널 없는 로그인 플로우**: `SiteAdapter.login_manually(wait_for_user=None)`은 로그인
브라우저를 띄운 뒤 로그인 완료 신호를 기다린다. 인자를 안 주면(터미널에서
`scripts/login_*.py`를 직접 실행하는 경우) 기존처럼 `input()`으로 콘솔 Enter를 기다린다.
웹 UI 경로에서는 `autowrite.py`가 `threading.Event` 기반 콜백을 넘긴다:
`POST /login/{site_id}`가 브라우저를 띄우고 이 요청 스레드 안에서 이벤트를 기다리며 대기하고,
사용자가 웹 페이지의 "로그인 완료" 버튼을 누르면 별도 요청 `POST /login/{site_id}/confirm`이
같은 이벤트를 `set()`해서 대기 중인 스레드를 깨운다(5분 타임아웃, `_pending_logins` 딕셔너리로
사이트별 중복 로그인 시도 방지). Playwright sync API는 생성한 스레드에서만 조작 가능하므로,
브라우저 열기~로그인 완료~세션 저장~브라우저 닫기가 전부 하나의 요청 스레드 안에서
끝나야 한다는 점이 이 설계의 핵심 제약이다 — 두 요청에 걸쳐 있는 건 순수 Python
`threading.Event`뿐이고 Playwright 객체는 절대 스레드 경계를 넘지 않는다.

**일일 게시 제한(`postlog.py`)**: 사이트당 하루 1건 게시 제한을 `storage/post_log.json`에
기록해 강제한다. `config.json`의 `"daily_limit"`을 `"N"`으로 두면 이 제한을 끌 수 있다.

**웹 레이어(`autowrite.py`)**: FastAPI 앱.
- `GET /`: 사이트별 상태(세션 유무, 오늘 게시 가능 여부) 표시. 세션 없는 사이트는 체크박스
  대신 "로그인하기" 버튼이 나온다.
- `POST /post`: 선택된 사이트마다 세션 확인 → 일일 제한 확인 → `adapter.post()` 호출 순으로
  처리하며 사이트별 성공/실패 메시지를 모아 다시 렌더링한다.
- `POST /login/{site_id}`, `POST /login/{site_id}/confirm`: 위 "터미널 없는 로그인 플로우" 참고.
- `GET/POST /settings`: `config.json`을 웹 폼으로 읽고 쓴다(블로그 이름/카테고리/갤러리 ID·종류/
  네이버 카페 club_id·menu_id/일일 제한). `selectors` 같은 고급 설정은 이 화면에 노출하지
  않고 그대로 보존한다.
- `_resource_path()`: `templates/`처럼 읽기 전용으로 번들된 리소스의 경로를 구한다. exe로
  실행 중이면 PyInstaller가 풀어놓은 `sys._MEIPASS`(실행마다 새로 생기는 임시 폴더) 기준,
  아니면 이 파일 기준. `config.BASE_DIR`(영속 데이터용, exe 폴더 기준)과는 용도가 다르므로
  구분해서 써야 한다.
- `uvicorn.run(app, ...)`으로 앱 객체를 직접 넘긴다(문자열 `"autowrite:app"` 아님) — exe
  안에는 `autowrite`라는 이름으로 다시 import할 파일이 실제로 없어서 문자열 방식은 깨진다.
- 시작 시 `_ensure_chromium_installed()`가 Chromium 설치 여부를 확인하고, 이미 설치돼 있어도
  `playwright install chromium`을 매번 호출한다(설치돼 있으면 몇 초 안에 그냥 넘어가는 멱등
  명령이라 부담 없음 — exe 프로즌 환경에서 자체 존재 확인만으로는 오탐 가능성이 있어서 실제
  설치 여부 판단은 CLI에 위임). 이어서 `_open_browser_when_ready()`가 1.5초 뒤 기본 브라우저를
  자동으로 연다.
- Windows에서는 모듈 최상단에서 콘솔 코드페이지와 stdout/stderr를 UTF-8로 강제 설정한다
  (`SetConsoleOutputCP(65001)` + `sys.stdout.reconfigure(...)`) — 안 하면 한국어 Windows의
  기본 cp949 코드페이지 때문에 exe 콘솔에 한글 안내 메시지가 깨져 보인다.

**exe 패키징(`build.spec`)**: `pyinstaller build.spec`으로 `dist/AutoWrite.exe`(onefile) 생성.
`collect_all("uvicorn")`, `collect_all("playwright")`로 동적 import되는 서브모듈과 playwright의
드라이버(브라우저 원격 제어용 node 실행파일 + cli.js, `playwright/driver/` 아래)를 통째로
번들에 포함한다 — 이게 없으면 exe 안에서 Playwright가 브라우저를 못 띄운다. Chromium 브라우저
본체는 여기 포함되지 않고(용량 문제) 최초 실행 시 사용자 PC에 별도로 내려받는다(위
`_ensure_chromium_installed()` 참고). `templates/`는 `datas`로 추가해야 번들에 포함된다.

## 보안 관련 주의사항

- `storage/`(세션 쿠키, 업로드 이미지, 게시 로그, 에러 스크린샷)와 `config.json`(블로그 이름,
  갤러리 ID 등 개인 설정)은 `.gitignore`에 포함되어 있다 — 커밋하거나 외부에 공유하지 않는다.
- 셀렉터/로직을 수정할 때도 비밀번호를 코드나 설정 파일에 저장하는 방식은 도입하지 않는다
  (로그인은 항상 브라우저 쿠키 세션 재사용 방식 유지).
- exe는 코드 서명이 되어 있지 않다 — Windows Defender/SmartScreen 경고가 뜰 수 있음을
  배포 시 사용자에게 안내해야 한다.
