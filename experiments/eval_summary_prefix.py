"""요약 프리펜드 파일럿 — LLM 페이지 요약을 프리픽스에 붙이면 검색 구멍이 메워지는가.

## 배경 (2026-08-19)

"반환지원 대상이 아닌 경우는 어떤 경우인가요?"(추천 칩)의 본편 답 페이지가 검색 17위
(kmrs_aply_trgt — 신청대상·한도·제외 안내)로 밀리고 top5 는 FAQ 부록("그 외에도…")뿐인
검색 구멍이 실측됐다(팀원 제보 → 순위표 확인). 원인: 본문이 금액 얘기 위주라 질문 어휘
("대상이 아닌")와 접점이 약함 — 제목 프리픽스만으로 부족. 처방 가설: 페이지가 **어떤
질문에 답할 수 있는지**를 담은 LLM 요약을 프리픽스 뒤에 붙여 임베딩 어휘를 보강한다
(원조 contextual retrieval — 지금까지는 검색 만점이라 안 썼으나, 만점이 아닌 구멍이
확인돼 도입 근거가 생김).

## 방법

1) --generate: 파일럿 범위(착오송금 반환 신청 업무 페이지)만 luna 1콜/페이지로 요약 생성
   → results/page_summaries_pilot.json 저장(사람 검수용 출력 포함). 요약은 현재 코퍼스
   원문 기준 — 재수집으로 원문이 바뀌면 재생성해야 한다(파일에 원문 해시 동봉).
2) 기본 실행: 메모리 Dense 인덱스 2벌(현행 vs 요약 부착) A/B — 운영 무접촉, 로컬 임베딩
   (dense_cache 적중분 제외 신규 인코딩만). 라우팅이 Dense 통일이므로 Dense 만 잰다.
   - 본 지표: 표적 질문들에서 본편 페이지(kmrs_aply_trgt 등)의 순위 변화
   - 가드: testset_retrieval_eval_v1 66문항 페이지 단위 R@5/R@20/MRR 비악화
     (프리픽스 실험의 '희석 시 즉시 기각' 기준 재사용)

실행: python experiments/eval_summary_prefix.py --generate   (luna ~페이지 수만큼 콜)
      python experiments/eval_summary_prefix.py              (A/B — LLM 콜 0)
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent   # experiments/ -> 리포 루트
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "src" / "crawler"))

from chunking import build_units, load_records  # noqa: E402
from retrieval import DenseRetriever, PageRanked  # noqa: E402

PILOT_BF = "착오송금 반환 신청"
SUMMARIES = ROOT / "results" / "page_summaries_pilot.json"
TESTSET = ROOT / "data" / "testset" / "testset_retrieval_eval_v1.jsonl"

# 표적 질문 — 실측된 검색 구멍(17·18위) + 같은 의도의 자연 변형들
TARGETS = [
    ("반환지원 대상이 아닌 경우는 어떤 경우인가요?", ["kmrs_aply_trgt", "sender_qlfc_check"]),
    ("착오송금 반환지원 못 받는 경우도 있나요?", ["kmrs_aply_trgt", "sender_qlfc_check"]),
    ("어떤 착오송금이 반환지원 신청 대상인가요?", ["kmrs_aply_trgt"]),
]

SUMMARY_SYSTEM = """당신은 검색 색인용 페이지 요약기입니다. 예금보험공사 안내 페이지 원문을 받아, 이 페이지가 **어떤 질문에 답할 수 있는지**를 1~2문장으로 요약합니다.

- 원문에 실제로 있는 내용만 씁니다. 원문에 없는 제도·조건·수치를 추가하지 않습니다.
- 사용자가 물을 법한 표현(대상/제외/한도/방법/기간/불가능한 경우 등)을 원문 근거 위에서 명시합니다 — 이 요약은 사람이 아니라 검색 임베딩이 읽습니다.
- 수치·기한은 원문에 있으면 포함해도 되지만 바꾸면 안 됩니다."""


def _page_hash(text):
    return hashlib.sha256(text.encode()).hexdigest()[:12]


def generate():
    from openai import OpenAI
    from pydantic import BaseModel, Field

    class PageSummary(BaseModel):
        summary: str = Field(description="이 페이지가 답할 수 있는 질문 주제 요약(1~2문장)")

    import os
    client = OpenAI()
    model = os.environ["OPENAI_PLANNER_MODEL"]
    out = {}
    pages = [d for d in load_records() if d["business_function"] == PILOT_BF]
    print(f"파일럿 대상: {PILOT_BF} — {len(pages)}페이지")
    for d in pages:
        msgs = [{"role": "system", "content": SUMMARY_SYSTEM},
                {"role": "user", "content": f"페이지 제목: {d['page_title']}\n\n원문:\n{d['text'][:4000]}"}]
        r = client.beta.chat.completions.parse(model=model, messages=msgs, response_format=PageSummary)
        s = r.choices[0].message.parsed.summary.strip()
        out[d["page_id"]] = {"summary": s, "source_hash": _page_hash(d["text"])}
        print(f"\n[{d['page_id']}] {d['page_title']}\n  → {s}")
    SUMMARIES.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n저장: {SUMMARIES} ({len(out)}페이지) — 내용 검수 후 A/B 를 돌리세요.")


def with_summaries(uids, texts, u2p, summaries):
    """'[제목 · 업무] ' 프리픽스 바로 뒤에 요약을 끼운다. 요약 없는 페이지는 그대로."""
    out = []
    for uid, t in zip(uids, texts):
        s = summaries.get(u2p[uid])
        if s and t.startswith("["):
            cut = t.index("] ") + 2
            out.append(t[:cut] + s["summary"] + "\n" + t[cut:])
        else:
            out.append(t)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--generate", action="store_true")
    args = ap.parse_args()
    if args.generate:
        generate()
        return

    summaries = json.loads(SUMMARIES.read_text(encoding="utf-8"))
    # 원문 변경 감지 — 요약이 옛 원문 기준이면 결과가 오염되므로 중단
    cur = {d["page_id"]: _page_hash(d["text"]) for d in load_records()}
    stale = [p for p, v in summaries.items() if cur.get(p) != v["source_hash"]]
    assert not stale, f"원문이 바뀐 페이지 — 요약 재생성 필요: {stale}"

    uids, texts, u2p = build_units("all")
    stexts = with_summaries(uids, texts, u2p, summaries)
    changed = sum(1 for a, b in zip(texts, stexts) if a != b)
    print(f"유닛 {len(uids)}개 중 요약 부착 {changed}개")

    print("[1/2] 현행 인덱스...", flush=True)
    base_unit = DenseRetriever(uids, texts)
    base_page = PageRanked(base_unit, u2p)
    print("[2/2] 요약 인덱스(변경분만 신규 인코딩)...", flush=True)
    summ_unit = DenseRetriever(uids, stexts)
    summ_page = PageRanked(summ_unit, u2p)

    print("\n── 표적 질문: 본편 페이지 순위 (페이지 단위, 현행 → 요약) ──")
    for q, expected in TARGETS:
        line = [q[:34]]
        for name, retr in (("현행", base_page), ("요약", summ_page)):
            ranking = retr.search(q, 20)
            ranks = {pid: i + 1 for i, (pid, _s) in enumerate(ranking)}
            line.append(f"{name}: " + " ".join(f"{e}={ranks.get(e, '20+')}" for e in expected))
        print("  " + " | ".join(line))

    # ── 가드: 테스트셋 66문항 Dense 페이지 단위 ──
    rows = [json.loads(l) for l in open(TESTSET, encoding="utf-8")]

    def metrics(retr):
        n, hit5, hit20, mrr = len(rows), 0, 0, 0.0
        for r in rows:
            ranking = retr.search(r["question"], 20)
            exp = set(r["expected_sources"])
            rank = next((i + 1 for i, (pid, _s) in enumerate(ranking) if pid in exp), None)
            if rank:
                hit20 += 1
                mrr += 1.0 / rank
                if rank <= 5:
                    hit5 += 1
        return hit5 / n, hit20 / n, mrr / n

    b5, b20, bm = metrics(base_page)
    s5, s20, sm = metrics(summ_page)
    print("\n── 가드: 테스트셋 66문항 (Dense) ──")
    print(f"  현행: R@5 {b5:.4f} · R@20 {b20:.4f} · MRR {bm:.4f}")
    print(f"  요약: R@5 {s5:.4f} · R@20 {s20:.4f} · MRR {sm:.4f}")
    print("  판정:", "가드 통과" if (s5 >= b5 and s20 >= b20) else "⚠️ 악화 — 희석 검토(기각 기준)")


if __name__ == "__main__":
    main()
