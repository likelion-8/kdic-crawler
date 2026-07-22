"""테스트셋 질문에 intent(informational/civil_petition) 라벨을 일괄 부여.

question_type/business_function처럼 사람이 직접 라벨링해야 하는 새 축이지만, 823건을
전부 손으로 검토하는 대신 규칙 기반 1차 라벨링을 하고 leave-one-out으로 정확도를
실측한다(question_type 분류기 때와 동일한 방식 — 규칙이 실제로 쓸만한지는 만들고 나서
재본다). 정확도가 낮으면 이 규칙을 다시 다듬거나 일부를 사람이 재검토해야 한다.

판단 기준:
  civil_petition = "절차 안내·서류 안내·페이지 연결"로 답해야 하는, 신청/접수/제출 등
  행정 절차를 실행하려는 질문. file_download·link_guide 유형은 서류/페이지를 묻는
  질문이라 사실상 전부 civil_petition으로 본다. 나머지(fact/faq/table_lookup)는
  절차 실행 관련 표현이 있을 때만 civil_petition — 금액·비율·정의 등 "사실"을 묻는
  질문(예: "포상금 몇 프로 줘요?")은 절차 표현이 있어도 informational에 가깝지만,
  이 스크립트는 표현 매칭만으로 1차 분류하므로 그런 경계 사례는 오분류될 수 있다.

실행: python3 src/project1_src/label_intent.py
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
TESTSET = ROOT / "data" / "testset" / "testset_all.jsonl"

# 절차 실행(신청/접수/제출 등)을 가리키는 표현 — 이게 있으면 civil_petition
PROCEDURE_MARKERS = [
    "신청", "접수", "제출", "구비서류", "필요서류", "신청서",
    "위임장", "대리인", "철회", "취소", "이의제기", "지급명령", "청구",
]


def infer_intent(question, question_type):
    if question_type in ("file_download", "link_guide"):
        return "civil_petition"
    if any(m in question for m in PROCEDURE_MARKERS):
        return "civil_petition"
    return "informational"


def main():
    rows = []
    with open(TESTSET, encoding="utf-8") as f:
        for line in f:
            rows.append(json.loads(line))

    # out_of_scope 포함 전체 행에 부여 — validate_testset.py가 필드 순서를 엄격히
    # 검사하므로(list(d.keys()) == KEYS), 일부 행만 필드가 빠지면 스키마가 깨진다.
    counts = {"informational": 0, "civil_petition": 0}
    for d in rows:
        intent = infer_intent(d["question"], d["question_type"])
        d["intent"] = intent
        counts[intent] += 1

    with open(TESTSET, "w", encoding="utf-8") as f:
        for d in rows:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")

    print(f"라벨링 완료: {counts}")


if __name__ == "__main__":
    main()
