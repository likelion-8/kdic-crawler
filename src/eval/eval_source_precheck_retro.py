"""프리체크 소급 실험 — rag_runs 로그에 source_precheck 를 돌려 "켰다면 어땠을지"를 잰다.

지금 운영은 모든 답변에 validate_answer(luna) 1콜을 부르고 판정을 observation 에 남기므로,
프리체크를 실제로 켜지 않고도 교차표를 완전하게 만들 수 있다 — 추가 LLM 콜 0, 위험 0.

                     │ luna: 정상        │ luna: 문제 판정
    프리체크: 깨끗함  │ 스킵해도 됐던 건  │ ★ 놓침 후보 — 이 칸이 실험의 본체
    프리체크: 의심    │ (동작 변화 없음)  │ (동작 변화 없음)

★ 칸의 건은 사람이 근거 원문과 대조해 라벨링해야 한다(--csv 로 뽑아서) — luna 도
경계 문항에서 흔들리므로(api/rag/answer.py 재생성 주석) luna 판정 자체가 정답지가 아니다.
"진짜 놓침"이면 프리체크 조건 보강, "luna 오판"이면 오히려 프리체크가 막아줄 사고다.

## 소급으로 잴 수 없는 것 (한계 — 건수는 세서 보고한다)

- 다중 하위질문 답변: rag_runs.answer 는 합본이라 하위 답변별 본문을 못 가른다 → 제외
- civil_petition: 검증 evidence 가 절차 안내문(civil_petition.py 조립)이라 로그의
  chunk_id 로 재구성 불가 → 제외
- 본문 교체 건(normalized=True): 저장된 answer 는 교체 후 문구라 생성 원문이 유실 → 제외
  (이 건들은 luna 가 문제로 판정한 건들이므로, 별도 건수로 보고해 놓침 상한 해석에 쓴다)
- 근거 evidence 는 observation.top 의 chunk_id 를 data/chunks_all.jsonl 에서 되찾아
  조립한다. 청크가 재수집으로 갈렸으면(chunk_id 부재) 그 행은 제외하고 건수만 센다.
  observation.top 은 TOP_N=5 = K_FINAL 이라 생성 때 프롬프트에 든 근거와 같은 범위다.

읽기 전용: rag_runs 를 SELECT 만 한다. 기존 파일 수정/git 실행 없음.
실행: python src/eval/eval_source_precheck_retro.py [--limit N] [--csv out.csv]
"""
import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "src"))

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
        if len(subs) != 1:
            skipped["다중 하위질문(합본이라 본문 분리 불가)"] += 1
            continue
        sub = subs[0]
        if sub.get("marker") is None:
            skipped["검증 미실행(marker None — 스위치 Off 또는 구버전 로그)"] += 1
            continue
        if sub.get("intent") == "civil_petition":
            skipped["civil_petition(검증 evidence 재구성 불가)"] += 1
            continue
        if sub.get("normalized"):
            skipped["본문 교체됨(생성 원문 유실 — luna 문제 판정 건)"] += 1
            continue
        if not answer or not str(answer).strip():
            skipped["답변 없음"] += 1
            continue
        top_ids = [t["chunk_id"] for t in (sub.get("top") or [])]
        missing_chunks = [cid for cid in top_ids if cid not in chunk_texts]
        if missing_chunks:
            skipped["청크 유실(재수집으로 chunk_id 변경)"] += 1
            continue
        evidence = "\n\n".join(chunk_texts[cid] for cid in top_ids)

        result = classify(answer, evidence, bool(sub["marker"]))
        reasons[result.reason] += 1
        # luna 의 문제 판정: 부적절 / 근거이탈 / 마커를 뒤집어 근거 미사용으로 확정
        luna_flagged = (sub.get("appropriate") is False
                        or sub.get("kind") == "ungrounded_claims"
                        or (sub["marker"] and sub.get("used_source") is False))
        cell[("clean" if result.clean else "suspicious",
              "flagged" if luna_flagged else "ok")] += 1
        records.append({
            "run_id": str(run_id), "question": question,
            "precheck": result.reason, "missing_numbers": ";".join(result.missing),
            "marker": sub["marker"], "used_source": sub.get("used_source"),
            "kind": sub.get("kind"), "appropriate": sub.get("appropriate"),
            "luna_flagged": luna_flagged, "status": status,
        })

    analyzed = sum(cell.values())
    print(f"전체 {len(rows)}행 중 분석 {analyzed}건, 제외 {sum(skipped.values())}건")
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
