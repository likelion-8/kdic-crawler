"""플래너 비교형 분해 안정성 실측 — 온도 1 흔들림 확인용 반복 실행.

배경(2026-08-19): 비교형 질문("미수령금 수령과 착오송금 반환신청은 뭐가 다른가요?")이
실사용에서 분해 없이 단일 검색을 타 한쪽 근거만 걷혔고, 반쪽이 few-shot 유용(流用)
환각으로 채워지는 사례가 재현됐다. 플래너 모델(gpt-5.6-luna)이 temperature=0 을
거부해 온도 1로 돌므로 분해 판단이 롤마다 흔들린다 — 규칙 명시(1차 보강)만으로는
같은 날 오후 실사용에서 또 빠졌고, few-shot 예시(2차 보강)까지 넣었다.

측정: 비교형(반드시 분해) x N회 + 단일(분해 금지) x N회. 비교형에는 프롬프트 예시에
없는 질문을 섞는다 — 예시에 있는 질문만 재면 암기 확인이지 일반화 확인이 아니다.

⚠️ 문항당 OpenAI 1콜(플래너) x ROLLS. 기본 5회면 총 ~30콜.
실행: python src/eval/eval_planner_split.py [--rolls N]
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "src"))

from query_planner import plan_query  # noqa: E402

# (질문, 프롬프트 예시에 있는가) — 비교형: 전부 분해돼야 한다
COMPARISON = [
    ("미수령금 수령과 착오송금 반환신청은 뭐가 다른가요?", "예시有"),
    ("예금자보호제도와 착오송금 반환지원 제도는 뭐가 다른가요?", "예시無"),
    ("채무조정 신청과 파산 면책은 뭐가 다른가요?", "예시無"),
]
# 단일 요구: 분해되면 안 된다(false split 회귀 — 벤치마크 채택 근거가 false split 0%였다)
SINGLE = [
    "예금자보호제도가 뭐예요?",
    "착오송금 반환까지 얼마나 걸리나요?",
    "예금보험금 신청 방법을 알려주세요.",
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rolls", type=int, default=5)
    args = ap.parse_args()

    ok = True
    for q, tag in COMPARISON:
        splits = sum(plan_query(q)["should_split"] for _ in range(args.rolls))
        mark = "✓" if splits == args.rolls else "✗"
        ok &= splits == args.rolls
        print(f"{mark} 비교형 분해 {splits}/{args.rolls} [{tag}] {q[:40]}")
    for q in SINGLE:
        splits = sum(plan_query(q)["should_split"] for _ in range(args.rolls))
        mark = "✓" if splits == 0 else "✗"
        ok &= splits == 0
        print(f"{mark} 단일 오분해 {splits}/{args.rolls} (0이어야 함) {q[:40]}")
    print("\n판정:", "통과" if ok else "실패 — 프롬프트 재보강 필요")


if __name__ == "__main__":
    main()
