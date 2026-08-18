"""색인 교체 게이트 — 새로 만든 청크가 품질 기준을 통과할 때만 운영 인덱스에 반영한다.

**왜 있나.** 재적재는 운영 인덱스를 그대로 갈아엎었다. 기획서(AD-004·PRD-03)는
"재청킹 → 재임베딩 → 평가 → 통과 시 교체(미달 시 자동 중단·기존 유지)"를 명시했고
docs/search_index_versioning.md 도 "실패하면 롤백이 아니라 **통과해야 반영**"을 원칙으로
적어 두었으나, 그 판정을 실제로 하는 코드가 없었다. 되돌릴 수 없는 버튼은 비개발자가 누르지
않고, 안 누르면 결국 개발자를 부른다 — 관리자 화면이 없애려던 바로 그 상태다.

**임시 색인을 만들지 않는 이유.** 기획서 문구는 "임시 색인"이지만 대상이 500청크 남짓이라
별도 컬렉션을 세울 필요가 없다. 새 청크를 메모리 인덱스로 올려 홀드아웃 검색만 돌리고,
통과할 때만 운영 테이블에 반영한다. 같은 보장을 훨씬 싸게 얻고, 임시 컬렉션의 수명 관리·정리
실패라는 새 실패 모드도 생기지 않는다. (기획서 문구 정정은 팀 확인 후 함께 한다.)

**홀드아웃을 쓰는 이유.** 골든셋(evaluation_dataset)은 질문 유형 분류의 참조 예시로 운영
검색 경로가 그대로 읽는다(query_classifier.QuestionTypeClassifier). 골든셋으로 재면 평가
대상 질문이 자기 자신을 유사도 1.0 으로 끌어와 라우팅이 항상 정답이 되어 실제보다 후하게
나온다. 홀드아웃(test_set)은 골든셋과 겹치는 문항이 0건이라 이 누수가 없고, 게이트 목표
수치도 원래 홀드아웃에서 측정해 정한 값이다.

**이음매.** `evaluate(unit_ids, texts, rows, build=...)` 하나다. build 를 주입하면 임베딩
모델을 올리지 않고도 판정 로직을 시험할 수 있어, 테스트가 이 인터페이스를 그대로 통과한다.
"""
from typing import Callable, Optional

# 정답 페이지가 상위 몇 위 안에 들었는지로 채점한다. 운영이 LLM 에 넘기는 근거 수(K_FINAL)와
# 같은 k 라야 게이트가 "실제로 답변에 쓰일 근거가 맞았나"를 재는 것이 된다.
RECALL_K = 5
# 1차 후보 폭. pipeline.K_CANDIDATES 와 같은 값을 쓰되, 이 모듈이 pipeline 을 import 하면
# 테스트가 무거워져 호출부(worker)가 넘긴다.
DEFAULT_K_CANDIDATES = 20


def page_of(chunk_id: str) -> str:
    """chunk_id → page_id. citation.py·observation.py 와 동일 규약('#' 앞이 page_id)."""
    return chunk_id.split("#")[0]


def _targets() -> dict:
    """게이트 목표값. 정본은 admin_evaluations.GATE_CRITERIA 하나뿐이라 거기서 끌어온다 —
    여기에 숫자를 다시 적으면 화면이 보여주는 기준과 실제 판정이 조용히 갈린다."""
    from api.routers.admin_evaluations import GATE_CRITERIA
    wanted = {"retrieval_accuracy@5": "recall@5", "mrr": "mrr"}
    out = {}
    for key, _label, _target, _op, threshold, _fmt in GATE_CRITERIA:
        if key in wanted:
            out[wanted[key]] = threshold
    return out


def _recall_mrr(ranked_pages: list, gold: set) -> tuple:
    """정답이 여러 개면 비율로 Recall — eval_pipeline_retrieval.recall_mrr 과 같은 규약이다.
    두 곳의 채점이 다르면 게이트를 통과한 색인이 정기 평가에서는 미달로 나온다."""
    recall = len(gold & set(ranked_pages[:RECALL_K])) / len(gold)
    rr = 0.0
    for i, p in enumerate(ranked_pages, 1):
        if p in gold:
            rr = 1.0 / i
            break
    return recall, rr


def evaluate(unit_ids: list, texts: list, rows: list, *,
             k_candidates: int = DEFAULT_K_CANDIDATES,
             build: Optional[Callable] = None) -> dict:
    """새 청크 집합을 메모리 인덱스로 올려 홀드아웃으로 채점하고 통과 여부를 돌려준다.

    rows 는 [{"question": str, "expected_sources": [page_id, ...]}] 이다. expected_sources 가
    빈 문항(범위 외)은 검색 채점 대상이 아니라 건너뛴다 — 정답이 없는 질문에 Recall 을 매기면
    분모가 0 이라 전체 수치가 왜곡된다.

    build 는 (unit_ids, texts) -> retriever 팩토리다. retriever 는 search(query, k) 로
    [(unit_id, score), ...] 를 준다(retrieval.DenseRetriever 와 같은 모양). 기본값은 실제
    DenseRetriever 이고, 테스트는 여기에 가짜를 넣어 모델 없이 판정 로직만 시험한다.

    돌려주는 dict:
      passed   전부 통과했나
      metrics  {"recall@5": float, "mrr": float, "n": int}
      targets  적용한 목표값
      failures 미달한 지표 [{"key","measured","target"}] — 화면이 그대로 보여준다
    """
    scored = [r for r in rows if r.get("expected_sources")]
    if not scored:
        raise ValueError("채점할 홀드아웃 문항이 없다 — test_set 이 비었는지 확인할 것")

    if build is None:
        from retrieval import DenseRetriever
        build = DenseRetriever
    retriever = build(unit_ids, texts)

    recall_sum = rr_sum = 0.0
    for row in scored:
        hits = retriever.search(row["question"], k_candidates)
        pages = []
        for hit in hits:
            page = page_of(hit[0])
            if page not in pages:
                pages.append(page)
        recall, rr = _recall_mrr(pages, set(row["expected_sources"]))
        recall_sum += recall
        rr_sum += rr

    n = len(scored)
    metrics = {"recall@5": round(recall_sum / n, 4), "mrr": round(rr_sum / n, 4), "n": n}
    targets = _targets()
    failures = [
        {"key": key, "measured": metrics[key], "target": target}
        for key, target in targets.items() if metrics[key] < target
    ]
    return {"passed": not failures, "metrics": metrics, "targets": targets, "failures": failures}


def describe(result: dict) -> str:
    """미달 사유를 사람이 읽는 한 줄로. 관리자가 '무엇이 얼마나 모자랐나'를 보고 재시도할지
    자료를 고칠지 판단한다(작업 단계 상세에 그대로 실린다)."""
    if result["passed"]:
        m = result["metrics"]
        return f"홀드아웃 {m['n']}문항 통과 — Recall@{RECALL_K} {m['recall@5']} · MRR {m['mrr']}"
    parts = [f"{f['key']} {f['measured']} < {f['target']}" for f in result["failures"]]
    return f"홀드아웃 {result['metrics']['n']}문항 미달 — " + " · ".join(parts)
