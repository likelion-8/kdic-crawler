"""유형 라우팅 스위치(USE_TYPE_ROUTING) — 전 유형 Dense 통일(2026-08-19 팀 결정)의 회귀 방지.

근거는 retrieval.USE_TYPE_ROUTING 주석과 results/routing_value 실측. 핵심 불변식 두 개:
  1. 스위치 Off(기본)면 분류기를 **호출조차 하지 않고** Dense 로 간다 — 질문당 분류 임베딩
     1회 절약이 설계의 일부라, 분류기가 불리기 시작하면 그 이득이 조용히 사라진다.
  2. 스위치 On 이면 종전 동작(link_guide→Hybrid, 그 외 Dense)이 그대로 복원된다 —
     재도입 경로가 살아 있어야 "코드는 보존, 스위치만 Off" 결정이 성립한다.

DB·모델을 붙이지 않는다 — 가짜 검색기/분류기로 dispatch 만 본다(test_classifier_leakage 와
같은 이음매 원칙). runtime_config.override 로 DB 를 차단해 파라미터를 주입한다.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
for p in (ROOT, ROOT / "src"):
    sys.path.insert(0, str(p))

import runtime_config  # noqa: E402
from retrieval import RoutedRetriever  # noqa: E402


class _FakeRetriever:
    def __init__(self, name):
        self.name = name
        self.calls = 0

    def search(self, query, k, business_function=None):
        self.calls += 1
        return [(f"{self.name}#c", 0.9, "본문")]


class _FakeClassifier:
    """항상 link_guide 로 분류 — 라우팅이 켜져 있다면 반드시 Hybrid 로 보내야 하는 조건."""

    def __init__(self):
        self.calls = 0

    def classify(self, query, **_kwargs):
        self.calls += 1
        return "link_guide"


@pytest.fixture()
def routed():
    hybrid, dense, clf = _FakeRetriever("hybrid"), _FakeRetriever("dense"), _FakeClassifier()
    yield RoutedRetriever(hybrid, dense, clf), hybrid, dense, clf
    runtime_config.override("params", None)  # 다른 테스트로 새지 않게 원복


def test_off_goes_dense_without_classifying(routed):
    r, hybrid, dense, clf = routed
    runtime_config.override("params", {"use_type_routing": False})
    r.search("보호한도 페이지 어디예요?", k=5)
    assert dense.calls == 1 and hybrid.calls == 0, "Off 면 전부 Dense"
    assert clf.calls == 0, "Off 면 분류기 호출 자체가 없어야 한다(임베딩 1회 절약이 설계)"


def test_default_constant_is_off(routed):
    # DB 빈 상태(문서화된 기본값) — USE_TYPE_ROUTING=False 가 기본이다
    r, hybrid, dense, clf = routed
    runtime_config.override("params", {})
    r.search("보호한도 페이지 어디예요?", k=5)
    assert dense.calls == 1 and hybrid.calls == 0 and clf.calls == 0


def test_on_restores_linkguide_hybrid(routed):
    r, hybrid, dense, clf = routed
    runtime_config.override("params", {"use_type_routing": True})
    r.search("보호한도 페이지 어디예요?", k=5)
    assert hybrid.calls == 1 and dense.calls == 0, "On 이면 link_guide→Hybrid 복원"
    assert clf.calls == 1


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
