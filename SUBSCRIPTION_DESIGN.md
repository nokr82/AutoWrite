# AutoWrite — 구독(라이선스) 인증 아키텍처 설계

> 이 문서는 설계만 정리한 것이며, 아직 구현되지 않았다. 실제 구현 여부/시점은 별도로 결정한다.

## Context

지금 이 앱은 순수 로컬 도구다: 사용자가 직접 쓴 글을 자기 계정(티스토리/디시인사이드/네이버 카페)에
Playwright로 대신 올려줄 뿐이고, 각 사이트 로그인 세션(쿠키)은 `storage/sessions/`에만 저장되며
서버나 제3자 신뢰 주체가 전혀 없다.

이 도구를 유료 구독형 제품으로 발전시키는 걸 검토하면서 다음을 전제로 두었다:

- **사이트 로그인 세션은 절대 건드리지 않는다** — 지금처럼 로컬에만 남겨서, 네이버/티스토리/
  디시인사이드 계정 정보를 우리가 떠안는 리스크(SaaS로 만들 경우 가장 큰 문제로 지목됐던 부분)를
  원천 차단한다.
- 대신 "이 사람이 이번 달 결제한 구독자인가"만 판별하는 **별도의, 훨씬 가벼운 자체 로그인**을
  새로 추가한다.
- 완벽한 크랙 방지(DRM)는 목표가 아니다 — 1인 개발자 규모 제품에서 일반적으로 감수하는 수준의
  우회 가능성은 감수한다.

이 문서는 이 저장소(exe/클라이언트)가 무엇을 새로 갖고, 별도로 만들어야 할 백엔드(구독/결제 서버,
이 저장소 밖의 별도 프로젝트)와는 어떤 최소 계약으로 통신하는지를 정의한다.

## 역할 분리

**이 저장소(exe)가 갖는 것:**
- 불투명한 구독 토큰, 로컬에서 한 번 생성한 device id, 마지막 검증 시각 — 이 세 가지만 로컬에 저장.
- 이메일/비밀번호를 입력받아 백엔드로 그대로 전달만 하는 로그인 화면(비밀번호 자체는 저장 안 함).
- 매번 네트워크를 타지 않고도 "지금 게시해도 되는가"를 판단하는 오프라인 유예 로직.
- 앱 시작 시 백그라운드로 한 번 재검증 시도(실패해도 앱 구동은 막지 않음).

**별도의 새 백엔드(이번 설계 범위 밖)가 갖는 것:**
- 회원 DB, 비밀번호 해시, 토큰 발급.
- Stripe 등 결제 연동과 "지금 유효 구독자인가"의 최종 판단.
- 구독당 기기 수 제한.
- 아래 백엔드 최소 계약에 정리한 API 3개.

클라이언트는 자기 자신의 불투명 토큰 외에는 아무것도 커스터디하지 않는다 — 지금 이미 로컬에 저장 중인
Playwright `storage_state` 쿠키와 신뢰 등급이 같다.

## 클라이언트 설계

### 새 모듈 `license.py` — `postlog.py`/`drafts.py`와 동일한 패턴

`storage/license.json`에 저장(이미 `.gitignore`의 `storage/` 규칙에 포함되므로 별도 수정 불필요).
`config.json`/`DEFAULT_CONFIG`에는 넣지 않는다 — 사용자가 직접 편집하는 설정이 아니고,
`config.json`을 지원 요청 시 그대로 공유하는 경우가 있어 토큰이 섞이는 걸 피한다.

```json
{
  "device_id": "uuid4 hex, 최초 1회 생성 후 영구 보존",
  "email": "표시/재로그인 편의용",
  "token": "서버가 발급한 불투명 토큰",
  "plan": "표시용 플랜 이름",
  "expires_at": "구독 만료일 (서버가 알려줌)",
  "last_verified_at": "마지막으로 서버 검증에 성공한 시각"
}
```

`license.py`가 제공할 함수(플랫 딕셔너리 load/save 스타일, `postlog.py`와 동일):
- `get_device_id() -> str` — 최초 호출 시 `uuid.uuid4().hex`를 만들어 영구 저장.
- `login(email, password) -> None` — 백엔드 `/v1/auth/login` 호출, 성공 시 토큰/만료일/검증시각 저장.
  인증 실패와 네트워크 실패를 구분되는 예외로 던진다.
- `verify(force=False) -> bool` — 백엔드 `/v1/auth/verify` 호출. 유예기간 안이고 `force`가 아니면
  네트워크를 아예 타지 않는다.
- `is_active() -> bool` — **순수 로컬 판단, 네트워크 호출 없음.** `/post`를 막을지 여기서 결정.
- `refresh_on_startup() -> None` — `verify()`를 시도하되 모든 예외를 삼킨다
  (`_ensure_chromium_installed`처럼 "실패해도 앱은 계속 뜬다" 원칙).
- `logout() -> None` — 로컬 상태 파일 삭제.

### 오프라인 유예 메커니즘 (하나로 확정)

불투명 토큰 + `last_verified_at` 캐시 + 유예기간, 시작 시 재검증:

- 로그인/검증 시 서버가 `expires_at`(구독 만료일)을 알려준다.
- `is_active()`는 다음이 모두 참일 때만 true: 토큰 존재 AND `now < expires_at` AND
  `(now - last_verified_at) < GRACE_PERIOD_DAYS`(**7일 권장**).
- 앱 시작 시 데몬 스레드로 `refresh_on_startup()`을 호출해 인터넷이 되면 조용히 최신 상태로 갱신한다.
  안 되면 캐시된 값이 유예기간 끝을 향해 그냥 늙어갈 뿐 — 유예기간이 끝나기 전까진 계속 게시 가능하고,
  끝나면 한 번은 온라인 상태에서 재검증해야 한다.
- 서버가 "네트워크 오류"가 아니라 명시적으로 "구독 해지/만료"라고 응답하면, 유예기간을 기다리지 않고
  즉시 무효화한다 — 유예는 "연결이 잠깐 끊긴 상황"을 위한 것이지 "해지된 구독"을 봐주기 위한 게 아니다.

**비대칭 서명 JWT로 완전 오프라인 검증하는 방식 대신 이걸 고른 이유:** 둘 다 크랙 난이도는 비슷하고
(이미 감수하기로 한 부분), 키 관리/로테이션의 복잡도를 추가로 얹을 실익이 없다. 몇 주씩 연속 오프라인
사용을 지원해야 하는 제품이 아니라면 이 캐시-타임스탬프 방식으로 충분하다.

### 게이팅 지점

**`/post`만 막는다.** `/settings`, `/drafts`, `/login/{site_id}`는 그대로 열어둔다 — 세션 설정이나
임시 저장 글쓰기는 막을 이유가 없고(오히려 무료 체험 유도 효과), 실제 가치가 전달되는 지점 한 곳만
막는 게 명확하다. 나중에 더 강하게 막고 싶으면(`/login/{site_id}`도 막기) 쉽게 넓힐 수 있다.

`autowrite.py`의 기존 `/post` 핸들러 맨 앞, "사이트를 하나 이상 선택하세요" 체크와 같은 자리에:

```python
if not license.is_active():
    messages.append({"level": "error", "text": "구독이 필요합니다. <a href='/account'>구독 로그인</a> 후 다시 시도하세요."})
    return templates.TemplateResponse(request, "index.html", {"sites": _site_status(), "messages": messages, "drafts": list_drafts()})
```

### 새 라우트/페이지: `/account` (신규 페이지, `/settings` 확장 아님)

`/settings`는 "사이트 설정"(블로그 이름, 갤러리 ID) 담당이고, 구독자 신원은 별개 관심사라 독립적으로
링크 가능해야 한다(게이팅 에러 메시지에서, 그리고 `/` 상단 상태 표시줄에서).

- `GET /account` — `templates/account.html` 렌더링: 현재 상태(활성/만료/없음), 만료일, 이메일 표시 +
  비활성이면 로그인 폼.
- `POST /account/login` (Form: `email`, `password`) — `license.login(...)` 호출 후 재렌더링.
- `POST /account/logout` — `license.logout()` 호출 후 재렌더링.

`templates/index.html` 상단에도 한 줄짜리 구독 상태 표시(예: "구독 활성 (2026-08-23까지)" 또는
"구독 필요 — 로그인", `/account`로 링크)를 추가한다.

### 시작 훅

`autowrite.py`의 `if __name__ == "__main__":` 블록에서 기존 `_open_browser_when_ready` 타이머 옆에
`license.refresh_on_startup()`을 데몬 스레드로 추가 — 오프라인이어도 앱 구동 자체는 막지 않는다.

## 기기 바인딩 (가볍게, 완벽하지 않게)

- 클라이언트가 `uuid.uuid4().hex`를 한 번 생성해 `storage/license.json`에 저장하고, 모든
  `/v1/auth/login` / `/v1/auth/verify` 호출에 실어 보낸다.
- 서버(범위 밖)가 구독당 활성 device id 수를 제한(예: 2대)하고, 초과 시 `409 device_limit_exceeded`
  같은 별도 에러를 준다 — 클라이언트는 "이미 다른 기기에서 사용 중입니다"로 표시.
- 하드웨어 지문(MAC/디스크 시리얼) 방식은 쓰지 않는다 — 일반 사용자의 정상적인 하드웨어/OS 변경에도
  오탐이 나서, 막으려는 피해보다 UX 피해가 커진다(DRM 수준 강제는 이미 배제하기로 함).
- 명시적 트레이드오프: `storage/license.json`을 지우면 새 device id가 발급되어 기기 수 제한을
  간단히 우회할 수 있다. DRM을 하지 않기로 한 이상, 이건 "가벼운 억제"이지 "강제 제한"이 아니라는
  걸 받아들인다.

## 새 의존성: HTTP 클라이언트

**`requests`를 추가한다** (httpx, 표준 라이브러리 `urllib.request` 대신).

- `urllib.request`는 의존성이 안 늘지만, JSON POST + 타임아웃 + 에러 처리를 직접 구현해야 해서
  이득이 없다.
- `httpx`는 비동기 우선이라 `httpcore`/`h11`/`anyio`/`sniffio`까지 딸려온다 — 이 앱은 로그인/검증,
  가끔 호출되는 동기 호출 두 개뿐이라 얻는 게 없다.
- `requests`는 PyInstaller 번들 사례가 가장 많고 `pyinstaller-hooks-contrib`가 까다로운 부분
  (certifi의 `cacert.pem`)을 대체로 알아서 처리해준다 — 지금 코드베이스의 "단순하게" 기조와도 맞다.

`requirements.txt`에 `requests` 추가(버전 고정 없이, 기존 스타일 그대로). `build.spec` 변경은
당장 필요 없을 것으로 예상되지만, 패키징 후 HTTPS 호출에서 SSL 인증서 오류가 나면
`collect_all("requests")`를 `uvicorn`/`playwright`와 같은 루프에 추가하는 걸 폴백으로 남겨둔다.

## 파일 단위 계획

**신규 파일:**
- `license.py` — `postlog.py`/`drafts.py`와 동일한 스타일의 플랫 JSON 저장 모듈. `storage/license.json`
  소유, device id 생성, login/verify/logout, 오프라인 유예 판단(`is_active()`)까지 담당. 내부에
  `requests` 기반 헬퍼 하나(`_api_post` 등)로 "네트워크 오류(유예 대상)"와 "서버가 명시적으로 거부
  (즉시 무효화)"를 구분한다.
- `templates/account.html` — `settings.html`과 같은 시각 시스템(CSS 변수/fieldset/flash 메시지 패턴)
  재사용. 로그인 폼 + 상태 표시 + 로그아웃 버튼.

**기존 파일 수정:**
- `requirements.txt` — `requests` 추가.
- `config.py` — `POST_LOG_PATH`/`DRAFTS_PATH` 옆에 `LICENSE_PATH = BASE_DIR / "storage" / "license.json"`
  상수 추가. `DEFAULT_CONFIG`에는 키를 추가하지 않는다(사용자가 편집하는 설정이 아니므로). 백엔드
  base URL은 `settings.html`에 노출하지 않고 `license.py` 상단 상수로 둔다(1인 제품 규모에서는
  서버 주소를 사용자가 설정할 이유가 없음).
- `autowrite.py` — `license` import, `GET/POST /account` + `POST /account/logout` 라우트 추가
  (기존 `/settings` GET/POST 쌍과 같은 모양), 기존 `/post` 핸들러 맨 앞에 `is_active()` 게이트 추가,
  `__main__` 블록에 `refresh_on_startup()` 데몬 스레드 추가.
- `templates/index.html` — 상단에 구독 상태 한 줄 추가, `/account`로 링크.

**변경 없음(명시적으로):** `.gitignore`(이미 `storage/`가 커버), `postlog.py`, `drafts.py`,
`sites/*`(게시 로직 자체는 건드리지 않음 — 구독 확인은 어댑터 실행 전 사전 체크일 뿐).

## 백엔드 최소 계약 (이 저장소 밖, 이번 설계 범위 밖)

회원 DB, 비밀번호 해시, Stripe 등 결제 연동은 별도 프로젝트/배포다. 클라이언트 설계를 구체화하는 데
필요한 최소 API 3개만 명시한다:

- `POST /v1/auth/login` `{email, password, device_id}` → 성공 시 `{token, expires_at, plan}`.
  실패: `401`(인증 실패), `402`/`403`(구독 만료/비활성), `409`(`device_limit_exceeded`).
- `POST /v1/auth/verify` `{token, device_id}` → `{valid, expires_at, plan}` — 비밀번호 재전송 없이
  주기적 재검증.
- `POST /v1/auth/logout` `{token, device_id}` (선택) — 서버 쪽 기기 슬롯 반납.

가입, 비밀번호 재설정, Stripe 웹훅, 관리자 대시보드 등은 전부 백엔드 자체 관심사이며 여기서
더 다루지 않는다.

## 검증 방법 (구현 단계에서)

- `license.py` 단위 테스트 없이도 수동 확인 가능: 가짜 백엔드(로컬 Flask/FastAPI 목업 서버 또는
  `unittest.mock.patch`로 `requests.post` 모킹)로 `login()`→`is_active()`→`verify()` 흐름을 확인.
- `is_active()`의 유예기간 경계값(만료 직전/직후, `last_verified_at` 유예기간 안/밖)은 시각을 주입해
  단위 테스트로 검증.
- `/account` 페이지는 Playwright로 직접 로그인 폼을 채워 제출해보고, `/post`가 비구독 상태에서
  실제로 막히는지, `/account/login` 성공 후 열리는지 스크린샷으로 확인.
- 패키징 후 `requests`가 exe 안에서 실제 HTTPS 호출에 성공하는지(SSL 인증서 오류 없는지) 반드시
  한 번 실제 빌드로 확인 — 실패 시 `build.spec`에 `collect_all("requests")` 추가.
