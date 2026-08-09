"""RAG 파이프라인 성능 baseline 측정 — rag_answer()의 단계별 소요 시간을 재서
docs/pipeline_latency_profile.md에 표로 남긴다. 어느 단계가 병목인지 확인하기 위한
일회성 진단 스크립트(반복/통계 집계는 하지 않음 - 병목이 애매하면 그때 추가).

⚠️ 그 문서는 이 스크립트의 출력물이다 — write_text()로 통째로 덮어쓰므로 손으로 편집한
내용은 재생성되지 않는다. 문서에 설명을 넣으려면 아래 lines 리스트를 고칠 것.
지금 커밋된 문서는 리랭킹이 조건 없이 항상 돌던 2026-07-23 측정본이고(USE_RERANKER 플래그는
같은 날 11:11 ae69751에서 그 뒤에 생겼다), 측정 맥락을 나중에 손으로 덧붙인 상태라 이 스크립트가
그대로 재현하지 못한다. 여러 문서가 그 수치를 인용하므로 main()이 파일이 이미 있으면 멈춘다.

대표 질문 4개(정보성/민원성/표조회/근거부족)는 새로 짓지 않고 data/testset/testset_all.jsonl에서
실제 라벨이 확인된 문항을 test_id로 그대로 가져온다.

실행: python3 src/crawler/measure_baseline.py (첫 실행 시 임베딩/재정렬 모델 로딩 포함,
이 로딩 시간은 "웜업" 실행으로 따로 표시하고 실제 비교는 웜업 이후 실행 기준으로 한다)
"""
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "src"))

from pipeline import (  # noqa: E402
    K_CANDIDATES, K_FINAL, USE_RERANKER, _rag_answer_traced,
)

TESTSET = ROOT / "data" / "testset" / "testset_all.jsonl"
DOC_PATH = ROOT / "docs" / "pipeline_latency_profile.md"

# (test_id, 표시용 유형 라벨) — testset_all.jsonl에서 실제 라벨 확인된 대표 질문
REPRESENTATIVE = [
    ("ms_poss_dcmnt_q4", "정보성"),
    ("ms_poss_dcmnt_q3", "민원성"),
    ("ms_trgt_fnst_q2", "표 조회"),
    ("ha_ilgl_intro_q3", "근거 부족(범위 밖)"),
]

STAGES = [
    "query_classification", "retrieval", "reranking",
    "context_building", "prompt_building", "llm_call", "total",
]


def load_questions():
    by_id = {}
    with open(TESTSET, encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            by_id[d["test_id"]] = d["question"]
    return [(test_id, label, by_id[test_id]) for test_id, label in REPRESENTATIVE]


def format_row(label, question, timings):
    cells = [label, question] + [f"{timings.get(s, 0):.2f}" for s in STAGES]
    return "| " + " | ".join(cells) + " |"


def main():
    # ponytail: 존재하면 멈추는 가드 한 줄. 커밋된 문서는 손으로 맥락을 덧붙인 2026-07-23
    # 기록이고 retrospective.md·candidate_ranking.py 등이 그 수치를 인용한다. 측정에 몇 분이
    # 걸리므로 LLM 호출 전에 판정한다. 새로 재려면 이 파일을 옮기거나 지우고 돌려라.
    if DOC_PATH.exists():
        raise SystemExit(f"{DOC_PATH} 가 이미 있다 — 덮어쓰지 않는다. 새로 측정하려면 옮기거나 지울 것.")

    questions = load_questions()

    print(f"웜업 실행(모델 로딩 포함): {questions[0][2]}")
    _, warmup_timings, _ = _rag_answer_traced(questions[0][2])
    print(f"  total: {warmup_timings['total']:.2f}s\n")

    rows = []
    for test_id, label, question in questions:
        answer, timings, _ = _rag_answer_traced(question)
        print(f"[{label}] {question}")
        print(f"  timings: {timings}")
        rows.append((label, question, timings))

    header = ["유형", "질문"] + STAGES
    lines = [
        "# RAG 파이프라인 성능 baseline",
        "",
        "> ⚠️ **이 파일은 `src/crawler/measure_baseline.py`가 생성한다 — 직접 편집하지 마라.**",
        "> 스크립트를 다시 돌리면 `write_text()`가 통째로 덮어써서 손으로 넣은 내용이 사라진다.",
        "> 설명을 덧붙이려면 문서가 아니라 생성 스크립트를 고칠 것.",
        "",
        f"측정일: {date.today().isoformat()}",
        "",
        "## 측정 시점 설정",
        "",
        f"- USE_RERANKER: {USE_RERANKER}",
        f"- retrieval_top_n (1차 후보): {K_CANDIDATES}",
        f"- final_top_k (재정렬 후 최종): {K_FINAL}",
        "- reranker_model: BAAI/bge-reranker-v2-m3"
        + ("" if USE_RERANKER else " (USE_RERANKER=False — 이번 측정에서는 호출되지 않았다)"),
        "- embedding_model: dragonkue/BGE-m3-ko",
        "- llm_model: HCX-DASH-002 (HyperCLOVA X, via langchain-naver ChatClovaX)",
        "- few_shot: 3건 고정(testset_all.jsonl reference_answer 발췌, prompt_builder.py)",
        "",
        f"## 웜업 실행 (모델/인덱스 최초 로딩 포함, 참고용 - 비교 대상 아님)",
        "",
        f"- 질문: {questions[0][2]}",
        f"- total: {warmup_timings['total']:.2f}s",
        "",
        "## 대표 질문별 단계 시간 (웜업 이후, 단위: 초)",
        "",
        "| " + " | ".join(header) + " |",
        "|" + "---|" * len(header),
    ]
    for label, question, timings in rows:
        lines.append(format_row(label, question, timings))

    slowest = max(STAGES[:-1], key=lambda s: sum(r[2][s] for r in rows))
    lines += [
        "",
        f"## 병목 확인",
        "",
        f"가장 느린 단계(4개 질문 합산 기준): **{slowest}**",
    ]

    DOC_PATH.parent.mkdir(parents=True, exist_ok=True)
    DOC_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\n결과 저장: {DOC_PATH}")


if __name__ == "__main__":
    main()
