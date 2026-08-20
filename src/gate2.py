"""Gate 2 — accepted V6 non-LLM request-unit semantic scope gate.

Runtime order:
    Gate1 -> Gate2 V6 -> Planner/Retrieval -> Answer

V6 is the accepted request-unit rescue over the frozen V5 relational classifier:
- discourse-aware request-unit decomposition;
- each unit keeps its full clause context (no semantic span atomization);
- BGE-m3-ko compares Relation / Action / Terminal / Responsibility /
  Contrastive Responsibility frames;
- all IN -> CONTINUE, all OOS -> EXIT, mixed -> MIXED;
- unknown/runtime failures fail open.

Gate2 itself makes zero LLM, external API, retrieval, reranker, or database calls.
The previous nearest-neighbor Gate2 (gate2_reference.json + gate2_cache + 0.66
threshold) is intentionally removed from production.
"""
from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path
from typing import Optional

from gptlike_scope_v5 import V5UnitDecision
from gptlike_scope_v6 import classify_gptlike_scope_v6

ROOT = Path(__file__).resolve().parent.parent
GATE1_CONFIG_PATH = ROOT / "config" / "gate1_rules.yaml"

logger = logging.getLogger(__name__)

_DEFAULT_OOS_RESPONSE = (
    "문의하신 내용은 예금보험공사가 제공하는 정보의 범위를 벗어난 질문이라 정확한 안내가 "
    "어렵습니다. 예금자보호제도나 착오송금 반환지원 등 공사 업무에 대해 궁금하신 점을 물어봐 주세요."
)


@dataclass(frozen=True)
class Gate2Result:
    action: str
    prediction: str
    units: tuple[V5UnitDecision, ...]
    unitizer_mode: str
    response_text: Optional[str] = None
    reason: str = ""
    # Deprecated compatibility fields for callers/log readers from the removed
    # similarity Gate2. They stay None and are not used for routing.
    s_id: Optional[float] = None
    s_ood: Optional[float] = None
    threshold: Optional[float] = None
    nearest_out_cluster_id: Optional[str] = None
    nearest_out_category: Optional[str] = None

    @property
    def in_scope_units(self) -> tuple[V5UnitDecision, ...]:
        return tuple(x for x in self.units if x.prediction == "IN_SCOPE")

    @property
    def oos_units(self) -> tuple[V5UnitDecision, ...]:
        return tuple(x for x in self.units if x.prediction == "OOS")

    def to_dict(self) -> dict:
        return {
            "action": self.action,
            "prediction": self.prediction,
            "unitizer_mode": self.unitizer_mode,
            "reason": self.reason,
            "in_scope_count": len(self.in_scope_units),
            "oos_count": len(self.oos_units),
            "units": [x.to_dict() for x in self.units],
        }


def _load_gate1_oos_response_text() -> str:
    """Reuse Gate1's public OOS copy; config failure must not break routing."""
    try:
        import yaml
        cfg = yaml.safe_load(GATE1_CONFIG_PATH.read_text(encoding="utf-8")) or {}
        variants = (cfg.get("responses") or {}).get("resp_out_of_domain") or []
        if variants:
            return str(variants[0])
    except Exception:
        logger.warning("Gate2 V6 OOS response config load failed; using fallback", exc_info=True)
    return _DEFAULT_OOS_RESPONSE


def run_gate2(text: str, config_path=None, cache_dir=None) -> Gate2Result:
    """Classify one query with accepted V6; removed Gate2 args are ignored."""
    del config_path, cache_dir
    try:
        decision = classify_gptlike_scope_v6(text)
    except Exception as exc:
        # Scope gate failures must not turn answerable user questions into hard rejects.
        logger.warning("Gate2 V6 runtime failure — CONTINUE fail-open", exc_info=True)
        return Gate2Result(
            action="CONTINUE",
            prediction="IN_SCOPE",
            units=(),
            unitizer_mode="runtime_error_fail_open",
            reason=f"runtime_error_fail_open:{type(exc).__name__}",
        )

    action = decision.action
    if action not in {"CONTINUE", "EXIT", "MIXED"}:
        logger.warning("Gate2 V6 returned unknown action %r — CONTINUE fail-open", action)
        action = "CONTINUE"

    if action == "EXIT":
        reason, prediction = "all_request_units_oos", "OOS"
    elif action == "MIXED":
        reason, prediction = "mixed_request_units", "MIXED"
    else:
        reason, prediction = "all_request_units_in_scope_or_fail_open", "IN_SCOPE"

    return Gate2Result(
        action=action,
        prediction=prediction,
        units=tuple(decision.units),
        unitizer_mode=decision.unitizer_mode,
        response_text=_load_gate1_oos_response_text() if action in {"EXIT", "MIXED"} else None,
        reason=reason,
    )
