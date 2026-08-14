"""1단계 파이프라인 평가 — 검색 + 분류 + 오타 강건성. 생성(HCX) 단계는 부르지 않는다.

⚠️ "LLM 호출 없음(빠름)"은 사실이 아니다 — intent 평가가 문항당 OpenAI 호출 1회를 쓴다
(운영 경로 plan_query, USE_QUERY_PLANNER=False면 폴백 classify_intent — 어느 쪽이든 OpenAI).
답변 생성(HCX)을 안 부른다는 뜻이지 "LLM을 아예 안 쓴다"는 뜻이 아니다.

2026-08-14 운영 경로 정합화 두 가지:
- intent 정확도를 운영과 같은 경로로 잰다 — USE_QUERY_PLANNER=True(현행)면 plan_query가
  내놓는 intent, False면 classify_intent(폴백). 이전 버전은 플래너 도입(2026-08-09) 후에도
  폴백 분류기만 재고 있어서 '운영 성능'이 아니었다. 결과 JSON의 intent_source로 어느
  경로를 쟀는지 남긴다.
- ContextHit 지표 추가 — 기존 hit@5는 '후보 20청크를 페이지로 접은 순위 상위 5'라서,
  top5 청크가 같은 페이지에 몰리면 LLM이 실제로 받는 페이지보다 넓게 잡아 과대평가된다.
  ContextHit는 운영 _answer_one과 동일하게 rerank(옵션)→top_k_cut(K_FINAL)→
  gate_low_relevance까지 거친 최종 컨텍스트에 정답 페이지가 있는지를 본다(참값).
  hit@5는 과거 수치와의 비교를 위해 그대로 유지한다.

held-out 세트(testset_pipeline.jsonl)로 '확정된 우리 파이프라인'의 실제 성능을 측정한다.
지금까지의 recall 측정이 '어떤 방식을 쓸지 고르는 개발(dev)용, testset_all 기준'이었다면,
이 평가는 '고른 시스템이 처음 보는 질문에 실제로 얼마나 하는지 재는 최종(test)용'이다.

리랭킹 on/off를 인자로 받는다(--rerank). 지금은 Off로 베이스라인을 재고, GPU 인스턴스를
확보해 리랭커를 도입할 때 --rerank로 같은 코드를 다시 돌려 향상폭을 비교한다(리랭커 하나만
바뀌고 나머지 고정 → 통제 A/B). 결과는 리랭커 설정별 파일명으로 구분 저장한다.

파일 구조에 의존하지 않는다 — test_id 네이밍이 아니라 각 행의 필드(expected_sources·intent·
question_type·note)로 대상을 정한다(팀원이 행을 더 추가해도 안 깨지게).

읽기 전용: 기존 파일 수정/git 실행 없음.
실행: python3 src/eval/eval_pipeline_retrieval.py            # 리랭킹 Off(베이스라인)
      python3 src/eval/eval_pipeline_retrieval.py --rerank   # 리랭킹 On(GPU 확보 시)
"""
import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "src"))

from retrieval import route_search_chunks  # noqa: E402
from query_classifier import classify_intent, _get_classifier  # noqa: E402
from query_planner import plan_query, USE_QUERY_PLANNER  # noqa: E402  운영 intent 경로
from candidate_ranking import gate_low_relevance, rerank, top_k_cut  # noqa: E402
import pipeline  # noqa: E402  K_CANDIDATES/K_FINAL 재사용

TESTSET = ROOT / "data" / "testset" / "testset_pipeline.jsonl"
OUTDIR = ROOT / "results" / "pipeline_holdout"
KS = (1, 3, 5, 10, 20)  # 20 = K_CANDIDATES 전체(리랭커가 만회 가능한 상한 = 후보 recall)


def page_of(chunk_id):
    """chunk_id → page_id. citation.py와 동일 규약(‘#’ 앞이 page_id)."""
    return chunk_id.split("#")[0]


def retrieve_pages(query, k_candidates, use_rerank):
    """실서비스 검색 경로(route_search_chunks)로 후보 청크를 뽑아 두 가지를 돌려준다.

    - ranked_pages: 후보 청크 전체를 페이지로 접은 순위(같은 페이지 첫 등장=최고순위).
      Recall@k·MRR 등 순위 지표용 — 과거 수치와 비교 가능하게 유지.
    - context_pages: 운영 _answer_one과 동일하게 rerank(옵션)→top_k_cut(K_FINAL)→
      gate_low_relevance까지 거친 뒤 **LLM이 실제로 받는 청크들**의 페이지 집합.
      ranked_pages[:5]와 다를 수 있다 — top5 청크가 한 페이지에 몰리면 실제 컨텍스트는
      페이지 1~2개뿐인데 페이지 순위 상위 5는 후보 뒤쪽 페이지까지 담기 때문."""
    # 자기참조 누수 차단 — 골든셋 문항으로 재면 질문이 자기 자신을 유형 분류 예시로
    # 끌어와 라우팅이 항상 정답이 된다. 홀드아웃은 겹침이 없어 무해하고, 골든셋 기반
    # 재측정(AD-006)에서만 실제로 값이 달라진다.
    chunks = route_search_chunks(query, k=k_candidates, exclude_self=True)
    if use_rerank:
        chunks = rerank(query, chunks)
    ranked_pages = []
    for cid, _score, _text in chunks:
        p = page_of(cid)
        if p not in ranked_pages:
            ranked_pages.append(p)
    final = gate_low_relevance(top_k_cut(chunks, k=pipeline.K_FINAL))
    context_pages = {page_of(cid) for cid, _score, _text in final}
    return ranked_pages, context_pages


def recall_mrr(ranked_pages, gold, ks=KS):
    """gold(정답 페이지 집합)에 대한 Recall@k와 MRR. 정답이 여러 개면 비율로 Recall 계산."""
    rec = {k: len(gold & set(ranked_pages[:k])) / len(gold) for k in ks}
    rr = 0.0
    for i, p in enumerate(ranked_pages, 1):
        if p in gold:
            rr = 1.0 / i
            break
    return rec, rr


def eval_retrieval(rows, k_candidates, use_rerank):
    """expected_sources 있는 행만 대상으로 Recall@k·MRR·ContextHit 집계."""
    rec_sum = {k: 0.0 for k in KS}
    rr_sum = ctx_sum = 0.0
    n = 0
    per_row = []
    for r in rows:
        gold = set(r.get("expected_sources") or [])
        if not gold:
            continue
        pages, ctx = retrieve_pages(r["question"], k_candidates, use_rerank)
        rec, rr = recall_mrr(pages, gold)
        ctx_hit = bool(gold & ctx)
        for k in KS:
            rec_sum[k] += rec[k]
        rr_sum += rr
        ctx_sum += ctx_hit
        n += 1
        per_row.append({"test_id": r.get("test_id"), "gold": list(gold),
                        "top5_pages": pages[:5], "hit@5": rec[5] > 0,
                        "context_pages": sorted(ctx), "context_hit": ctx_hit,
                        "rr": round(rr, 4)})
    summary = {f"Recall@{k}": round(rec_sum[k] / n, 4) for k in KS}
    summary["MRR"] = round(rr_sum / n, 4)
    summary["ContextHit"] = round(ctx_sum / n, 4)  # LLM이 실제 받는 컨텍스트에 정답 존재율
    summary["n"] = n
    return summary, per_row


def eval_classification(rows):
    """intent·question_type 분류 정확도(expected_sources 있는 답변형 질문 대상).

    intent는 운영과 같은 경로로 잰다 — USE_QUERY_PLANNER=True면 plan_query(대표 intent =
    첫 하위질문의 것, pipeline._rag_answer_traced의 log_intent와 동일 규약), False면
    classify_intent 폴백. question_type은 운영 라우팅과 동일한 1-NN 분류기."""
    qt_clf = _get_classifier("question_type")
    intent_true, intent_pred = [], []
    qt_true, qt_pred = [], []
    misclassified_intent = []
    for r in rows:
        if not (r.get("expected_sources")):   # oos는 분류 정답이 모호 → 제외
            continue
        q = r["question"]
        if r.get("intent"):
            if USE_QUERY_PLANNER:
                items = plan_query(q)["items"]
                it = items[0]["intent"] if items else "informational"
            else:
                it = classify_intent(q)
            intent_true.append(r["intent"]); intent_pred.append(it)
            if it != r["intent"]:
                misclassified_intent.append({"test_id": r.get("test_id"), "q": q[:45],
                                             "true": r["intent"], "pred": it})
        if r.get("question_type"):
            qt = qt_clf.classify(q)
            qt_true.append(r["question_type"]); qt_pred.append(qt)

    def acc(t, p):
        return round(sum(a == b for a, b in zip(t, p)) / len(t), 4) if t else None

    # link_guide 이진(라우팅에 실제 영향): link_guide냐 아니냐만 봄
    lg_correct = sum(1 for t, p in zip(qt_true, qt_pred)
                     if (t == "link_guide") == (p == "link_guide"))
    return {
        "intent_accuracy": acc(intent_true, intent_pred),
        "intent_source": "plan_query(운영)" if USE_QUERY_PLANNER else "classify_intent(폴백)",
        "intent_n": len(intent_true),
        "question_type_accuracy_5way": acc(qt_true, qt_pred),
        "question_type_n": len(qt_true),
        "link_guide_binary_accuracy": round(lg_correct / len(qt_true), 4) if qt_true else None,
    }, misclassified_intent


def eval_typo_robustness(rows, k_candidates, use_rerank):
    """오타 질문 vs 원본 질문의 Recall@5 비교. note에 '오타' 표시가 있고 원본(test_id에서
    끝 't' 제거)이 존재하는 쌍만 대상(팀원이 다른 방식으로 추가한 행은 자동 제외)."""
    by_id = {r["test_id"]: r for r in rows}
    pairs = []
    for r in rows:
        tid = r.get("test_id", "")
        if "오타" in (r.get("note") or "") or (tid.endswith("t") and tid[:-1] in by_id):
            base = by_id.get(tid[:-1])
            if base and base.get("expected_sources"):
                pairs.append((base, r))
    if not pairs:
        return None
    orig_hit = typo_hit = 0
    for base, typo in pairs:
        gold = set(base["expected_sources"])
        orig_hit += recall_mrr(retrieve_pages(base["question"], k_candidates, use_rerank)[0], gold)[0][5] > 0
        typo_hit += recall_mrr(retrieve_pages(typo["question"], k_candidates, use_rerank)[0], gold)[0][5] > 0
    n = len(pairs)
    return {"n_pairs": n,
            "orig_recall@5": round(orig_hit / n, 4),
            "typo_recall@5": round(typo_hit / n, 4),
            "drop": round((orig_hit - typo_hit) / n, 4)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rerank", action="store_true", help="리랭킹 On(GPU 확보 후 도입 시)")
    args = ap.parse_args()

    rows = [json.loads(l) for l in open(TESTSET, encoding="utf-8") if l.strip()]
    k_c = pipeline.K_CANDIDATES
    tag = "on" if args.rerank else "off"
    n_ans = sum(1 for r in rows if r.get("expected_sources"))
    n_oos = len(rows) - n_ans
    print(f"testset_pipeline: {len(rows)}행 (검색채점 대상 {n_ans} / out-of-scope {n_oos})")
    print(f"리랭킹: {tag.upper()} · K_CANDIDATES={k_c} · (생성 HCX 미호출 / intent는 운영 경로 OpenAI 호출)\n")

    t0 = time.time()
    retr, per_row = eval_retrieval(rows, k_c, args.rerank)
    print("=== [A] 검색 (Recall@k · MRR · ContextHit) ===")
    for k in KS:
        print(f"  Recall@{k}: {retr[f'Recall@{k}']:.4f}")
    print(f"  MRR:       {retr['MRR']:.4f}   (n={retr['n']})")
    print(f"  ContextHit: {retr['ContextHit']:.4f}   (운영 최종 컨텍스트에 정답 존재율 — 참값)")

    clf, mis_intent = eval_classification(rows)
    print("\n=== [B] 분류 정확도 ===")
    print(f"  intent 정확도:            {clf['intent_accuracy']}  (n={clf['intent_n']}, {clf['intent_source']})")
    print(f"  question_type 정확도(5분류): {clf['question_type_accuracy_5way']}  (n={clf['question_type_n']})")
    print(f"  link_guide 이진 정확도:     {clf['link_guide_binary_accuracy']}  (라우팅 실제 영향)")

    typo = eval_typo_robustness(rows, k_c, args.rerank)
    print("\n=== [D] 오타 강건성 (Recall@5) ===")
    if typo:
        print(f"  원본: {typo['orig_recall@5']:.4f}  →  오타: {typo['typo_recall@5']:.4f}"
              f"  (하락 {typo['drop']:+.4f}, 쌍 {typo['n_pairs']}개)")
    else:
        print("  (오타 쌍 없음 — note '오타' 또는 t접미 쌍 미발견)")

    print(f"\n총 소요 {time.time()-t0:.0f}s")

    OUTDIR.mkdir(parents=True, exist_ok=True)
    out = OUTDIR / f"retrieval_rerank_{tag}.json"
    out.write_text(json.dumps({
        "rerank": args.rerank, "k_candidates": k_c,
        "n_rows": len(rows), "n_answerable": n_ans, "n_out_of_scope": n_oos,
        "retrieval": retr, "classification": clf, "typo_robustness": typo,
        "intent_misclassified": mis_intent, "per_row_retrieval": per_row,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"결과 저장: {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
