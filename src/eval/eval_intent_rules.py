"""intent 분류 — 규칙 기반(정규표현식) 방법. Leave-Page-Out으로 평가.

민원 처리(civil_petition) 신호가 되는 표현을 정규식으로 잡아, 하나라도 걸리면
civil_petition, 아니면 informational로 분류한다. 페이지 단위 분리(같은 페이지 형제
질문이 train/eval에 섞이지 않게)로 평가해, eval_intent_sibling.py에서 확인한 형제
누수를 여기서도 방지한다.

⚠️ 주의: intent 원본 라벨 자체가 규칙 기반(label_intent.py)으로 만들어졌을 수 있어,
규칙 기반 분류가 높게 나와도 "실제 의도 파악을 잘한다"기보다 "라벨링 규칙을 흉내냈다"에
가까울 수 있다. 결과 해석 시 이 순환성을 감안할 것.

읽기 전용: 기존 파일 수정/‌git 실행 없음. 결과는 data/intent_rules_result.json.
실행: python3 src/eval/eval_intent_rules.py
"""
import json
import re
import random
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
TESTSET = ROOT / "data" / "testset" / "testset_all.jsonl"
OUT_RESULT = ROOT / "data" / "intent_rules_result.json"
SEED = 42
INTENTS = ["informational", "civil_petition"]

# 민원 처리(신청/접수/제출 등 절차 실행) 신호 패턴. 하나라도 걸리면 civil_petition.
CIVIL_PATTERNS = [
    r"하려면", r"하고\s*싶", r"해야\s*(하나요|되나요|하나요|되나|하나)",
    r"받으려면", r"신청", r"접수", r"제출", r"구비\s*서류", r"필요한.{0,6}서류",
    r"위임장", r"다운로드", r"발급", r"환급", r"철회", r"취소",
    r"이의\s*제기", r"청구", r"지급명령", r"어떻게\s*하",
]
_CIVIL_RE = [re.compile(p) for p in CIVIL_PATTERNS]


def predict(question):
    return "civil_petition" if any(r.search(question) for r in _CIVIL_RE) else "informational"


def load_inscope():
    rows = [json.loads(l) for l in open(TESTSET, encoding="utf-8") if l.strip()]
    inscope = [r for r in rows if r.get("expected_sources")]
    return inscope


def page_split(inscope, ratio=0.8, seed=SEED):
    """페이지(page_id=expected_sources[0]) 단위로 train/eval 분리. 같은 페이지 질문은
    통째로 한쪽에만. eval_intent_sibling.py의 '형제=같은 페이지' 기준과 동일하게 맞춤."""
    pages = sorted({r["expected_sources"][0] for r in inscope})
    rng = random.Random(seed)
    shuf = pages[:]
    rng.shuffle(shuf)
    k = int(round(len(shuf) * ratio))
    train_pages = set(shuf[:k])
    train = [r for r in inscope if r["expected_sources"][0] in train_pages]
    ev = [r for r in inscope if r["expected_sources"][0] not in train_pages]
    return train, ev


def metrics(y_true, y_pred):
    acc = sum(t == p for t, p in zip(y_true, y_pred)) / len(y_true)
    per = {}
    for lab in INTENTS:
        tp = sum(1 for t, p in zip(y_true, y_pred) if t == lab and p == lab)
        fp = sum(1 for t, p in zip(y_true, y_pred) if t != lab and p == lab)
        fn = sum(1 for t, p in zip(y_true, y_pred) if t == lab and p != lab)
        prec = tp / (tp + fp) if (tp + fp) else 0.0
        rec = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
        per[lab] = {"precision": round(prec, 4), "recall": round(rec, 4),
                    "f1": round(f1, 4), "support": tp + fn}
    return round(acc, 4), per


def main():
    inscope = load_inscope()
    train, ev = page_split(inscope)
    print(f"페이지 단위 분리(seed={SEED}): train {len(train)}건 / eval {len(ev)}건")
    print(f"  eval intent 분포: {dict(Counter(r['intent'] for r in ev))}")

    # 규칙은 학습이 없으므로 eval에 바로 적용(train/eval 비교용으로 동일 eval셋 사용)
    ev_q = [r["question"] for r in ev]
    ev_true = [r["intent"] for r in ev]
    ev_pred = [predict(q) for q in ev_q]
    acc, per = metrics(ev_true, ev_pred)

    misclassified = [{"question": q, "true": t, "pred": p}
                     for q, t, p in zip(ev_q, ev_true, ev_pred) if t != p]

    print("\n" + "=" * 62)
    print("규칙 기반 — eval(held-out 페이지) 정확도")
    print("=" * 62)
    print(f"정확도: {acc*100:.1f}%  ({len(ev)-len(misclassified)}/{len(ev)})")
    for lab in INTENTS:
        m = per[lab]
        print(f"  {lab:15} P={m['precision']:.3f} R={m['recall']:.3f} F1={m['f1']:.3f} (n={m['support']})")

    # 참고: 전체 821건에 적용한 안정적 추정치(규칙은 train 불필요라 전체 평가 가능)
    all_q = [r["question"] for r in inscope]
    all_true = [r["intent"] for r in inscope]
    all_pred = [predict(q) for q in all_q]
    all_acc, _ = metrics(all_true, all_pred)
    print(f"\n(참고) 전체 821건 적용 정확도: {all_acc*100:.1f}%")

    print(f"\n오분류 {len(misclassified)}건 (eval):")
    for m in misclassified[:25]:
        print(f"  [실제 {m['true']} → 예측 {m['pred']}] {m['question'][:48]}")
    if len(misclassified) > 25:
        print(f"  ... 외 {len(misclassified)-25}건 (json에 전체 저장)")

    OUT_RESULT.write_text(json.dumps({
        "method": "rule_based_regex",
        "seed": SEED,
        "eval_n": len(ev),
        "eval_acc_leave_page_out": acc,
        "eval_per_class": per,
        "all821_acc": all_acc,
        "patterns": CIVIL_PATTERNS,
        "misclassified": misclassified,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n결과 저장: {OUT_RESULT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
