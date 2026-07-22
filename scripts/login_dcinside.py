"""디시인사이드 최초 1회 수동 로그인 후 세션(쿠키)을 저장한다.

실행: python scripts/login_dcinside.py
브라우저 창이 뜨면 정상적으로 로그인한 뒤, 터미널로 돌아와 Enter를 누르세요.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import SESSION_DIR
from sites import DcInsideAdapter

if __name__ == "__main__":
    DcInsideAdapter(session_dir=SESSION_DIR).login_manually()
