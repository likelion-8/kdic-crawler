"""2단계 파이프라인 평가 — 생성(답변) 품질. LLM(HyperCLOVA X) 호출 있음(느림·비용).

held-out 세트(testset_pipeline.jsonl)로 답변 단계를 측정한다:
  - must_include 커버리지: 답변에 핵심 사실(금액·기한 등)이 들어갔나(결정론 프록시)
  - 출처 정확률: 정답 페이지의 실제 URL이 답변에 붙었나(citation.py가 결정론적으로 붙임)
  - out-of-scope 처리율: 답 없는 질문(의미없음)에 지어내지 않고 적절히 거절/안내하나
  - 생성 성공률·평균 응답시간

설계 원칙(옛 evaluate_pipeline.py의 교훈): 문자열로 '의미'를 흉내내는 자동지표는 과신 금지.
must_include·거절감지는 결정론 프록시(하한선)로만 쓰고, 애매한 건 manual_review로 빼 사람이 확인.

리랭킹 on/off를 인자로 받는다(--rerank). 지금 Off 베이스라인 → GPU 확보 후 리랭커 도입 시 재실행.
⚠️ 문항당 HCX 1회 이상 호출(비용·시간). 전량 전 --limit 로 소규모 검증 권장.
※ "Qdrant 단일 프로세스라 평가 중 streamlit 켜지 말 것"이라는 경고가 여기 있었으나 더 이상
   해당되지 않는다 — 2026-08-03에 Dense가 Supabase pgvector로 이관해 프로세스 배타 제약이
   사라졌다(retrieval.PgVectorDenseRetriever). 챗봇과 동시에 돌려도 된다.

읽기 전용: 기존 파일 수정/git 실행 없음.
실행: python3 src/eval/eval_pipeline_generation.py [--limit N] [--rerank]
"""
import argparse
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "src"))

import pipeline  # noqa: E402  (USE_RERANKER 토글 + _rag_answer_traced 호출)

TESTSET = ROOT / "data" / "testset" / "testset_pipeline.jsonl"
CORPUS = ROOT / "data" / "corpus.jsonl"
OUTDIR = ROOT / "results" / "pipeline_holdout"

# 거절 표현 마커(옛 evaluate_pipeline.py 실측 기반). 종결형으로 앵커 — 내용의 "확인할 수 없는
# 경우" 같은 표현 오탐을 피하려 bare "확인할 수 없"은 넣지 않는다.
REFUSAL_MARKERS = [
    "확인할 수 없습니다", "확인되지 않습니다", "확인되지 않아",
    "답변을 드릴 수 없", "답변을 제공할 수 없", "답변드리기 어렵", "답변이 어렵",
    "답변을 제공해 드리기 어렵", "제공할 수 없습니다", "제공해 드릴 수 없", "드리기 어렵습니다",
    "안내가 어렵", "안내드리기 어렵", "알 수 없습니다", "찾을 수 없습니다",
    "범위를 벗어난", "관련 기관에", "문의하시길",
]


def is_refused(answer):
    return any(m in answer for m in REFUSAL_MARKERS)


def _normalize(s):
    """정확매칭 오탐 제거 — 공백 제거 + 날짜를 YYYY-MM-DD로 통일(표기차 흡수)."""
    s = re.sub(r"\s+", "", s)
    s = re.sub(r"(\d{4})[-.년\s]*(\d{1,2})[-.월\s]*(\d{1,2})일?",
               lambda m: f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}", s)
    return s


def must_include_hit(answer, must):
    """must_include 문구가 모두 답변에 있나(all-or-nothing 하한선). 없으면 None."""
    if not must:
        return None
    na = _normalize(answer)
    return all(_normalize(m) in na for m in must)


def load_page_urls():
    m = {}
    for line in open(CORPUS, encoding="utf-8"):
        d = json.loads(line)
        m[d["page_id"]] = d.get("source_url")
    return m


def evaluate_generation(rows, page2url, *, rerank=False):
    """생성 평가 채점 — main() 과 api 의 run_evaluation 이 공유하는 순수 함수.

    채점 로직(출처 정확률·OOS 거절·must_include 커버리지·실패 기록)을 한 곳에 둔다. 감싸는
    쪽(관리자 평가 API)이 이 로직을 다시 짜지 않게 하기 위함이다. rows 는 testset 행 dict
    리스트(question·expected_sources·question_type·must_include·test_id), page2url 은
    load_page_urls() 결과다. (summary, records, failed) 를 돌려준다.

    ⚠️ 문항당 HCX 1회 이상 호출(비용·시간). 대량이면 rows 를 잘라 넘겨 소규모로 검증할 것.
    """
    pipeline.USE_RERANKER = rerank  # 모듈 전역 토글 → _answer_one 이 런타임에 참조
    records, failed = [], []
    t0 = time.time()
    for i, r in enumerate(rows, 1):
        q = r["question"]
        gold = set(r.get("expected_sources") or [])
        # OOS 판정은 명시적 의도 라벨(question_type=="out_of_scope")로 한다.
        is_oos = (r.get("question_type") == "out_of_scope")
        try:
            answer, timings, _ = pipeline._rag_answer_traced(q)
        except Exception as e:
            failed.append({"test_id": r.get("test_id"), "error": f"{type(e).__name__}: {e}"})
            print(f"  ✗ {r.get('test_id')} 실패: {type(e).__name__}: {e}", flush=True)
            continue
        gold_urls = [page2url.get(p) for p in gold]
        records.append({
            "test_id": r.get("test_id"),
            "is_oos": is_oos,
            "must_hit": must_include_hit(answer, r.get("must_include")),
            "src_correct": (any(u and u in answer for u in gold_urls) if gold else None),
            "has_source": "http" in answer,
            "refused": is_refused(answer),
            "elapsed": timings.get("total"),
            "answer": answer,
        })
        if i % 10 == 0 or i == len(rows):
            print(f"  {i}/{len(rows)} 처리 (누적 {time.time()-t0:.0f}s)", flush=True)

    def rate(xs):
        xs = [x for x in xs if x is not None]
        return round(sum(bool(x) for x in xs) / len(xs), 4) if xs else None

    ans_recs = [r for r in records if not r["is_oos"]]
    oos_recs = [r for r in records if r["is_oos"]]
    elapsed = [r["elapsed"] for r in records if r["elapsed"] is not None]
    summary = {
        "rerank": rerank,
        "n_total": len(rows), "n_success": len(records), "n_failed": len(failed),
        "생성_성공률": round(len(records) / len(rows), 4) if rows else None,
        "평균_응답시간_s": round(sum(elapsed) / len(elapsed), 2) if elapsed else None,
        "must_include_커버리지(답변형)": rate([r["must_hit"] for r in ans_recs]),
        "출처_정확률(답변형)": rate([r["src_correct"] for r in ans_recs]),
        "출처링크_포함률(답변형)": rate([r["has_source"] for r in ans_recs]),
        "oos_적절거절률": rate([r["refused"] for r in oos_recs]),
        "n_answerable": len(ans_recs), "n_oos": len(oos_recs),
    }
    return summary, records, failed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None, help="앞에서 N문항만(소규모 검증)")
    ap.add_argument("--rerank", action="store_true", help="리랭킹 On(GPU 확보 후 도입 시)")
    args = ap.parse_args()

    pipeline.USE_RERANKER = args.rerank  # 모듈 전역 토글 → _answer_one이 런타임에 참조
    tag = "on" if args.rerank else "off"

    rows = [json.loads(l) for l in open(TESTSET, encoding="utf-8") if l.strip()]
    if args.limit:
        rows = rows[:args.limit]
    page2url = load_page_urls()

    n_ans = sum(1 for r in rows if r.get("expected_sources"))
    print(f"testset_pipeline: {len(rows)}행 (답변형 {n_ans} / out-of-scope {len(rows)-n_ans})")
    print(f"리랭킹: {tag.upper()} · ⚠️ 문항당 HCX 호출 — 챗봇 켜지 말 것\n")

    # 채점은 evaluate_generation 이 한다(관리자 평가 API 와 공유하는 순수 함수).
    summary, records, failed = evaluate_generation(rows, page2url, rerank=args.rerank)

    # 사람이 확인할 표본: 답변형인데 must_include 실패 + oos인데 거절 안 함
    review = [{"test_id": r["test_id"], "why": "must_include 실패", "answer": r["answer"]}
              for r in records if not r["is_oos"] and r["must_hit"] is False]
    review += [{"test_id": r["test_id"], "why": "oos인데 거절 안 함(지어냈을 수 있음)",
                "answer": r["answer"]} for r in records if r["is_oos"] and not r["refused"]]

    print("\n=== 생성 평가 요약 ===")
    for k, v in summary.items():
        print(f"  {k}: {v}")
    print(f"  사람확인 필요(manual_review): {len(review)}건")

    OUTDIR.mkdir(parents=True, exist_ok=True)
    out = OUTDIR / f"generation_rerank_{tag}{'_limit'+str(args.limit) if args.limit else ''}.json"
    out.write_text(json.dumps({
        "summary": summary, "manual_review": review,
        "records": records, "failed": failed,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n결과 저장: {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
