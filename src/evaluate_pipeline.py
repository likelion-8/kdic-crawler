"""testset_all.jsonl 전체를 pipeline.rag_answer_eval로 돌려 자동 채점한다.

각 질문을 rag_answer_eval(query)에 넣어 (답변·intent·사용 청크·시간)을 받고, 정답 데이터
(expected_sources·intent·must_include·question_type)와 대조해 지표를 낸다. 한 문항 실패가
전체를 멈추지 않도록 try/except로 감싸 failed_cases에 남긴다.

설계 원칙(2026-07-23 정리): **문자열로 '의미'를 흉내내는 지표는 계속 새어 신뢰할 수 없다**
(거절 표현·정답 문구는 무한히 다르게 쓰임). 그래서 자동 summary에는 **구조적 사실만** 남기고,
정확도·거절 적절성 같은 '의미' 판단은 **사람이 읽는 층화 표본(build_sample)** 을 앵커로 삼는다.

- summary(구조 지표, aggregate): 생성 성공률 · 평균 응답시간 · 정답 출처 포함률(페이지ID 집합 일치)
- intent 정확도: `--loo-intent` (분류기가 평가셋 자기참조 leak이라 summary엔 안 넣음)
- 정확도·거절 앵커: `--sample` → 사람 채점 표본. 프록시(must_include·거절감지)는 여기서
  '표본 선별 힌트'로만 쓴다(지표로 보고하지 않음).
- `--judge`/`--validate-judge` 코드는 남겨두되(미검증) summary엔 없다 — 사람 표본으로 검증 후 판단.

주의:
- rag_answer_eval는 검색(Qdrant 임베디드)+HCX를 실제로 호출한다. Qdrant는 단일 프로세스라
  **평가 중 챗봇 터미널을 열지 말 것.** HCX는 문항당 1회 호출(전체 문항 수만큼 호출 — 비용·시간).
- 전량 실행 전에 `--limit 50` 등으로 소규모 검증 권장.

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

# 거절 감지 마커. 시스템 프롬프트는 "제공된 자료에서 확인할 수 없습니다"로 거절하라 하지만
# LLM이 자유롭게 바꿔 쓴다("답변을 드릴 수 없습니다" 등) → 관찰된 종결 표현을 모두 포함한다.
# ⚠️ 종결형(~습니다/어렵)으로 앵커링한다 — bare "확인할 수 없"은 내용의 "확인할 수 없는 경우"를
# 오탐하므로 넣지 않는다(856 실측으로 확인).
REFUSAL_MARKERS = [
    "확인할 수 없습니다", "확인되지 않습니다", "확인되지 않아",
    "답변을 드릴 수 없", "답변을 제공할 수 없", "답변드리기 어렵", "답변이 어렵",
    "답변을 제공해 드리기 어렵", "제공할 수 없습니다", "제공해 드릴 수 없", "드리기 어렵습니다",
    "안내가 어렵", "안내드리기 어렵", "알 수 없습니다", "찾을 수 없습니다",
]
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
    표기만 달라 substring이 실패 → 정확도를 과소평가함. 의미 동일하므로 정규화해 맞춘다.
    '/' 구분자도 포함한다(golden_labels 검증 중 발견 - corpus의 부보금융회사 갱신일이
    "2026/03/31"처럼 슬래시로 적혀있어 '-.년' 구분자만으로는 못 잡았음, 2026-07-23)."""
    s = re.sub(r"\s+", "", s)
    s = re.sub(r"(\d{4})[-./년\s]*(\d{1,2})[-./월\s]*(\d{1,2})일?",
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
    """기록들 → 요약 지표. **구조적 사실만** 담는다(문자열로 의미를 흉내내는 지표는 제외).

    의도적으로 뺀 것: 답변 정확도·거절 성공률·민원 섹션 포함률(문자열 프록시라 계속 새어
    신뢰 불가) / intent_정확도(분류기가 평가셋 자기참조 leak — 실제값은 loo_intent()) /
    judge(미검증). 정확도·거절 적절성 같은 '의미' 판단은 build_sample()로 뽑은 사람 표본 채점을
    앵커로 삼는다. 여기 남은 셋은 문자열 의미해석 없이 사실로 확정되는 것들이다."""
    def rate(xs):
        xs = [x for x in xs if x is not None]
        return round(sum(bool(x) for x in xs) / len(xs), 4) if xs else None

    inscope = [r for r in records if not r["is_out_of_scope"]]
    oos = [r for r in records if r["is_out_of_scope"]]
    elapsed = [r["elapsed"] for r in records if r["elapsed"] is not None]
    return {
        "n_total": len(records),
        "n_inscope": len(inscope),
        "n_out_of_scope": len(oos),
        # 생성_성공률은 _write_outputs에서 failed 포함해 다시 채운다
        "평균_응답시간_s": round(sum(elapsed) / len(elapsed), 2) if elapsed else None,
        "정답출처_포함률_inscope": rate([r["correct_source"] for r in inscope]),
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
    답변에서만 계산되는 결정론 플래그(refused·must_include_hit)는 저장된 answer로 매번 재계산한다
    — 매처가 개선되면 옛 결과에도 소급 반영돼, 부분 재실행(retry)으로 옛·새 값이 섞이지 않는다
    (HCX 불필요). ※ civil_procedure는 llm_text 기반이라 여기서 재계산 못함(run 시점 값 유지)."""
    for r in records:
        r["refused"] = is_refused(r["answer"])
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


def build_sample(out="results", size=80):
    """정확도·거절 적절성의 **진짜 앵커** — 사람이 읽고 채점할 층화 표본을 뽑는다.

    문자열 프록시(must_include·거절감지)는 자동 지표로는 계속 새어 신뢰 못 하므로, 여기선
    '표본을 고르는 힌트'로만 쓴다(판정은 사람이 함). 표본은 (a)프록시가 오답 의심한 것
    (b)out_of_scope(거절 적절성) (c)in-scope인데 거절한 것(과잉거절 의심) (d)유형 대표 를
    섞어 대표성+정보성을 함께 갖춘다. 순서 고정 → 재현 가능.

    출력 {out}/review_sample.jsonl: 질문·기준답변·실제답변 + 채점칸(정확한가·거절_적절·메모).
    팀원이 이 칸을 채우면 그게 신뢰 가능한 정확도/거절 수치가 된다(프록시·judge는 이걸로 검증)."""
    outdir = ROOT / out
    R = [json.loads(l) for l in open(outdir / "baseline_results.jsonl", encoding="utf-8") if l.strip()]
    tsmap = {json.loads(l)["test_id"]: json.loads(l)
             for l in open(TESTSET, encoding="utf-8") if l.strip()}
    srt = lambda rs: sorted(rs, key=lambda x: x["test_id"])

    strata = [  # (선정이유, 배정수, 후보)
        ("프록시_오답의심", 25, [r for r in R if r["must_include_hit"] is False]),
        ("out_of_scope", 20, [r for r in R if r["is_out_of_scope"]]),
        ("inscope_거절", 12, [r for r in R if not r["is_out_of_scope"] and r["refused"]]),
    ]
    picked = {}  # test_id -> (선정이유, record)  — dict라 삽입순 유지·자동 dedup
    for name, quota, rs in strata:
        for r in srt(rs)[:quota]:
            picked.setdefault(r["test_id"], (name, r))
    rest = srt([r for r in R if r["test_id"] not in picked])  # 나머지 유형 대표(균등 stride)
    need = size - len(picked)
    if need > 0 and rest:
        step = max(1, len(rest) // need)
        for r in rest[::step]:
            if len(picked) >= size:
                break
            picked.setdefault(r["test_id"], ("유형대표", r))

    sample = []
    for reason, r in picked.values():
        t = tsmap[r["test_id"]]
        sample.append({
            "test_id": r["test_id"], "선정이유": reason, "question_type": r["question_type"],
            "is_out_of_scope": r["is_out_of_scope"], "question": t["question"],
            "reference_answer": t["reference_answer"], "answer": r["answer"],
            "expected_sources": t.get("expected_sources"), "chunk_pages": r["chunk_pages"],
            # 참고 힌트(판정 아님 — 사람 채점 보조용)
            "_힌트_must_include": t.get("must_include"),
            "_힌트_프록시정답": r["must_include_hit"], "_힌트_거절감지": r["refused"],
            # ↓ 사람이 채우는 칸
            "정확한가": "", "거절_적절": "", "메모": "",
        })

    (outdir / "review_sample.jsonl").write_text(
        "".join(json.dumps(s, ensure_ascii=False) + "\n" for s in sample), encoding="utf-8")
    counts = Counter(reason for reason, _ in picked.values())
    print(f"사람 채점 표본 {len(sample)}건 → {out}/review_sample.jsonl")
    for k, v in counts.items():
        print(f"  {k}: {v}")
    print("팀원이 정확한가(예/아니오/애매)·거절_적절(예/아니오/해당없음)·메모 칸을 채우면 앵커가 됨.")
    return 0


def loo_intent():
    """intent 분류기의 leave-one-out 정확도(HCX 불필요, 임베딩만).

    ⚠️ 파이프라인의 intent_정확도(summary)는 leak이다 — classify_intent은 testset_all 질문들과의
    1-최근접인데, 평가 질문이 그 참조셋에 그대로 들어 있어 자기 자신이 최근접이 된다(train=test).
    여기서는 각 질문의 최근접에서 '자기 자신'을 빼고 다시 재봐 실제 일반화 정확도를 추정한다.
    (앞서 question_type/business_function 분류기에서 확인된 형제효과와 같은 뿌리)"""
    import numpy as np
    from query_classifier import _get_classifier
    c = _get_classifier("intent")           # emb: 정규화된 in-scope 질문 임베딩, types: 라벨
    emb, types = c.emb, np.array(c.types)
    S = emb @ emb.T                          # 코사인 유사도(정규화됨)
    np.fill_diagonal(S, -1e9)                # 자기 자신 제외 → 진짜 leave-one-out
    pred = types[np.argmax(S, axis=1)]
    acc = float((pred == types).mean())
    print(f"intent LOO 정확도(자기 제외 1-NN): {acc:.4f}  (n={len(types)}, in-scope only)")
    print("  → 이 값이 실제 추정치. summary의 intent_정확도(~0.98)는 self-match leak이라 무의미.")
    return acc


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
    assert is_refused("자료에 없어 답변을 제공할 수 없습니다.")  # 마커 밖 거절 표현 포착
    assert not is_refused("실지명의를 확인할 수 없는 경우 반환에서 제외됩니다.")  # 내용 오탐 방지
    assert has_source("답변...\n[출처]\n- 보호한도 (https://x)") and not has_source("근거 없음")
    assert must_include_hit("원금과 1억원까지", ["1억원"]) is True
    assert must_include_hit("보호됩니다", ["1억원"]) is False
    assert must_include_hit("아무거나", []) is None
    # 정규화: 공백·날짜 표기차 흡수 (856 실측 오탐 케이스)
    assert must_include_hit("통상 익 영업일에 입금", ["익영업일"]) is True
    assert must_include_hit("2012년 9월 10일 개시", ["2012-09-10"]) is True
    assert must_include_hit("2026/03/31 기준", ["2026년 3월 31일"]) is True  # 슬래시 날짜
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
    # aggregate 스모크 — 구조 지표만 담기고 프록시·judge·intent는 빠졌는지 함께 확인
    recs = [
        {"is_out_of_scope": False, "correct_source": True, "elapsed": 3.0},
        {"is_out_of_scope": True, "correct_source": None, "elapsed": 1.0},
    ]
    s = aggregate(recs)
    assert s["정답출처_포함률_inscope"] == 1.0 and s["평균_응답시간_s"] == 2.0
    assert s["n_out_of_scope"] == 1
    # 롤백된 프록시·leak 지표는 summary에 없어야 함
    for k in ["must_include_커버리지_inscope(정확도_프록시)", "답변정확도_judge",
              "거절_성공률_oos", "민원_서류포함률", "intent_정확도"]:
        assert k not in s, f"{k}는 summary에서 빠져야 함"
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
    ap.add_argument("--loo-intent", action="store_true",
                    help="intent 정확도를 leave-one-out으로 재측정(summary의 intent_정확도는 leak)")
    ap.add_argument("--sample", nargs="?", type=int, const=80, default=None,
                    help="사람 채점용 층화 표본 추출(정확도 앵커). 기본 80건")
    ap.add_argument("--selftest", action="store_true", help="지표 함수만 검증(모델 불필요)")
    args = ap.parse_args()
    if args.selftest:
        _selftest()
    elif args.sample is not None:
        sys.exit(build_sample(out=args.out, size=args.sample))
    elif args.loo_intent:
        sys.path.insert(0, str(ROOT / "src"))
        sys.exit(0 if loo_intent() is not None else 1)
    elif args.validate_judge:
        sys.exit(validate_judge(out=args.out))
    elif args.retry_failed:
        sys.path.insert(0, str(ROOT / "src"))
        sys.exit(retry_failed(out=args.out, judge=args.judge))
    else:
        sys.path.insert(0, str(ROOT / "src"))
        sys.exit(run(limit=args.limit, out=args.out, judge=args.judge))
