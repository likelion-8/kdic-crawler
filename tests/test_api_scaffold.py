"""관리자 API 공통 뼈대가 유지되는지 확인한다.

여러 명이 각자 관리자 API 를 만드는 동안, 아래 두 가지가 깨지면 증상이 조용하다.

1. 라우터 등록이 빠지면 그 기능 전체가 404 인데, 서버는 멀쩡히 뜨고 로그도 조용하다.
2. 라우터의 인증 의존성이 사라지면 **인증 없이 열린다.** 화면에서는 로그인한 채로 쓰니
   아무도 눈치채지 못하고, 발견하는 건 보통 배포 후다.

그래서 코드 리뷰가 아니라 테스트로 잡는다. DB 접속은 필요 없다.
"""
import sys
from pathlib import Path

from fastapi import APIRouter

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api.deps import get_current_admin
from api.main import create_app
from api.routers import admin_knowledge, admin_pipeline


def _router_dependency_calls(router: APIRouter):
    return [d.dependency for d in router.dependencies]


def test_pipeline_router_requires_auth_for_every_endpoint():
    """라우터 수준 인증. 여기 추가되는 엔드포인트는 따로 챙기지 않아도 401 이 걸린다.

    이 줄이 사라지면 앞으로 추가되는 잡 API 가 전부 인증 없이 열린다.
    """
    assert get_current_admin in _router_dependency_calls(admin_pipeline.router)


def test_endpoints_added_to_the_pipeline_router_reach_the_app():
    """이 뼈대의 약속 그 자체 — 라우터에 엔드포인트만 더하면 서비스에 붙는다.

    app.routes 를 뒤져 등록 여부를 보는 방법은 못 쓴다. 지금 FastAPI 는 include_router 결과를
    _IncludedRouter 로 감싸 prefix 를 밖으로 내주지 않는다. 그래서 실제로 엔드포인트를 하나
    붙여 보고 앱의 OpenAPI 에 나타나는지로 확인한다 — 등록과 접두어를 한 번에 검증한다.
    """
    probe = "/__scaffold_probe__"

    @admin_pipeline.router.get(probe)
    def _probe():  # pragma: no cover - 호출하지 않는다. 경로가 잡히는지만 본다
        return {}

    try:
        paths = create_app().openapi()["paths"]
        assert admin_pipeline.router.prefix + probe in paths
    finally:
        # 모듈 전역 라우터라 다른 테스트에 새어 나가지 않게 되돌린다.
        admin_pipeline.router.routes = [
            r for r in admin_pipeline.router.routes
            if getattr(r, "path", None) != admin_pipeline.router.prefix + probe
        ]


def test_knowledge_router_is_registered():
    """이미 엔드포인트가 있는 라우터는 경로로 바로 확인된다."""
    assert "/api/admin/knowledge/pages" in create_app().openapi()["paths"]


def test_admin_routers_live_under_the_admin_prefix():
    """접두어가 어긋나면 프론트가 부르는 경로와 안 맞는다(전 화면 404)."""
    assert admin_pipeline.router.prefix == "/api/admin"
    assert admin_knowledge.router.prefix == "/api/admin/knowledge"


if __name__ == "__main__":
    test_pipeline_router_requires_auth_for_every_endpoint()
    test_endpoints_added_to_the_pipeline_router_reach_the_app()
    test_knowledge_router_is_registered()
    test_admin_routers_live_under_the_admin_prefix()
    print("OK - 관리자 API 공통 뼈대(등록 · 라우터 수준 인증 · 접두어)")
