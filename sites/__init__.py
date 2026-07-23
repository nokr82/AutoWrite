from .base import PostContent, SiteAdapter
from .dcinside import DcInsideAdapter
from .naver_cafe import NaverCafeAdapter
from .tistory import TistoryAdapter

# 사이트 id -> 어댑터 클래스. 나중에 사이트를 추가하면 여기에만 등록하면 된다.
SITE_ADAPTERS: dict[str, type[SiteAdapter]] = {
    TistoryAdapter.site_id: TistoryAdapter,
    DcInsideAdapter.site_id: DcInsideAdapter,
    NaverCafeAdapter.site_id: NaverCafeAdapter,
}

__all__ = [
    "PostContent",
    "SiteAdapter",
    "SITE_ADAPTERS",
    "TistoryAdapter",
    "DcInsideAdapter",
    "NaverCafeAdapter",
]
