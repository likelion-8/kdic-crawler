"""source_verifier 학습 — data/source_verifier/labels.jsonl로 로지스틱 회귀를 학습해
model.json(TF-IDF 어휘·가중치·임계값)을 만든다. sklearn은 학습 때만 쓰고 산출물은
JSON이라 추론 환경의 sklearn 버전과 무관하다. 저장 전에 source_verifier의 수식 구현이
sklearn 확률과 일치하는지 전 표본에서 assert로 검증한다(source_verifier.py 상단 주석).

labels.jsonl 형식: {"question", "src", "answer", "context", "label"}
  (label 1=근거 사용 → 출처 부착 / 0=미사용(거절·인사) → 생략)
실행: python3 src/train_source_verifier.py
"""
import json
import math
from pathlib import Path

import numpy as np
from scipy.sparse import csr_matrix, hstack
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import StratifiedKFold

import source_verifier
from query_classifier import tokenize_intent
from retrieval import DEFAULT_DENSE_MODEL, _encode_query, _get_model
from source_verifier import MODEL_PATH, _content_overlap

ROOT = Path(__file__).resolve().parent.parent
LABELS = ROOT / "data" / "source_verifier" / "labels.jsonl"
# 근거사용 전원 통과 임계값에 곱하는 안전 마진 — 학습 분포 밖 답변에서도 출처 누락(위험
# 축)이 나지 않도록 보수적으로 잡는다. 0.7~1.0 스윕 결과 근거사용 누락은 전 구간 1/61로
# 동일했고 미사용 차단만 25→29로 올라, 약간의 여유를 남긴 0.9를 택했다(차단 28/46).
MARGIN = 0.9


def build_features(rows):
    model = _get_model(DEFAULT_DENSE_MODEL)
    docs, overlap, cosine = [], [], []
    for r in rows:
        toks = tokenize_intent(r["answer"])
        docs.append(" ".join(toks))
        overlap.append(_content_overlap(toks, r["context"]))
        cosine.append(float(_encode_query(model, r["answer"]) @ _encode_query(model, r["context"])))
    return docs, np.array(overlap), np.array(cosine)


def pick_threshold(clf, X, y):
    prob = clf.predict_proba(X)[:, 1]
    cands = [t for t in sorted(set(np.round(prob, 3))) if (prob[y == 1] >= t).all()]
    return round(float(max(cands) if cands else 0.5) * MARGIN, 3)


def main():
    rows = [json.loads(l) for l in open(LABELS, encoding="utf-8")]
    print(f"{len(rows)}건 로드 (사용 {sum(r['label'] for r in rows)} / 미사용 {sum(1 - r['label'] for r in rows)})")
    docs, overlap, cosine = build_features(rows)
    y = np.array([r["label"] for r in rows])

    def assemble(vec, d, idx, fit=False):
        Xt = vec.fit_transform(d) if fit else vec.transform(d)
        return hstack([Xt, csr_matrix(np.column_stack([overlap[idx], cosine[idx]]))])

    # 5-fold CV — 위험 축(근거사용 누락)과 미관 축(미사용 차단)을 나눠 보고한다
    miss = blocked = tp = tn = 0
    for tr, te in StratifiedKFold(5, shuffle=True, random_state=42).split(docs, y):
        vec = TfidfVectorizer(token_pattern=r"\S+", min_df=2, lowercase=False)
        clf = LogisticRegression(class_weight="balanced", max_iter=2000).fit(
            assemble(vec, [docs[i] for i in tr], tr, fit=True), y[tr])
        thr = pick_threshold(clf, assemble(vec, [docs[i] for i in tr], tr), y[tr])
        pred = clf.predict_proba(assemble(vec, [docs[i] for i in te], te))[:, 1] >= thr
        tp += (y[te] == 1).sum(); tn += (y[te] == 0).sum()
        miss += (~pred[y[te] == 1]).sum(); blocked += (~pred[y[te] == 0]).sum()
    print(f"CV(5-fold) 근거사용 누락 {miss}/{tp} | 미사용 차단 {blocked}/{tn}")

    # 최종 모델은 전 데이터로 학습
    vec = TfidfVectorizer(token_pattern=r"\S+", min_df=2, lowercase=False)
    all_idx = np.arange(len(rows))
    X = assemble(vec, docs, all_idx, fit=True)
    clf = LogisticRegression(class_weight="balanced", max_iter=2000).fit(X, y)
    threshold = pick_threshold(clf, X, y)

    w = clf.coef_[0]
    n_vocab = len(vec.vocabulary_)
    vocab = {tok: [float(vec.idf_[i]), float(w[i])] for tok, i in vec.vocabulary_.items()}
    MODEL_PATH.write_text(json.dumps({
        "vocab": vocab,
        "w_overlap": float(w[n_vocab]),
        "w_cosine": float(w[n_vocab + 1]),
        "bias": float(clf.intercept_[0]),
        "threshold": threshold,
        "n_samples": len(rows),
    }, ensure_ascii=False), encoding="utf-8")

    # 수식 구현 검증 — source_verifier의 JSON 기반 점수가 sklearn 확률과 일치해야 저장 유효
    source_verifier._model_cache.clear()
    m = source_verifier._load_model()
    sk_prob = clf.predict_proba(X)[:, 1]
    for i, r in enumerate(rows):
        toks = tokenize_intent(r["answer"])
        z = (m["bias"] + source_verifier._tfidf_score(toks, m["vocab"])
             + m["w_overlap"] * overlap[i] + m["w_cosine"] * cosine[i])
        manual = 1.0 / (1.0 + math.exp(-z))
        assert abs(manual - sk_prob[i]) < 1e-6, f"수식 구현 불일치 row {i}: {manual} vs {sk_prob[i]}"
    print(f"수식 구현 == sklearn 검증 통과 ({len(rows)}건)")
    print(f"저장: {MODEL_PATH.relative_to(ROOT)} (vocab {n_vocab}개, threshold={threshold})")


if __name__ == "__main__":
    main()
