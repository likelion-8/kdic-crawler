"""api/masking.mask_text — 게시된 관리자 규칙이 실제 마스킹에 반영되는지(미구현 ③).

runtime_config.get_prompt 만 대역으로. 회귀 대상 셋 : (1) 고정 4종은 게시본과 무관하게 항상
적용(바닥), (2) 게시된 활성 규칙이 실제로 가려진다, (3) 잘못된 정규식·비활성 규칙은 건너뛴다.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
for p in (ROOT, ROOT / "api", ROOT / "src"):
    sys.path.insert(0, str(p))

import runtime_config  # noqa: E402
from api.masking import mask_text  # noqa: E402


@pytest.fixture
def published(monkeypatch):
    state = {"active": True, "items": []}
    monkeypatch.setattr(runtime_config, "get_prompt",
                        lambda _k, _d: {"masking": {"active": state["active"], "items": state["items"]}})
    return state


def test_fixed_rules_apply_even_with_empty_publication(published):
    assert mask_text("전화 010-1234-5678") == "전화 [전화번호 마스킹]"


def test_published_active_rule_masks(published):
    published["items"] = [{"pattern": r"\b\d{6}-\d{2}\b", "replacement": "[사번 마스킹]", "active": True}]
    assert mask_text("사번 123456-78 문의") == "사번 [사번 마스킹] 문의"


def test_inactive_rule_is_skipped(published):
    published["items"] = [{"pattern": r"사번", "replacement": "[X]", "active": False}]
    assert mask_text("사번 문의") == "사번 문의"


def test_broken_regex_skips_only_that_rule(published):
    published["items"] = [
        {"pattern": "[깨진", "replacement": "[X]", "active": True},
        {"pattern": r"내선\s*\d{4}", "replacement": "[내선 마스킹]", "active": True},
    ]
    assert mask_text("내선 1234 로") == "[내선 마스킹] 로"


def test_masking_switch_off_keeps_fixed_floor(published):
    # 목록 전체 스위치를 꺼도 고정 4종(바닥)은 남는다 — 개인정보 경로에서 실수로 전부 꺼지는 것을 막는다
    published["active"] = False
    published["items"] = [{"pattern": r"사번", "replacement": "[X]", "active": True}]
    assert mask_text("사번 010-1234-5678") == "사번 [전화번호 마스킹]"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
