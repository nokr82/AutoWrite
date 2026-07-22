# 자동 포스팅 프로그램

사용자가 직접 작성한 글(사진 + 텍스트)을 입력하면, 선택한 사이트의 **본인 계정**으로
그대로 게시해주는 로컬 도구입니다. 글은 AI가 쓰지 않습니다 — 입력한 내용을 그대로 올릴 뿐입니다.

- 대상 사이트: 티스토리, 디시인사이드 (설계상 다른 사이트도 `sites/` 아래에 어댑터만 추가하면 확장 가능)
- 계정: 사이트당 본인 계정 1개, 로그인은 쿠키 세션 저장 후 재사용 (비밀번호는 저장하지 않음)
- 제한: 사이트당 하루 1건만 게시 가능 (자동 강제)

## 1. 설치

```bash
pip install -r requirements.txt
playwright install chromium
```

## 2. 설정

처음 한 번 아래 명령을 실행하면 `config.json` 템플릿이 자동 생성됩니다.

```bash
python autowrite.py
```

생성된 `config.json`을 열어 채워주세요.

```json
{
  "tistory": { "blog_name": "myblog", "category_name": "" },
  "dcinside": { "gallery_id": "programming", "gallery_type": "major" }
}
```

- `tistory.blog_name`: `https://{blog_name}.tistory.com` 의 그 이름
- `dcinside.gallery_id`: 갤러리 주소의 `id` 파라미터. 마이너 갤러리면 `gallery_type`을 `"minor"`로.

## 3. 최초 로그인 (사이트당 1회)

브라우저 창이 뜨면 직접 로그인하고, 터미널로 돌아와 Enter를 누르면 세션(쿠키)이 저장됩니다.

```bash
python scripts/login_tistory.py
python scripts/login_dcinside.py
```

세션은 `storage/sessions/*.json`에 저장됩니다. 로그아웃되거나 만료되면 다시 실행하세요.

## 4. 실행

```bash
python autowrite.py
```

브라우저에서 http://127.0.0.1:8000 접속 → 제목/본문/사진 입력 → 올릴 사이트 선택 → 게시.

게시 시 브라우저 창이 자동으로 뜹니다(headless 아님). 디시인사이드는 등록 과정에서
자동입력 방지(캡차)가 뜰 수 있는데, 이 프로그램은 캡차를 우회하지 않습니다 —
뜨면 그 창에서 직접 풀고 터미널에서 Enter를 누르면 이어서 진행됩니다.

## 5. 사이트 UI가 바뀌어서 자동화가 깨졌을 때

`sites/tistory.py`, `sites/dcinside.py` 상단의 `DEFAULT_SELECTORS`가 실제 사이트 구조와
어긋나면 해당 단계에서 에러가 나고 `storage/error_screenshots/`에 스크린샷이 저장됩니다.

고치는 방법:
1. 어댑터 생성 시 `debug=True`로 넘기면 Playwright Inspector가 열려 실제 셀렉터를 확인하며 단계별로 진행할 수 있습니다.
2. 확인한 셀렉터를 `config.json`의 `"selectors"` 안에 사이트별로 덮어써 넣으면 코드 수정 없이 고칠 수 있습니다.

```json
{
  "selectors": {
    "tistory": { "title_input": "#post-title-inp" }
  }
}
```

## 6. 예약 실행 (다음 단계, 아직 미구현)

하루 1건이므로 Windows 작업 스케줄러로 특정 시각에 자동 게시하도록 확장할 수 있습니다.
다만 "AI가 글을 쓰지 않는다"는 원칙상, 예약 실행을 하려면 미리 작성해둔 글(제목/본문/사진 경로)을
어딘가에 큐로 저장해두는 방식이 필요합니다 — 현재는 웹 UI에서 직접 입력 후 즉시 게시하는
흐름만 구현되어 있습니다. 필요하면 "예약 게시함(대기 중인 글 목록)" 기능을 추가로 설계해드릴 수 있습니다.

## 폴더 구조

```
autowrite.py          FastAPI 앱 진입점
config.py / config.json   사이트별 설정
postlog.py             하루 1건 제한 기록
sites/
  base.py              공통 어댑터 인터페이스 (로그인 세션, 에러 스크린샷 등)
  tistory.py            티스토리 어댑터
  dcinside.py            디시인사이드 어댑터
scripts/
  login_tistory.py       최초 로그인용
  login_dcinside.py       최초 로그인용
templates/index.html     웹 UI
storage/
  sessions/               사이트별 로그인 세션(쿠키) 저장
  uploads/                업로드된 이미지 임시 저장
  post_log.json            하루 1건 제한 기록
  error_screenshots/       자동화 실패 시 디버깅용 스크린샷
```

## 보안 메모

- 사이트 비밀번호는 이 프로그램 어디에도 저장되지 않습니다. 로그인은 브라우저 쿠키 세션만 재사용합니다.
- `storage/sessions/*.json`은 로그인 상태를 그대로 담고 있어 유출 시 계정이 탈취될 수 있으니
  git 등에 커밋하거나 외부에 공유하지 마세요.
