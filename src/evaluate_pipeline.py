"""testset_all.jsonl 전체를 pipeline.rag_answer_eval로 돌려 자동 채점한다.

각 질문을 rag_answer_eval(query)에 넣어 (답변·intent·사용 청크·시간)을 받고, 정답 데이터
(expected_sources·intent·must_include·question_type)와 대조해 지표를 낸다. 한 문항 실패가
전체를 멈추지 않도록 try/except로 감싸 failed_cases에 남긴다.

지표(대부분 결정론 — LLM judge 불필요):
- 답변 생성 성공률, 평균 응답 시간
- intent 라우팅 정확도(예측 vs 라벨)
- (in-scope) 출처 포함률 / 정답 출처 포함률(사용 청크 페이지에 정답 페이지가 있나, 복수정답 허용)
- (in-scope) must_include 커버리지 = '답변 정확도'의 결정론 프록시
- 답변 정확도 LLM judge (--judge, opt-in) — 기준답변 대비 사실 부합. judge 신뢰도는 사람 대조 검증 필요
- (out_of_scope) 거절 성공률 / (in-scope) 과잉 거절률
- (민원) 절차·서류·공식페이지 포함률 (각 섹션 분리 판정)

주의:
- rag_answer_eval는 검색(Qdrant 임베디드)+HCX를 실제로 호출한다. Qdrant는 단일 프로세스라
  **평가 중 챗봇 터미널을 열지 말 것.** HCX는 문항당 1회 호출(856문항이면 856회 — 비용·시간).
- 856 전량 전에 `--limit 50` 등으로 소규모 검증 권장.

실행:  python3 src/evaluate_pipeline.py [--limit N] [--out results]
검증:  python3 src/evaluate_pipeline.py --selftest   (지표 함수만, 모델/HCX 불필요)
"""
import argparse
import json
import re
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TESTSET = ROOT / "data" / "testset" / "testset_all.jsonl"
CHUNKS = ROOT / "data" / "chunks_all.jsonl"

# 시스템 프롬프트의 거절 문구("제공된 자료에서 확인할 수 없습니다") 핵심 조각
REFUSAL_MARKERS = ["확인할 수 없습니다", "확인할 수 없", "확인되지 않"]
# 민원 답변 섹션 마커 (prompt_builder.assemble_civil_petition_answer가 붙이는 heading)
DOC_MARKER = "**필요 서류**"
PAGE_MARKER = "**신청 페이지**"


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


def _normalize(s):
    """정확매칭 오탐 제거용 정규화. 공백 제거 + 날짜를 YYYY-MM-DD로 통일.
    이유(856 실측): 답변 '익 영업일'/'2012년 9월 10일'이 must '익영업일'/'2012-09-10'과
    표기만 달라 substring이 실패 → 정확도를 과소평가함. 의미 동일하므로 정규화해 맞춘다."""
    s = re.sub(r"\s+", "", s)
    s = re.sub(r"(\d{4})[-.년\s]*(\d{1,2})[-.월\s]*(\d{1,2})일?",
               lambda m: f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}", s)
    return s


def must_include_hit(answer, must):
    """must_include 문구가 모두 답변에 있나 — '답변 정확도'의 결정론 프록시(all-or-nothing 하한선).
    공백·날짜 표기차는 _normalize로 흡수한다(순수 형식차이로 인한 오탐 제거)."""
    if not must:
        return None
    na = _normalize(answer)
    return all(_normalize(m) in na for m in must)


def correct_source(chunk_page_ids, gold_pages):
    """사용한 top 청크의 페이지 중 정답 페이지가 있나(복수정답이면 하나라도)."""
    if not gold_pages:
        return None
    return bool(set(chunk_page_ids) & set(gold_pages))


def civil_sections(answer, llm_text):
    """민원 답변의 절차·서류·공식페이지 포함 여부를 각각 판정(결정론).
    절차=LLM이 쓴 절차 텍스트가 있고 거절이 아님, 서류/공식페이지=해당 섹션 heading 존재."""
    return {
        "procedure": bool(llm_text.strip()) and not is_refused(llm_text),
        "documents": DOC_MARKER in answer,
        "official_page": PAGE_MARKER in answer,
    }


def judge_correct(question, answer, reference):
    """LLM judge — 후보 답변이 기준 답변과 사실적으로 부합하나(예/아니오). HCX 1회 추가 호출.
    ⚠️ judge 자체 신뢰도는 사람 대조로 검증해야 함(미검증 상태에선 참고치)."""
    from llm_client import call_hyperclova
    prompt = [
        ("system", "당신은 예금보험공사 답변을 채점하는 평가자입니다. 표현 차이는 무시하고, "
                   "후보 답변이 기준 답변과 사실·수치·핵심 정보 면에서 부합하는지만 판단하세요."),
        ("human", f"질문: {question}\n\n기준 답변: {reference}\n\n후보 답변: {answer}\n\n"
                  "후보 답변이 기준 답변과 사실적으로 부합하면 '예', 틀리거나 핵심을 빠뜨렸으면 "
                  "'아니오'로만 답하세요."),
    ]
    return call_hyperclova(prompt).strip().startswith("예")


def score_one(d, result, chunk2page):
    """한 문항 채점 → 기록 dict. d=테스트셋 항목, result=rag_answer_eval 반환."""
    answer = result["answer"]
    llm_text = result.get("llm_text", "")
    gold_pages = list(d.get("expected_sources") or [])
    chunk_pages = [chunk2page.get(c) for c, *_ in result.get("chunks", [])]
    must = d.get("must_include") or []
    intent_gold = d.get("intent")
    sec = civil_sections(answer, llm_text) if intent_gold == "civil_petition" else {}
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
        "civil_procedure": sec.get("procedure"),
        "civil_documents": sec.get("documents"),
        "civil_official_page": sec.get("official_page"),
        "judge_correct": None,  # --judge 시 run 루프에서 채움
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
        "답변정확도_judge": rate([r.get("judge_correct") for r in records]),  # --judge 없으면 None
        "거절_성공률_oos": rate([r["refused"] for r in oos]),
        "과잉거절률_inscope": rate([r["refused"] for r in inscope]),
        "민원_절차포함률": rate([r["civil_procedure"] for r in civil]),
        "민원_서류포함률": rate([r["civil_documents"] for r in civil]),
        "민원_공식페이지포함률": rate([r["civil_official_page"] for r in civil]),
    }


def validate_judge(out="results"):
    """LLM judge 신뢰도 검증(재현 가능, HCX 불필요) — 이미 저장된 baseline_results.jsonl을 읽어
    judge를 결정론 프록시(must_include)와 교차대조하고, 판단이 갈리는 지점을 층화 표본으로 뽑아
    사람이 답변 vs 기준답변을 직접 확인할 수 있게 파일로 남긴다.

    핵심: judge와 프록시가 어긋나는 곳이 곧 '정확도를 무엇으로 볼 것인가'가 갈리는 지점이다.
    프록시(all-or-nothing 정확매칭)는 하한선, judge(의미 판정)는 관대할 수 있으므로 둘 다 완벽하지
    않다. 표본을 사람이 읽고 어느 쪽이 맞는지 확인하는 것이 이 검증의 목적.

    출력: {out}/judge_validation.json(교차표·일치율), {out}/judge_review_sample.jsonl(표본)."""
    outdir = ROOT / out
    R = [json.loads(l) for l in open(outdir / "baseline_results.jsonl", encoding="utf-8") if l.strip()]
    ts = {json.loads(l)["test_id"]: json.loads(l)
          for l in open(TESTSET, encoding="utf-8") if l.strip()}

    # 저장된 답변으로 프록시를 '정규화 매처'로 다시 채점(코드 개선이 소급 반영되게).
    both = []
    for r in R:
        if r.get("judge_correct") is None:
            continue
        must = ts[r["test_id"]].get("must_include") or []
        mh = must_include_hit(r["answer"], must)
        if mh is None:
            continue
        both.append((r, r["judge_correct"], mh))

    c = Counter((jc, mh) for _, jc, mh in both)
    agree = c[(True, True)] + c[(False, False)]
    n = len(both)
    crosstab = {
        "n": n,
        "judge_T_must_T": c[(True, True)],
        "judge_T_must_F": c[(True, False)],
        "judge_F_must_T": c[(False, True)],
        "judge_F_must_F": c[(False, False)],
        "일치율": round(agree / n, 4) if n else None,
        "judge_정확도": round(sum(jc for _, jc, _ in both) / n, 4) if n else None,
        "프록시_정확도_정규화후": round(sum(mh for _, _, mh in both) / n, 4) if n else None,
        "설명": "일치율이 낮으면 둘 중 하나(또는 둘 다)가 틀린 것 — 아래 표본을 사람이 확인할 것. "
                "judge_T_must_F가 크면 프록시가 부분답변·표기차로 과소평가했을 가능성, "
                "judge_F_must_T가 크면 judge가 엄격했거나 프록시가 놓친 사실오류일 가능성.",
    }

    # 4개 버킷에서 각 N개씩 층화 표본(순서 고정 → 재현 가능). 사람 확인용 필드 포함.
    def take(jc, mh, k):
        return [r for r, j, m in both if (j, m) == (jc, mh)][:k]
    picked = take(True, False, 8) + take(False, False, 5) + take(False, True, 5) + take(True, True, 4)
    sample = []
    for r in picked:
        t = ts[r["test_id"]]
        sample.append({
            "test_id": r["test_id"], "judge": r["judge_correct"],
            "must_hit_정규화": must_include_hit(r["answer"], t.get("must_include") or []),
            "must_include": t.get("must_include"), "question": t["question"],
            "reference_answer": t["reference_answer"], "answer": r["answer"],
            "사람판정": "",  # 검토자가 예/아니오/애매 로 채우는 칸
        })

    (outdir / "judge_validation.json").write_text(
        json.dumps(crosstab, ensure_ascii=False, indent=2), encoding="utf-8")
    (outdir / "judge_review_sample.jsonl").write_text(
        "".join(json.dumps(s, ensure_ascii=False) + "\n" for s in sample), encoding="utf-8")

    print("=== judge 신뢰도 교차검증 ===")
    for k, v in crosstab.items():
        if k != "설명":
            print(f"  {k}: {v}")
    print(f"\n표본 {len(sample)}건 → {out}/judge_review_sample.jsonl (사람판정 칸 채워 확인)")
    print(f"교차표 → {out}/judge_validation.json")
    return 0


def _process_one(d, chunk2page, judge, rag_answer_eval):
    """한 문항 실행+채점 → rec. 파이프라인 오류는 호출자가 잡도록 그대로 전파.
    judge(opt-in) 실패는 답변 채점을 버리지 않게 격리(judge_correct=None 유지)."""
    rec = score_one(d, rag_answer_eval(d["question"]), chunk2page)
    if judge and not rec["is_out_of_scope"] and d.get("reference_answer"):
        try:
            rec["judge_correct"] = judge_correct(d["question"], rec["answer"], d["reference_answer"])
        except Exception as e:
            print(f"  judge 실패({d['test_id']}): {type(e).__name__}: {e}", flush=True)
    return rec


def _write_outputs(outdir, records, failed, tsmap):
    """records/failed로 4개 산출물 저장 후 summary 반환. manual_review는 records에서 파생.
    run()·retry_failed() 공용 — 두 경로의 출력 형식을 일치시킨다.
    must_include_hit은 저장된 answer로 매번 재계산한다 — 정규화 매처가 개선되면 옛 결과에도
    소급 반영돼, 부분 재실행(retry)으로 옛·새 값이 섞이는 것을 막는다(HCX 불필요)."""
    for r in records:
        r["must_include_hit"] = must_include_hit(r["answer"], tsmap[r["test_id"]].get("must_include") or [])
    review = [{"test_id": r["test_id"], "question": tsmap[r["test_id"]]["question"],
               "must_include": tsmap[r["test_id"]].get("must_include"), "answer": r["answer"]}
              for r in records if r["must_include_hit"] is False]
    total = len(records) + len(failed)
    summary = aggregate(records)
    summary["n_failed"] = len(failed)
    summary["n_manual_review"] = len(review)
    summary["생성_성공률"] = round(len(records) / total, 4) if total else None

    (outdir / "baseline_results.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records), encoding="utf-8")
    (outdir / "failed_cases.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in failed), encoding="utf-8")
    (outdir / "manual_review.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in review), encoding="utf-8")
    (outdir / "baseline_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def _print_summary(summary, outdir):
    print("\n=== 요약 ===")
    for k, v in summary.items():
        print(f"  {k}: {v}")
    print(f"\n결과 저장: {outdir.relative_to(ROOT)}/ (results·failed·manual_review·summary)")


def run(limit=None, out="results", judge=False):
    from pipeline import rag_answer_eval  # 여기서만 import — selftest는 모델 로딩 회피

    rows, chunk2page, _ = load_gold()
    if limit:
        rows = rows[:limit]
    tsmap = {d["test_id"]: d for d in rows}
    outdir = ROOT / out
    outdir.mkdir(exist_ok=True)
    print(f"평가 대상 {len(rows)}문항 · 결과 → {outdir.relative_to(ROOT)}/", flush=True)
    print("⚠️ 문항당 HCX 1회 호출. Qdrant 단일 프로세스 — 챗봇 터미널 열지 말 것.\n", flush=True)

    records, failed = [], []
    t0 = time.time()
    for i, d in enumerate(rows, 1):
        try:
            records.append(_process_one(d, chunk2page, judge, rag_answer_eval))
            if i % 10 == 0 or i == len(rows):
                print(f"  {i}/{len(rows)} 처리 (누적 {time.time()-t0:.0f}s)", flush=True)
        except Exception as e:
            import traceback
            failed.append({"test_id": d.get("test_id"), "question": d.get("question"),
                           "error": f"{type(e).__name__}: {e}", "trace": traceback.format_exc()})
            print(f"  ✗ {d.get('test_id')} 실패: {type(e).__name__}: {e}", flush=True)

    _print_summary(_write_outputs(outdir, records, failed, tsmap), outdir)
    return 0


def retry_failed(out="results", judge=False):
    """failed_cases.jsonl의 문항만 재실행해 성공분을 기존 결과에 병합(주로 RateLimit 재시도).
    RateLimit 완화를 위해 문항 사이에 짧은 간격을 둔다. 재실패분은 failed에 남기고 재집계·재저장."""
    from pipeline import rag_answer_eval

    outdir = ROOT / out
    rows, chunk2page, _ = load_gold()
    tsmap = {d["test_id"]: d for d in rows}
    records = [json.loads(l) for l in open(outdir / "baseline_results.jsonl", encoding="utf-8") if l.strip()]
    failed_in = [json.loads(l) for l in open(outdir / "failed_cases.jsonl", encoding="utf-8") if l.strip()]
    print(f"재실행 대상 {len(failed_in)}건 (기존 성공 {len(records)}건에 병합)", flush=True)

    still_failed = []
    for i, fc in enumerate(failed_in, 1):
        d = tsmap.get(fc["test_id"])
        if d is None:  # 테스트셋에서 사라진 test_id는 재시도 불가
            still_failed.append(fc)
            continue
        try:
            records.append(_process_one(d, chunk2page, judge, rag_answer_eval))
            print(f"  {i}/{len(failed_in)} ✓ {fc['test_id']}", flush=True)
        except Exception as e:
            import traceback
            still_failed.append({"test_id": fc["test_id"], "question": d["question"],
                                 "error": f"{type(e).__name__}: {e}", "trace": traceback.format_exc()})
            print(f"  {i}/{len(failed_in)} ✗ {fc['test_id']}: {type(e).__name__}", flush=True)
        time.sleep(1.0)  # ponytail: 고정 1s 간격으로 RateLimit 완화. 계속 429면 값을 올릴 것

    _print_summary(_write_outputs(outdir, records, still_failed, tsmap), outdir)
    return 0


def _selftest():
    """순수 채점 함수 검증 — 모델/HCX 불필요."""
    assert is_refused("제공된 자료에서 확인할 수 없습니다.") and not is_refused("1억원까지 보호됩니다.")
    assert has_source("답변...\n[출처]\n- 보호한도 (https://x)") and not has_source("근거 없음")
    assert must_include_hit("원금과 1억원까지", ["1억원"]) is True
    assert must_include_hit("보호됩니다", ["1억원"]) is False
    assert must_include_hit("아무거나", []) is None
    # 정규화: 공백·날짜 표기차 흡수 (856 실측 오탐 케이스)
    assert must_include_hit("통상 익 영업일에 입금", ["익영업일"]) is True
    assert must_include_hit("2012년 9월 10일 개시", ["2012-09-10"]) is True
    assert must_include_hit("원금만", ["1억원"]) is False  # 진짜 누락은 여전히 False
    assert correct_source(["dp_protlmts", "dp_faq_page"], ["dp_protlmts"]) is True
    assert correct_source(["ha_center"], ["dp_protlmts"]) is False
    assert correct_source(["x"], []) is None
    # 민원 3분리
    full = "위임장을 지참해 신청하세요.\n\n**필요 서류**\n- 위임장: http://x\n\n**신청 페이지**\n- 신청: http://y"
    s3 = civil_sections(full, "위임장을 지참해 신청하세요.")
    assert s3 == {"procedure": True, "documents": True, "official_page": True}
    s3b = civil_sections("제공된 자료에서 확인할 수 없습니다.", "제공된 자료에서 확인할 수 없습니다.")
    assert s3b["procedure"] is False and s3b["documents"] is False
    # aggregate 스모크
    recs = [
        {"is_out_of_scope": False, "intent_gold": "civil_petition", "intent_pred": "civil_petition",
         "intent_correct": True, "refused": False, "has_source": True, "correct_source": True,
         "must_include_hit": True, "civil_procedure": True, "civil_documents": True,
         "civil_official_page": True, "judge_correct": True, "elapsed": 3.0},
        {"is_out_of_scope": True, "intent_gold": "informational", "intent_pred": "informational",
         "intent_correct": True, "refused": True, "has_source": False, "correct_source": None,
         "must_include_hit": None, "civil_procedure": None, "civil_documents": None,
         "civil_official_page": None, "judge_correct": None, "elapsed": 2.0},
    ]
    s = aggregate(recs)
    assert s["거절_성공률_oos"] == 1.0 and s["정답출처_포함률_inscope"] == 1.0
    assert s["민원_서류포함률"] == 1.0 and s["답변정확도_judge"] == 1.0
    print("selftest ok")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None, help="앞에서 N문항만(소규모 검증용)")
    ap.add_argument("--out", default="results", help="결과 디렉터리")
    ap.add_argument("--judge", action="store_true", help="답변 정확도 LLM judge(문항당 HCX 1회 추가)")
    ap.add_argument("--validate-judge", action="store_true",
                    help="저장된 결과로 judge를 프록시와 교차검증+표본추출(재실행/HCX 불필요)")
    ap.add_argument("--retry-failed", action="store_true",
                    help="failed_cases.jsonl 문항만 재실행해 기존 결과에 병합(RateLimit 재시도)")
    ap.add_argument("--selftest", action="store_true", help="지표 함수만 검증(모델 불필요)")
    args = ap.parse_args()
    if args.selftest:
        _selftest()
    elif args.validate_judge:
        sys.exit(validate_judge(out=args.out))
    elif args.retry_failed:
        sys.path.insert(0, str(ROOT / "src"))
        sys.exit(retry_failed(out=args.out, judge=args.judge))
    else:
        sys.path.insert(0, str(ROOT / "src"))
        sys.exit(run(limit=args.limit, out=args.out, judge=args.judge))
