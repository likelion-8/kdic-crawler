"""testset_all.jsonl 전체를 pipeline.rag_answer_eval로 돌려 자동 채점한다.

각 질문을 rag_answer_eval(query)에 넣어 (답변·intent·사용 청크·시간)을 받고, 정답 데이터
(expected_sources·intent·must_include·question_type)와 대조해 지표를 낸다. 한 문항 실패가
전체를 멈추지 않도록 try/except로 감싸 failed_cases에 남긴다.

지표(대부분 결정론 — LLM judge 불필요):
- 답변 생성 성공률, 평균 응답 시간
- intent 라우팅 정확도(예측 vs 라벨)
- (in-scope) 출처 포함률 / 정답 출처 포함률(사용 청크 페이지에 정답 페이지가 있나, 복수정답 허용)
- (in-scope) must_include 커버리지 = '답변 정확도'의 결정론 프록시 (완전한 정확도는 judge 후속)
- (out_of_scope) 거절 성공률 / (in-scope) 과잉 거절률
- (민원) 답변에 공식 링크(http) 포함률 (절차·서류 품질은 수동/judge 후속)

주의:
- rag_answer_eval는 검색(Qdrant 임베디드)+HCX를 실제로 호출한다. Qdrant는 단일 프로세스라
  **평가 중 챗봇 터미널을 열지 말 것.** HCX는 문항당 1회 호출(856문항이면 856회 — 비용·시간).
- 856 전량 전에 `--limit 50` 등으로 소규모 검증 권장.

실행:  python3 src/evaluate_pipeline.py [--limit N] [--out results]
검증:  python3 src/evaluate_pipeline.py --selftest   (지표 함수만, 모델/HCX 불필요)
"""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TESTSET = ROOT / "data" / "testset" / "testset_all.jsonl"
CHUNKS = ROOT / "data" / "chunks_all.jsonl"

# 시스템 프롬프트의 거절 문구("제공된 자료에서 확인할 수 없습니다") 핵심 조각
REFUSAL_MARKERS = ["확인할 수 없습니다", "확인할 수 없", "확인되지 않"]


def load_gold():
    """chunk_id→page_id, page_id→source_url 매핑과 테스트셋을 로드."""
    chunk2page, page2url = {}, {}
    with open(CHUNKS, encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            chunk2page[d["chunk_id"]] = d["page_id"]
            page2url[d["page_id"]] = d.get("source_url")
    rows = [json.loads(l) for l in open(TESTSET, encoding="utf-8") if l.strip()]
    return rows, chunk2page, page2url


# ── 순수 채점 함수(모델/HCX 불필요, selftest 대상) ──────────────────────────
def is_refused(answer):
    return any(m in answer for m in REFUSAL_MARKERS)


def has_source(answer):
    """답변에 출처 링크가 붙었나(citation.py가 결정론적으로 붙인 URL)."""
    return "http" in answer


def must_include_hit(answer, must):
    """must_include 문구가 모두 답변에 있나 — '답변 정확도'의 결정론 프록시."""
    if not must:
        return None
    return all(m in answer for m in must)


def correct_source(chunk_page_ids, gold_pages):
    """사용한 top 청크의 페이지 중 정답 페이지가 있나(복수정답이면 하나라도)."""
    if not gold_pages:
        return None
    return bool(set(chunk_page_ids) & set(gold_pages))


def score_one(d, result, chunk2page):
    """한 문항 채점 → 기록 dict. d=테스트셋 항목, result=rag_answer_eval 반환."""
    answer = result["answer"]
    gold_pages = list(d.get("expected_sources") or [])
    chunk_pages = [chunk2page.get(c) for c, *_ in result.get("chunks", [])]
    must = d.get("must_include") or []
    intent_gold = d.get("intent")
    return {
        "test_id": d["test_id"],
        "question_type": d["question_type"],
        "is_out_of_scope": not gold_pages,
        "intent_gold": intent_gold,
        "intent_pred": result.get("intent"),
        "intent_correct": (result.get("intent") == intent_gold) if intent_gold else None,
        "refused": is_refused(answer),
        "has_source": has_source(answer),
        "correct_source": correct_source(chunk_pages, gold_pages),
        "must_include_hit": must_include_hit(answer, must),
        "elapsed": result.get("timings", {}).get("total"),
        "chunk_pages": chunk_pages,
        "answer": answer,
    }


def aggregate(records):
    """기록들 → 요약 지표."""
    def rate(xs):
        xs = [x for x in xs if x is not None]
        return round(sum(bool(x) for x in xs) / len(xs), 4) if xs else None

    inscope = [r for r in records if not r["is_out_of_scope"]]
    oos = [r for r in records if r["is_out_of_scope"]]
    civil = [r for r in records if r["intent_gold"] == "civil_petition"]
    elapsed = [r["elapsed"] for r in records if r["elapsed"] is not None]
    return {
        "n_total": len(records),
        "n_inscope": len(inscope),
        "n_out_of_scope": len(oos),
        "생성_성공률": round(len(records) / len(records), 4) if records else None,  # 실패는 failed_cases로 빠짐
        "평균_응답시간_s": round(sum(elapsed) / len(elapsed), 2) if elapsed else None,
        "intent_정확도": rate([r["intent_correct"] for r in records]),
        "출처_포함률_inscope": rate([r["has_source"] for r in inscope]),
        "정답출처_포함률_inscope": rate([r["correct_source"] for r in inscope]),
        "must_include_커버리지_inscope(정확도_프록시)": rate([r["must_include_hit"] for r in inscope]),
        "거절_성공률_oos": rate([r["refused"] for r in oos]),
        "과잉거절률_inscope": rate([r["refused"] for r in inscope]),
        "민원_링크포함률": rate([r["has_source"] for r in civil]),
    }


def run(limit=None, out="results"):
    from pipeline import rag_answer_eval  # 여기서만 import — selftest는 모델 로딩 회피

    rows, chunk2page, page2url = load_gold()
    if limit:
        rows = rows[:limit]
    outdir = ROOT / out
    outdir.mkdir(exist_ok=True)
    print(f"평가 대상 {len(rows)}문항 · 결과 → {outdir.relative_to(ROOT)}/", flush=True)
    print("⚠️ 문항당 HCX 1회 호출. Qdrant 단일 프로세스 — 챗봇 터미널 열지 말 것.\n", flush=True)

    records, failed, review = [], [], []
    t0 = time.time()
    for i, d in enumerate(rows, 1):
        try:
            r = rag_answer_eval(d["question"])
            rec = score_one(d, r, chunk2page)
            records.append(rec)
            # 정확도 프록시(must_include) 실패 → 수동 검수 후보
            if rec["must_include_hit"] is False:
                review.append({"test_id": d["test_id"], "question": d["question"],
                               "must_include": d.get("must_include"), "answer": rec["answer"]})
            if i % 10 == 0 or i == len(rows):
                print(f"  {i}/{len(rows)} 처리 (누적 {time.time()-t0:.0f}s)", flush=True)
        except Exception as e:
            import traceback
            failed.append({"test_id": d.get("test_id"), "question": d.get("question"),
                           "error": f"{type(e).__name__}: {e}", "trace": traceback.format_exc()})
            print(f"  ✗ {d.get('test_id')} 실패: {type(e).__name__}: {e}", flush=True)

    summary = aggregate(records)
    summary["n_failed"] = len(failed)
    summary["n_manual_review"] = len(review)
    summary["생성_성공률"] = round(len(records) / len(rows), 4) if rows else None

    (outdir / "baseline_results.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records), encoding="utf-8")
    (outdir / "failed_cases.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in failed), encoding="utf-8")
    (outdir / "manual_review.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in review), encoding="utf-8")
    (outdir / "baseline_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n=== 요약 ===")
    for k, v in summary.items():
        print(f"  {k}: {v}")
    print(f"\n결과 저장: {outdir.relative_to(ROOT)}/ (results·failed·manual_review·summary)")
    return 0


def _selftest():
    """순수 채점 함수 검증 — 모델/HCX 불필요."""
    assert is_refused("제공된 자료에서 확인할 수 없습니다.") and not is_refused("1억원까지 보호됩니다.")
    assert has_source("답변...\n[출처]\n- 보호한도 (https://x)") and not has_source("근거 없음")
    assert must_include_hit("원금과 1억원까지", ["1억원"]) is True
    assert must_include_hit("보호됩니다", ["1억원"]) is False
    assert must_include_hit("아무거나", []) is None
    assert correct_source(["dp_protlmts", "dp_faq_page"], ["dp_protlmts"]) is True
    assert correct_source(["ha_center"], ["dp_protlmts"]) is False
    assert correct_source(["x"], []) is None
    # aggregate 스모크
    recs = [
        {"is_out_of_scope": False, "intent_gold": "informational", "intent_pred": "informational",
         "intent_correct": True, "refused": False, "has_source": True, "correct_source": True,
         "must_include_hit": True, "elapsed": 3.0},
        {"is_out_of_scope": True, "intent_gold": "informational", "intent_pred": "informational",
         "intent_correct": True, "refused": True, "has_source": False, "correct_source": None,
         "must_include_hit": None, "elapsed": 2.0},
    ]
    s = aggregate(recs)
    assert s["거절_성공률_oos"] == 1.0 and s["정답출처_포함률_inscope"] == 1.0 and s["intent_정확도"] == 1.0
    print("selftest ok")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None, help="앞에서 N문항만(소규모 검증용)")
    ap.add_argument("--out", default="results", help="결과 디렉터리")
    ap.add_argument("--selftest", action="store_true", help="지표 함수만 검증(모델 불필요)")
    args = ap.parse_args()
    if args.selftest:
        _selftest()
    else:
        sys.path.insert(0, str(ROOT / "src"))
        sys.exit(run(limit=args.limit, out=args.out))
