"""답변 1건의 관측 기록 — 답변할 때 계산되고 버려지던 값을 붙잡아 rag_runs.observation 에 남긴다.

**왜 있나.** AD-005 대화 로그 상세가 관리자에게 내는 값 중 넷(source_count·source_used·
marker·normalized)이 "답변시 계산·미저장"이라 항상 null 이었다. 민원 건을 열어도 어떤 근거를
썼는지, 근거에 기반한 답인지를 볼 수 없어 **검색 문제인지 프롬프트 문제인지 데이터 문제인지
가릴 수 없었다.** 원인을 못 가리면 다음 화면(AD-007/AD-008/AD-002)을 고를 수 없고, AD-006
문항 후보도 정답 없는 껍데기로만 등록된다. 관리자 작업 흐름이 여기서 끊긴다.

**이음매.** 새로 넓히지 않았다. `answer.log_run(question, resp, sub_plans, ...)` 이 이미
`sub_plans` 를 받고 있고 `SubPlan.top` 에 (chunk_id, score, text) 가 들어 있다 — 필요한 값은
이미 이음매를 건너고 있었고 log_run 이 읽지 않았을 뿐이다. 그래서 호출부 3곳(sse.py)은
한 줄도 바뀌지 않는다. 유일하게 못 건너던 검증 판정은 `finalize_sub` 가 SubPlan 에 적어 보낸다
(SubPlan 은 내부 dataclass — 와이어 타입 SubAnswer 를 건드리면 프론트 계약·MSW 목이 함께
흔들리므로 손대지 않는다).

**읽는 쪽도 여기 둔다.** admin_logs(AD-005 상세)와 admin_evaluations(AD-006 후보 자동 채움)이
각자 JSON 을 파헤치면 모양이 세 군데로 흩어진다. summarize()·expected_pages() 로 감싸 이 파일이
모양의 정본이 되게 한다.
"""
from typing import Optional

# 관측에 남길 상위 청크 수. 화면(AD-005)이 근거를 훑는 용도라 컨텍스트에 실제로 들어간
# 만큼(K_FINAL=5)이면 충분하다 — 후보 20개를 통째로 남기면 로그가 답변보다 커진다.
TOP_N = 5


def page_of(chunk_id: str) -> str:
    """chunk_id → page_id. citation.py·eval_pipeline_retrieval 과 동일 규약('#' 앞이 page_id)."""
    return chunk_id.split("#")[0]


def build(sub_plans: list) -> Optional[dict]:
    """하위 질문별 관측을 모아 rag_runs.observation 에 넣을 dict 를 만든다.

    sub_plans 가 비면(캐시 적중·가드레일 차단처럼 검색을 안 탄 경로) None 을 준다 — 빈 dict 를
    넣으면 화면이 '관측이 있는데 내용이 없음'과 '관측 자체가 없음'을 구분하지 못한다.

    판정 필드(marker/used_source/kind/appropriate/normalized)는 finalize_sub 가 SubPlan 에
    적어 둔 값을 그대로 읽는다. 아직 안 적혔으면(스위치 Off·예외) None 으로 남긴다 —
    **모르는 것을 false 로 적지 않는다.** 이 규칙을 깨면 화면이 '검증 안 함'과 '검증 실패'를
    같은 것으로 보여준다(logs.py 주석의 선례).
    """
    if not sub_plans:
        return None
    subs = []
    for sp in sub_plans:
        top = [
            {"chunk_id": cid, "page_id": page_of(cid), "score": round(float(score), 4)}
            for cid, score, _text in (getattr(sp, "top", None) or [])[:TOP_N]
        ]
        subs.append({
            "question": sp.question,
            "intent": getattr(sp, "intent", None),
            "top": top,
            "marker": getattr(sp, "obs_marker", None),
            "used_source": getattr(sp, "obs_used_source", None),
            "kind": getattr(sp, "obs_kind", None),
            "appropriate": getattr(sp, "obs_appropriate", None),
            "normalized": getattr(sp, "obs_normalized", None),
            # 프리체크 섀도 판정(exp/source-precheck-v1) — 소급 실험 표본용. None = 미계산.
            "precheck": getattr(sp, "obs_precheck", None),
            "precheck_missing": getattr(sp, "obs_precheck_missing", None),
        })
    return {"subs": subs}


def with_served_from(observation: Optional[dict], served_from: Optional[str]) -> Optional[dict]:
    """관측에 '무엇이 이 답변을 냈나'를 얹는다. served_from 이 없으면 그대로 돌려준다.

    캐시 적중은 검색·생성을 통째로 건너뛰므로 sub_plans 가 비고 build() 가 None 을 준다 —
    그 결과 rag_runs.observation 이 NULL 이라 **캐시 적중과 가드레일 차단·Gate EXIT 가 로그에서
    구분되지 않았다.** AD-005 상세가 '판정 원천 없음'이라고만 말하고 왜인지는 못 말했고, 총 소요
    1.2초가 왜 이렇게 빠른지도 설명되지 않았다.

    판정 필드는 건드리지 않는다 — 캐시라고 근거 사용 여부를 지어내면 안 된다(파일 상단 규칙).
    """
    if not served_from:
        return observation
    return {**(observation or {}), "served_from": served_from}


def served_from(observation: Optional[dict]) -> Optional[str]:
    """이 답변을 낸 경로. 현재 값은 'cache' 하나이고, 없으면 None(=평소 경로)."""
    return (observation or {}).get("served_from")


def _subs(observation: Optional[dict]) -> list:
    return (observation or {}).get("subs") or []


def expected_pages(observation: Optional[dict]) -> list:
    """근거로 실제 쓰인 페이지를 순위 순서로, 중복 없이. AD-006 후보의 정답 출처 초안이다.

    used_source 가 참인 하위 답변의 근거만 모은다 — 근거를 안 쓴 답변(인사·범위 밖)의 검색
    결과까지 정답 후보로 올리면 관리자가 지워야 할 것만 늘어난다. 판정이 None(검증 꺼짐)이면
    포함한다: 검증을 안 돌렸을 뿐 근거는 실제로 프롬프트에 들어갔다.
    """
    pages = []
    for s in _subs(observation):
        if s.get("used_source") is False:
            continue
        for t in s.get("top") or []:
            if t["page_id"] not in pages:
                pages.append(t["page_id"])
    return pages


def summarize(observation: Optional[dict]) -> dict:
    """AD-005 상세가 쓰는 4개 값. 관측이 없으면 전부 None — 이전과 같은 '모름'이다.

    - source_count : 근거로 쓴 페이지 수(expected_pages 와 같은 기준)
    - source_used  : 하위 답변 중 하나라도 근거를 썼나
    - marker       : LLM 자기보고 마커. 하위별로 갈리면 '혼재'
    - normalized   : 본문이 표준 안내로 교체됐나(환각·동문서답 차단이 걸린 건)
    """
    subs = _subs(observation)
    if not subs:
        return {"source_count": None, "source_used": None, "marker": None, "normalized": None}

    def _any(key):
        vals = [s.get(key) for s in subs if s.get(key) is not None]
        return any(vals) if vals else None

    markers = {s.get("marker") for s in subs if s.get("marker") is not None}
    marker = None
    if len(markers) == 1:
        marker = "[SOURCE_USED]" if markers.pop() else "[NO_SOURCE]"
    elif len(markers) > 1:
        marker = "혼재"

    return {
        "source_count": len(expected_pages(observation)),
        "source_used": _any("used_source"),
        "marker": marker,
        "normalized": _any("normalized"),
    }
