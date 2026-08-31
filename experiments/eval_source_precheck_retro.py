"""프리체크 소급 실험 — rag_runs 로그에 source_precheck 를 돌려 "켰다면 어땠을지"를 잰다.

지금 운영은 모든 답변에 validate_answer(luna) 1콜을 부르고 판정을 observation 에 남기므로,
프리체크를 실제로 켜지 않고도 교차표를 완전하게 만들 수 있다 — 추가 LLM 콜 0, 위험 0.

                     │ luna: 정상        │ luna: 문제 판정
    프리체크: 깨끗함  │ 스킵해도 됐던 건  │ ★ 놓침 후보 — 이 칸이 실험의 본체
    프리체크: 의심    │ (동작 변화 없음)  │ (동작 변화 없음)

★ 칸의 건은 사람이 근거 원문과 대조해 라벨링해야 한다(--csv 로 뽑아서) — luna 도
경계 문항에서 흔들리므로(api/rag/answer.py 재생성 주석) luna 판정 자체가 정답지가 아니다.
"진짜 놓침"이면 프리체크 조건 보강, "luna 오판"이면 오히려 프리체크가 막아줄 사고다.

## 표본의 두 출처

1) 섀도 필드(observation.subs[].precheck — 2026-08-19 finalize_sub 가 기록 시작):
   실제 생성 원문·실제 evidence 로 판정된 값이라 그대로 쓴다. 다중 하위질문·civil·
   본문 교체 건까지 전부 표본이 된다. 새 트래픽은 모두 이 경로.
2) 그 이전 로그는 소급 재구성 — rag_runs.answer(합본)와 chunk_id 복원의 한계 탓에
   아래 조건이 전부 맞아야만 표본이 된다(못 재는 건 사유별 건수로 보고):
   - 단일 하위질문(합본이라 다중이면 본문 분리 불가)
   - informational(civil 은 검증 evidence 가 절차 안내문이라 재구성 불가)
   - 본문 미교체(normalized=True 는 생성 원문 유실 — luna 문제 판정 건들이므로
     별도 건수로 보고해 놓침 상한 해석에 쓴다)
   - observation.top 의 chunk_id 가 data/chunks_all.jsonl 에 생존(TOP_N=5 = K_FINAL
     이라 생성 때 프롬프트에 든 근거와 같은 범위다)

읽기 전용: rag_runs 를 SELECT 만 한다. 기존 파일 수정/git 실행 없음.
실행: python experiments/eval_source_precheck_retro.py [--limit N] [--csv out.csv]
"""
import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent   # experiments/ -> 리포 루트
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "src" / "crawler"))

from sqlalchemy import select  # noqa: E402

from db import get_session  # noqa: E402
from schema import rag_runs  # noqa: E402
from source_precheck import classify  # noqa: E402

CHUNKS = ROOT / "data" / "chunks_all.jsonl"


def load_chunk_texts() -> dict:
    texts = {}
    with open(CHUNKS, encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            texts[row["chunk_id"]] = row["text"]
    return texts


def fetch_rows(limit=None):
    stmt = (select(rag_runs.c.id, rag_runs.c.question, rag_runs.c.answer,
                   rag_runs.c.status, rag_runs.c.observation)
            .where(rag_runs.c.observation.isnot(None))
            .order_by(rag_runs.c.created_at))
    if limit:
        stmt = stmt.limit(limit)
    with get_session() as session:
        return session.execute(stmt).all()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--csv", default=None, help="행별 판정을 CSV 로 저장(수동 라벨링용)")
    args = ap.parse_args()

    chunk_texts = load_chunk_texts()
    rows = fetch_rows(args.limit)

    skipped = Counter()   # 소급 판정이 불가능한 행들 — 사유별 건수
    reasons = Counter()   # 프리체크 의심 사유 분포 — 정규화기 보강 지점이 여기서 나온다
    cell = Counter()      # 교차표: (precheck, luna)
    records = []          # CSV 용 행별 기록

    for run_id, question, answer, status, obs in rows:
        subs = (obs or {}).get("subs") or []
        if not subs:
            # 검색을 안 탄 경로(캐시 적중·가드레일 차단 등) — 검증 자체가 없어 실험 무관.
            # 조용히 버리면 "전체 N행"과 분석 건수의 차이를 설명할 수 없으니 세서 보고한다.
            skipped["하위답변 없음(캐시·가드레일 등 검색 미경유)"] += 1
            continue
        for sub in subs:
            # 1) 섀도 필드가 있으면 그대로 쓴다(finalize_sub 가 실제 생성 원문·실제 evidence 로
            #    판정한 값) — 다중 하위질문·civil·본문 교체 건까지 전부 표본이 된다.
            if sub.get("precheck") is not None:
                reason = sub["precheck"]
                missing = sub.get("precheck_missing") or []
                sub_q = sub.get("question") or question
            # 2) 섀도 필드 이전 로그는 소급 재구성 — 단일 하위질문·informational·본문 미교체·
            #    청크 생존 조건이 전부 맞아야 답변↔근거 대응이 성립한다.
            else:
                if len(subs) != 1:
                    skipped["구버전 로그: 다중 하위질문(합본이라 본문 분리 불가)"] += 1
                    continue
                if sub.get("intent") == "civil_petition":
                    skipped["구버전 로그: civil_petition(검증 evidence 재구성 불가)"] += 1
                    continue
                if sub.get("normalized"):
                    skipped["구버전 로그: 본문 교체됨(생성 원문 유실 — luna 문제 판정 건)"] += 1
                    continue
                if not answer or not str(answer).strip():
                    skipped["답변 없음"] += 1
                    continue
                if sub.get("marker") is None:
                    skipped["검증 미실행(marker None — 스위치 Off 또는 구버전 로그)"] += 1
                    continue
                top_ids = [t["chunk_id"] for t in (sub.get("top") or [])]
                if any(cid not in chunk_texts for cid in top_ids):
                    skipped["구버전 로그: 청크 유실(재수집으로 chunk_id 변경)"] += 1
                    continue
                evidence = "\n\n".join(chunk_texts[cid] for cid in top_ids)
                result = classify(answer, evidence, bool(sub["marker"]))
                reason, missing, sub_q = result.reason, result.missing, question

            if sub.get("marker") is None:
                skipped["검증 미실행(marker None — luna 판정 없어 교차표 불가)"] += 1
                continue
            reasons[reason] += 1
            # luna 의 문제 판정: 부적절 / 근거이탈 / 마커를 뒤집어 근거 미사용으로 확정
            luna_flagged = (sub.get("appropriate") is False
                            or sub.get("kind") == "ungrounded_claims"
                            or (sub["marker"] and sub.get("used_source") is False))
            cell[("clean" if reason == "clean" else "suspicious",
                  "flagged" if luna_flagged else "ok")] += 1
            records.append({
                "run_id": str(run_id), "question": sub_q,
                "precheck": reason, "missing_numbers": ";".join(missing),
                "marker": sub["marker"], "used_source": sub.get("used_source"),
                "kind": sub.get("kind"), "appropriate": sub.get("appropriate"),
                "luna_flagged": luna_flagged, "status": status,
            })

    analyzed = sum(cell.values())
    print(f"전체 {len(rows)}행 → 하위답변 기준 분석 {analyzed}건, 제외 {sum(skipped.values())}건")
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

    stars = [r for r in records if r["precheck"] == "clean" and r["luna_flagged"]]
    if stars:
        print(f"\n── ★ 놓침 후보 {len(stars)}건 — 근거 원문과 대조해 사람이 라벨링할 것 ──")
        for r in stars[:20]:
            print(f"  {r['run_id']}  kind={r['kind']} appropriate={r['appropriate']}  {r['question'][:60]}")

    if args.csv:
        with open(args.csv, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=list(records[0].keys()) if records else [])
            w.writeheader()
            w.writerows(records)
        print(f"\n행별 판정 {len(records)}건 저장: {args.csv}")


if __name__ == "__main__":
    main()
