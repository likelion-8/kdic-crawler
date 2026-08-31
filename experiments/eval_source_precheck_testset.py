"""프리체크 테스트셋 실험 — 테스트셋 질문으로 답변을 생성해 프리체크 vs luna 교차표를 만든다.

소급 실험(eval_source_precheck_retro.py)의 표본 부족(운영 로그 9건)을 보충한다. 질문마다
운영과 같은 경로로 답변을 만들고, 같은 입력에 대해 두 판정을 나란히 받아 적는다:
    검색(k=20) → 게이트 → 상위 5 → 프롬프트 → HCX 생성 → 마커 분리
        → source_precheck.classify (0콜)  vs  source_check.validate_answer (luna 1콜)

⚠️ 문항당 LLM 2콜(HCX 생성 1 + luna 검증 1) — 비용·시간 있음. 전량 전 --limit 권장.
쿼리 플래너·분해는 안 탄다(테스트셋 질문은 단일 질문이라 분해가 실익 없고, 플래너 콜만
늘어난다). intent=informational 문항만 돌린다 — civil_petition 은 evidence 조립이 달라
비교 축이 흐려진다(건수만 보고).

rag_runs 로깅 없음(파이프라인 조립부를 직접 부르므로 실사용 로그를 오염시키지 않는다 —
eval_pipeline_generation.py 와 같은 원칙). 기존 파일 수정/git 실행 없음.

실행: python experiments/eval_source_precheck_testset.py [--limit N] [--csv out.csv]
      [--testset data/testset/xxx.jsonl] [--deterministic]
"""
import argparse
import csv
import json
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent   # experiments/ -> 리포 루트
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "src" / "crawler"))

import runtime_config  # noqa: E402
from candidate_ranking import gate_low_relevance, top_k_cut  # noqa: E402
from llm_client import call_hyperclova  # noqa: E402
from prompt_builder import _strip_no_source_marker, build_informational_prompt  # noqa: E402
from retrieval import route_search_chunks  # noqa: E402
from source_check import validate_answer  # noqa: E402
from source_precheck import classify  # noqa: E402

DEFAULT_TESTSET = ROOT / "data" / "testset" / "testset_retrieval_eval_v1.jsonl"


def load_testset(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--testset", default=str(DEFAULT_TESTSET))
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--only", default=None,
                    help="1부터 세는 문항 번호를 쉼표로 — 속도제한 등으로 빠진 건 재실행용 (예: 26,27,44)")
    ap.add_argument("--sleep", type=float, default=0.0,
                    help="문항 사이 대기(초) — HCX 속도제한 회피용 (2026-08-19 오후 66문항 중 17건 튕김)")
    ap.add_argument("--csv", default=None, help="문항별 기록 저장(놓침 후보 수동 라벨링용)")
    ap.add_argument("--deterministic", action="store_true",
                    help="HCX temperature 0 + seed 고정(재현용). 기본은 운영과 같은 샘플링")
    args = ap.parse_args()

    # DB 파라미터 오염 차단 — eval_pipeline_generation.py CLI 와 같은 이유(문서화된
    # 기본값 위에서 실험이 성립하게). 이 프로세스 안에서만 유효하다.
    runtime_config.override("params", {})

    items = load_testset(args.testset)
    if args.only:
        picked = {int(n) for n in args.only.split(",")}
        items = [it for i, it in enumerate(items, 1) if i in picked]
    if args.limit:
        items = items[: args.limit]

    skipped = Counter()
    reasons = Counter()
    cell = Counter()
    records = []
    t0 = time.time()

    for i, item in enumerate(items, 1):
        if args.sleep and i > 1:
            time.sleep(args.sleep)
        q = item["question"]
        if item.get("intent") and item["intent"] != "informational":
            skipped[f"intent={item['intent']}(비교 축 상이)"] += 1
            continue
        try:
            candidates = route_search_chunks(q, k=20)
            top = gate_low_relevance(top_k_cut(candidates, k=5))
            evidence = "\n\n".join(text for _, _, text in top)
            raw = call_hyperclova(build_informational_prompt(q, top),
                                  deterministic=args.deterministic)
            body, marker = _strip_no_source_marker(raw)
        except Exception as e:
            skipped[f"생성 실패({type(e).__name__})"] += 1
            continue

        pc = classify(body, evidence, marker)
        v = validate_answer(q, body, evidence)
        if v is None:
            skipped["luna 검증 실패(None — 교차표 불가)"] += 1
            continue
        reasons[pc.reason] += 1
        luna_flagged = ((not v.appropriate) or v.kind == "ungrounded_claims"
                        or (marker and not v.used_source))
        cell[("clean" if pc.clean else "suspicious",
              "flagged" if luna_flagged else "ok")] += 1
        records.append({
            "test_id": item.get("test_id"), "question": q,
            "precheck": pc.reason, "missing_numbers": ";".join(pc.missing),
            "marker": marker, "used_source": v.used_source, "kind": v.kind,
            "appropriate": v.appropriate, "luna_flagged": luna_flagged,
            "answer": body,  # 놓침 후보 수동 라벨링에 원문이 필요하다
        })
        star = "★" if (pc.clean and luna_flagged) else " "
        print(f"  [{i}/{len(items)}] {star} precheck={pc.reason:16s} "
              f"luna={'문제' if luna_flagged else '정상'}  {q[:40]}")

    analyzed = sum(cell.values())
    print(f"\n{len(items)}문항 중 분석 {analyzed}건, 제외 {sum(skipped.values())}건 "
          f"({time.time() - t0:.0f}초)")
    for why, n in skipped.most_common():
        print(f"  제외: {why} — {n}건")

    print("\n── 교차표 ──")
    print(f"  깨끗함 ∧ luna 정상   : {cell[('clean', 'ok')]:5d}  ← 스킵해도 됐던 건")
    print(f"  깨끗함 ∧ luna 문제   : {cell[('clean', 'flagged')]:5d}  ← ★ 놓침 후보(수동 라벨 필요)")
    print(f"  의심   ∧ luna 정상   : {cell[('suspicious', 'ok')]:5d}")
    print(f"  의심   ∧ luna 문제   : {cell[('suspicious', 'flagged')]:5d}")
    if analyzed:
        clean_n = cell[("clean", "ok")] + cell[("clean", "flagged")]
        print(f"\n  절감률(스킵률): {clean_n}/{analyzed} = {clean_n / analyzed:.1%}")
        if clean_n:
            print(f"  놓침 후보율(clean 중): {cell[('clean', 'flagged')]}/{clean_n} "
                  f"= {cell[('clean', 'flagged')] / clean_n:.1%}")

    print("\n── 프리체크 사유 분포 ──  (number_mismatch 가 많으면 정규화기 보강 검토)")
    for reason, n in reasons.most_common():
        print(f"  {reason:18s} {n:5d}")

    if args.csv and records:
        with open(args.csv, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=list(records[0].keys()))
            w.writeheader()
            w.writerows(records)
        print(f"\n문항별 기록 {len(records)}건 저장: {args.csv}")


if __name__ == "__main__":
    main()
