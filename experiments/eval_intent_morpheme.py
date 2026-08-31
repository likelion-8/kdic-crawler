"""intent 분류 — 형태소(Kiwi) + TF-IDF + LogisticRegression. Leave-Page-Out으로 평가.

질문을 Kiwi로 형태소+품사 태그 단위("신청/NNG", "하/VV", "어요/EF")로 토큰화하고,
TF-IDF로 벡터화한 뒤 LogisticRegression으로 intent(정보성/민원성)를 분류한다.
어미(EF)·연결어미(EC) 같은 문법 형태소가 '문의 vs 실행' 의도를 가르는지 특징 기여도로 본다.

기존 BM25 파이프라인의 Kiwi 토크나이저 '로직'만 재사용한다(bm25_cache 파일은 안 건드림).
페이지 단위 분리(형제 질문이 train/eval에 안 섞이게)로 형제 누수를 방지한다.

읽기 전용: 기존 파일 수정/git 실행 없음. 결과는 results/intent_eval/intent_morpheme_result.json.
실행: python3 experiments/eval_intent_morpheme.py
"""
import json
import random
from collections import Counter
import sys
from pathlib import Path

import numpy as np
from kiwipiepy import Kiwi
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.naive_bayes import MultinomialNB

ROOT = Path(__file__).resolve().parent.parent   # experiments/ -> 리포 루트
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "src" / "crawler"))
TESTSET = ROOT / "data" / "testset" / "testset_all.jsonl"
OUT_RESULT = ROOT / "results" / "intent_eval" / "intent_morpheme_result.json"
SEED = 42
INTENTS = ["informational", "civil_petition"]  # index 0, 1 (1=민원성=양성)

_kiwi = Kiwi()


def tokenize(text):
    """형태소+품사 태그 토큰. BM25의 _tok(form만)와 달리 태그를 붙여 어미까지 특징으로 살린다."""
    return [f"{t.form}/{t.tag}" for t in _kiwi.tokenize(text)]


def load_inscope():
    rows = [json.loads(l) for l in open(TESTSET, encoding="utf-8") if l.strip()]
    return [r for r in rows if r.get("expected_sources")]


def page_split(inscope, ratio=0.8, seed=SEED):
    """eval_intent_rules.py와 동일한 seed·로직 → 완전히 같은 train/eval 분리."""
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
    acc = float(np.mean([t == p for t, p in zip(y_true, y_pred)]))
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

    tr_q = [r["question"] for r in train]
    ev_q = [r["question"] for r in ev]
    tr_y = [r["intent"] for r in train]
    ev_y = [r["intent"] for r in ev]

    print("Kiwi 형태소 토큰화 + TF-IDF 벡터화 중…")
    vec = TfidfVectorizer(tokenizer=tokenize, token_pattern=None,
                          lowercase=False, min_df=2)
    Xtr = vec.fit_transform(tr_q)
    Xev = vec.transform(ev_q)
    print(f"  특징(형태소 토큰) 수: {len(vec.get_feature_names_out())}")

    results = {}
    # 클래스 불균형(정보성 ~2.7:1)이라 balanced 가중치 사용
    for name, clf in [
        ("LogReg", LogisticRegression(max_iter=1000, class_weight="balanced")),
        ("MultinomialNB", MultinomialNB()),
    ]:
        clf.fit(Xtr, tr_y)
        pred = clf.predict(Xev)
        acc, per = metrics(ev_y, pred)
        results[name] = {"acc": acc, "per_class": per,
                         "misclassified": [{"question": q, "true": t, "pred": p}
                                           for q, t, p in zip(ev_q, ev_y, pred) if t != p]}
        print(f"\n[{name}] eval 정확도: {acc*100:.1f}%")
        for lab in INTENTS:
            m = per[lab]
            print(f"  {lab:15} P={m['precision']:.3f} R={m['recall']:.3f} F1={m['f1']:.3f} (n={m['support']})")

    # 특징 기여도 — LogReg 계수(양수=민원성 쪽, 음수=정보성 쪽)
    logreg = LogisticRegression(max_iter=1000, class_weight="balanced").fit(Xtr, tr_y)
    feats = np.array(vec.get_feature_names_out())
    coef = logreg.coef_[0]  # 클래스 순서는 logreg.classes_ 기준
    pos_class = logreg.classes_[1]  # 보통 'informational'(알파벳순) → 부호 해석 주의
    order = np.argsort(coef)
    top_civil_idx = order[::-1][:15] if pos_class == "civil_petition" else order[:15]
    top_info_idx = order[:15] if pos_class == "civil_petition" else order[::-1][:15]

    def fmt(idx):
        return [(feats[i], round(float(coef[i]), 3)) for i in idx]

    top_civil = fmt(top_civil_idx)
    top_info = fmt(top_info_idx)
    print(f"\n(LogReg classes_={list(logreg.classes_)}, 양성 index1={pos_class})")
    print("\n민원성(civil_petition) 쪽으로 미는 상위 형태소:")
    for f, w in top_civil:
        tag = f.split("/")[-1]
        mark = "  ← 어미/연결어미" if tag in ("EF", "EC") else ""
        print(f"  {f:18} {w:+.3f}{mark}")
    print("\n정보성(informational) 쪽으로 미는 상위 형태소:")
    for f, w in top_info:
        tag = f.split("/")[-1]
        mark = "  ← 어미/연결어미" if tag in ("EF", "EC") else ""
        print(f"  {f:18} {w:+.3f}{mark}")

    best = max(results, key=lambda k: results[k]["acc"])
    print(f"\n최고: {best} {results[best]['acc']*100:.1f}%")

    OUT_RESULT.write_text(json.dumps({
        "method": "morpheme_tfidf",
        "seed": SEED,
        "eval_n": len(ev),
        "n_features": len(feats),
        "classifiers": {k: {"acc": v["acc"], "per_class": v["per_class"],
                            "n_misclassified": len(v["misclassified"])}
                        for k, v in results.items()},
        "best": {"name": best, "acc": results[best]["acc"]},
        "top_features_civil": top_civil,
        "top_features_info": top_info,
        "misclassified_best": results[best]["misclassified"],
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n결과 저장: {OUT_RESULT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
