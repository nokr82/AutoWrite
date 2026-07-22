# -*- mode: python ; coding: utf-8 -*-
# exe 빌드용 PyInstaller 스펙 파일.
# 사용법: pyinstaller build.spec  (README.md의 "exe로 빌드하기" 참고)

from PyInstaller.utils.hooks import collect_all

datas = [("templates", "templates")]
binaries = []
hiddenimports = []

# uvicorn과 playwright는 동적 import(문자열 기반 플러그인 로딩)를 쓰기 때문에
# PyInstaller가 정적 분석만으로는 필요한 하위 모듈을 다 못 찾는다. collect_all로
# 각 패키지의 서브모듈/데이터/바이너리를 통째로 넣어준다.
# 주의: collect_all("playwright")는 파이썬 패키지와 드라이버(브라우저를 원격 제어하는
# 실행파일)까지만 포함한다 — Chromium 브라우저 본체는 여기 안 들어있고, 최초 실행 시
# autowrite.py의 _ensure_chromium_installed()가 사용자 PC에 따로 내려받는다.
for pkg in ("uvicorn", "playwright"):
    pkg_datas, pkg_binaries, pkg_hiddenimports = collect_all(pkg)
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hiddenimports

a = Analysis(
    ["autowrite.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="AutoWrite",
    debug=False,
    strip=False,
    upx=False,
    console=True,  # Chromium 다운로드 진행 상황, 캡차 대기 안내 등을 보여줘야 해서 콘솔 유지
    onefile=True,
)
