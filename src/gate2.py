"""Gate 2 — 임베딩 유사도 기반 도메인 판정 게이트(Gate 1 뒤, 쿼리 플래너 앞).

Gate 1과 같은 정밀도 우선 철학(설계 프롬프트: "확실한 것만 즉시 처리하고, 조금이라도
애매하면 전부 통과") — Gate 1의 룰 기반 판정을 놓친 out-of-domain 중, 참조 사전과의
임베딩 유사도로 "확실하다"고 판단되는 경우만 추가로 EXIT시킨다. 애매하면 CONTINUE로
다음 단계(향후 Gate 3 크로스인코더 → Gate 4 Supervisor LLM)로 넘긴다.

판정 방식: 클러스터 centroid 평균이 아니라 **개별 문장 벡터 전체 중 최댓값**(nearest
neighbor) — 참조 사전(config/gate2_reference.json)의 문장 하나하나를 독립 벡터로 두면
길이가 다른 항목(단어 ~ 문장)을 섞어도 서로 희석되지 않는다(2026-08-19 팀 확인,
src/crawler/build_gate2_reference.py 참고).

    s_id  = max cos(q, in_domain 참조 벡터)
    s_ood = max cos(q, out_of_domain 참조 벡터)
    block = (s_ood >= threshold) AND (s_ood > s_id)

threshold·결정규칙은 config/gate2_reference.json에서 읽는다(하드코딩 금지) —
experiments/gate2_threshold_search.py 그리드서치로 값을 정했다(2026-08-19, threshold=0.66).

외부 노출 응답은 판정된 카테고리(일상잡담/인접도메인/개인정보상담요청/프롬프트인젝션)와
무관하게 전부 동일한 문구를 쓴다 — Gate 1의 resp_out_of_domain을 그대로 재사용한다(단일
출처, 문구 drift 방지). 어떤 카테고리·클러스터로 판정됐는지는 Gate2Result.reason /
nearest_out_category 등 내부 필드에만 남기고 사용자에게는 노출하지 않는다 — 특히
"프롬프트인젝션으로 판정됨" 사실 자체를 절대 노출하지 않는다.

벡터 캐시(config/gate2_reference.json, data/gate2_cache/*.npy) 로드 실패(파일 없음·손상·
모델/버전 불일치)는 서버를 죽이면 안 된다 — 경고 로그만 남기고 이후 모든 호출에서 항상
CONTINUE로 안전하게 폴백한다(Gate 2를 건너뛰고 파이프라인은 그대로 진행).
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = ROOT / "config" / "gate2_reference.json"
DEFAULT_CACHE_DIR = ROOT / "data" / "gate2_cache"
GATE1_CONFIG_PATH = ROOT / "config" / "gate1_rules.yaml"

logger = logging.getLogger(__name__)


@dataclass
class Gate2Result:
    """Gate 2 판정 결과. EXIT면 response_text를 그대로 사용자에게 반환하고 파이프라인을
    멈춘다. CONTINUE면(s_id/s_ood가 None인 경우 포함 — 캐시 로드 실패) 기존 흐름이 이어진다."""
    action: str                              # "EXIT" | "CONTINUE"
    s_id: Optional[float]
    s_ood: Optional[float]
    threshold: Optional[float]
    nearest_out_cluster_id: Optional[str] = None
    nearest_out_category: Optional[str] = None   # 내부 로그 전용 — 사용자에게 노출 금지
    response_text: Optional[str] = None
    reason: str = ""


_state: dict = {}
_load_failed = False


def _load_gate1_oos_response_text() -> str:
    import yaml
    with open(GATE1_CONFIG_PATH, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    variants = (cfg.get("responses") or {}).get("resp_out_of_domain") or []
    if not variants:
        raise ValueError("gate1_rules.yaml에 responses.resp_out_of_domain이 없음")
    return variants[0]


def _load_state(config_path=None, cache_dir=None) -> Optional[dict]:
    """참조 벡터·threshold·응답문구를 프로세스당 1회 로딩. 실패하면 이후 모든 호출에서
    다시 시도하지 않고(반복 재시도로 매 요청 지연시키지 않음) None을 반환해 run_gate2가
    항상 CONTINUE로 폴백하게 한다."""
    global _load_failed
    if _state:
        return _state
    if _load_failed:
        return None
    try:
        import numpy as np

        config_path = config_path or DEFAULT_CONFIG_PATH
        cache_dir = cache_dir or DEFAULT_CACHE_DIR
        config = json.loads(Path(config_path).read_text(encoding="utf-8"))
        manifest = json.loads((Path(cache_dir) / "manifest.json").read_text(encoding="utf-8"))
        if manifest.get("version") != config.get("version"):
            raise ValueError(
                f"gate2_cache 버전({manifest.get('version')!r})이 config 버전"
                f"({config.get('version')!r})과 다름 — build_gate2_reference.py 재실행 필요")
        in_emb = np.load(Path(cache_dir) / "in_domain_emb.npy")
        out_emb = np.load(Path(cache_dir) / "out_domain_emb.npy")
        threshold = config["threshold"]
        response_text = _load_gate1_oos_response_text()

        _state.update(in_emb=in_emb, out_emb=out_emb, manifest=manifest,
                       threshold=threshold, response_text=response_text)
        return _state
    except Exception:  # noqa: BLE001 — 캐시 로드는 절대 서버를 죽이면 안 된다
        logger.warning("Gate 2 참조 벡터 로드 실패 — 이후 모든 요청에서 Gate 2를 건너뜁니다"
                        "(CONTINUE 폴백).", exc_info=True)
        _load_failed = True
        return None


def run_gate2(text: str, config_path=None, cache_dir=None) -> Gate2Result:
    """질문 하나를 받아 Gate 2 판정 결과를 돌려준다. 캐시 로드 실패 시 항상 CONTINUE."""
    state = _load_state(config_path, cache_dir)
    if state is None:
        return Gate2Result(action="CONTINUE", s_id=None, s_ood=None, threshold=None,
                            reason="vector_cache_unavailable")

    from retrieval import DEFAULT_DENSE_MODEL, _encode_query, _get_model
    model = _get_model(DEFAULT_DENSE_MODEL)
    q = _encode_query(model, text)

    sims_in = state["in_emb"] @ q
    sims_out = state["out_emb"] @ q
    s_id = float(sims_in.max())
    idx_out = int(sims_out.argmax())
    s_ood = float(sims_out[idx_out])
    threshold = state["threshold"]

    if s_ood >= threshold and s_ood > s_id:
        nearest = state["manifest"]["out_of_domain"][idx_out]
        return Gate2Result(
            action="EXIT", s_id=s_id, s_ood=s_ood, threshold=threshold,
            nearest_out_cluster_id=nearest["cluster_id"],
            nearest_out_category=nearest["category"],
            response_text=state["response_text"],
            reason=f"out_of_domain(category={nearest['category']}, cluster={nearest['cluster_id']})")

    return Gate2Result(action="CONTINUE", s_id=s_id, s_ood=s_ood, threshold=threshold,
                        reason="in_domain_or_ambiguous")
