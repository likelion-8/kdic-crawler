"""intent(정보성 informational / 민원성 civil_petition) 코사인 유사도 분류의
'진짜 정확도'를 데이터 누수(data leakage) 없이 검증한다.

배경: 운영 분류기(query_classifier.py)는 testset_all.jsonl의 in-scope 질문 전체를
'기준(참조 벡터)'으로 쓰고, 그 정확도도 같은 데이터로 재면 각 질문이 자기 자신을
최근접으로 골라 정확도가 허위로 부풀려진다(1-NN self-match leak).

이 스크립트는 두 가지를 한다:
  (진단) 운영 방식이 왜 부풀려지는지 구체 수치로 보여준다(1-NN self / leave-one-out).
  (검증) 요청대로 centroid 기반 분류기를 8:2 stratified 분리로 제대로 측정하고,
         비교용으로 '누수 있는' 전체-기준/전체-검증 버전도 같이 낸다.

읽기 전용 원칙:
  - retrieval.py에서 임베딩 모델(BGE-m3-ko)만 빌려 쓴다(수정 안 함).
  - 기존 dense_cache/*.npy 는 '겹침 확인용'으로만 읽는다(덮어쓰지 않음).
  - 새로 계산한 centroid는 data/intent_eval_centroids.npy 로만 저장한다.
  - 운영 분류 로직(query_classifier가 참조하는 파일)에는 아무 영향도 주지 않는다.

실행: python3 src/eval_intent_cosine.py
"""
import json
import random
import sys
from collections import Counter
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from retrieval import DEFAULT_DENSE_MODEL, DenseRetriever, _get_model  # noqa: E402

TESTSET = ROOT / "data" / "testset" / "testset_all.jsonl"
DENSE_CACHE = ROOT / "data" / "dense_cache"
OUT_CENTROIDS = ROOT / "data" / "intent_eval_centroids.npy"
OUT_RESULT = ROOT / "data" / "intent_cosine_eval_result.json"

SEED = 42
INTENTS = ["informational", "civil_petition"]  # 라벨 순서 고정


# ── 데이터 로드 ───────────────────────────────────────────────────────────────
def load_inscope():
    """운영 분류기와 동일하게 in-scope(expected_sources 있는) 질문만 쓴다.
    query_classifier.QuestionTypeClassifier가 `if d['expected_sources']`로 거르는 것과 일치."""
    rows = [json.loads(l) for l in open(TESTSET, encoding="utf-8") if l.strip()]
    inscope = [r for r in rows if r.get("expected_sources")]
    questions = [r["question"] for r in inscope]
    intents = [r["intent"] for r in inscope]
    assert all(i in INTENTS for i in intents), "예상 못한 intent 라벨 존재"
    return questions, intents


# ── 임베딩 / 분류 / 지표 ──────────────────────────────────────────────────────
def embed(model, texts):
    return np.asarray(model.encode(
        texts, normalize_embeddings=True, show_progress_bar=False, batch_size=8))


def make_centroids(vecs, labels):
    """클래스별 평균 벡터(centroid)를 만들고 단위벡터로 정규화(코사인=내적)."""
    cents = {}
    for lab in INTENTS:
        idx = [i for i, l in enumerate(labels) if l == lab]
        c = vecs[idx].mean(axis=0)
        cents[lab] = c / (np.linalg.norm(c) + 1e-12)
    return cents


def classify_by_centroid(qvecs, centroids):
    C = np.stack([centroids[l] for l in INTENTS])   # (2, d)
    pred_idx = (qvecs @ C.T).argmax(axis=1)          # 더 가까운 centroid
    return [INTENTS[i] for i in pred_idx]


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


def stratified_split(labels, ratio=0.8, seed=SEED):
    """클래스별로 따로 셔플·분할해 train/eval 클래스 비율을 원본과 동일하게 유지."""
    rng = random.Random(seed)
    train, ev = [], []
    for lab in INTENTS:
        idx = [i for i, l in enumerate(labels) if l == lab]
        rng.shuffle(idx)
        k = int(round(len(idx) * ratio))
        train += idx[:k]
        ev += idx[k:]
    return sorted(train), sorted(ev)


# ── 메인 ─────────────────────────────────────────────────────────────────────
def main():
    questions, intents = load_inscope()
    n = len(questions)
    dist = dict(Counter(intents))

    print("=" * 70)
    print("STEP 1 · 데이터 누수 진단 (운영 intent 분류기 방식)")
    print("=" * 70)
    print(f"in-scope 질문 수: {n}  (intent 분포: {dist})")
    # 운영 분류기의 '기준(참조 벡터)' = 바로 이 질문들. 검증도 같은 데이터면 100% 겹침.
    cache = DenseRetriever._cache_path(questions, DEFAULT_DENSE_MODEL)
    cached = cache.exists()
    print(f"운영 분류기 참조셋 = 이 in-scope 질문 전체 → 검증도 이걸로 하면 겹침 {n}/{n} = 100.0%")
    print(f"참조 임베딩 캐시 파일: {cache.name}  (dense_cache에 존재: {cached})")
    if cached:
        shp = np.load(cache).shape
        print(f"  └ 캐시 shape {shp} — 이 {shp[0]}개가 운영 분류기가 기준으로 쓰는 그 벡터들")

    print(f"\n임베딩 모델 로딩: {DEFAULT_DENSE_MODEL}")
    model = _get_model(DEFAULT_DENSE_MODEL)
    vecs = embed(model, questions)  # (n, d)  — 이번 실험 전용, dense_cache 안 건드림

    # 운영 방식(1-NN)의 누수를 구체적으로 시연
    S = vecs @ vecs.T
    self_pred = [intents[i] for i in S.argmax(axis=1)]         # 자기 자신 포함 → 자기가 1등
    nn_self_acc, _ = metrics(intents, self_pred)
    np.fill_diagonal(S, -1e9)                                   # 자기 자신 제외(leave-one-out)
    loo_pred = [intents[i] for i in S.argmax(axis=1)]
    nn_loo_acc, _ = metrics(intents, loo_pred)
    print(f"\n[운영 방식 1-NN] 자기참조 포함(완전 누수): {nn_self_acc*100:.1f}%  ← 자기 자신이 항상 1등이라 거의 100%")
    print(f"[운영 방식 1-NN] 자기 자신만 제외(LOO):     {nn_loo_acc*100:.1f}%  ← 누수 걷어낸 실제값")

    # === STEP 2: 8:2 stratified 분리 ===
    print("\n" + "=" * 70)
    print("STEP 2 · 8:2 Stratified 분리 (seed 고정)")
    print("=" * 70)
    tr_idx, ev_idx = stratified_split(intents, ratio=0.8, seed=SEED)
    tr_labels = [intents[i] for i in tr_idx]
    ev_labels = [intents[i] for i in ev_idx]
    print(f"train {len(tr_idx)}건 / eval {len(ev_idx)}건  (seed={SEED})")
    for name, labs in [("train", tr_labels), ("eval", ev_labels)]:
        c = Counter(labs)
        print(f"  {name}: " + ", ".join(f"{lab}={c.get(lab,0)}" for lab in INTENTS))

    # === STEP 3: centroid 분류기 (train으로만 centroid) ===
    tr_vecs = vecs[tr_idx]
    ev_vecs = vecs[ev_idx]
    centroids = make_centroids(tr_vecs, tr_labels)
    # 새 centroid는 별도 파일로만 저장 (dense_cache 절대 안 건드림)
    np.save(OUT_CENTROIDS, np.stack([centroids[l] for l in INTENTS]))

    # === STEP 4: eval 정확도 + 클래스별 지표 + 오분류 ===
    ev_pred = classify_by_centroid(ev_vecs, centroids)
    clean_acc, clean_per = metrics(ev_labels, ev_pred)
    ev_questions = [questions[i] for i in ev_idx]
    misclassified = [
        {"question": q, "true": t, "pred": p}
        for q, t, p in zip(ev_questions, ev_labels, ev_pred) if t != p
    ]

    print("\n" + "=" * 70)
    print("STEP 3~4 · centroid 분류기 (train centroid → eval 측정) [올바른 검증]")
    print("=" * 70)
    print(f"eval accuracy: {clean_acc*100:.2f}%  ({len(ev_idx)-len(misclassified)}/{len(ev_idx)})")
    for lab in INTENTS:
        m = clean_per[lab]
        print(f"  {lab:15} P={m['precision']:.3f}  R={m['recall']:.3f}  F1={m['f1']:.3f}  (n={m['support']})")
    print(f"오분류 {len(misclassified)}건:")
    for m in misclassified:
        print(f"  [실제 {m['true']} → 예측 {m['pred']}] {m['question'][:50]}")

    # === STEP 5: 누수 있는 centroid 베이스라인 (전체 기준 + 전체 검증) ===
    leak_centroids = make_centroids(vecs, intents)
    leak_pred = classify_by_centroid(vecs, leak_centroids)
    leak_acc, leak_per = metrics(intents, leak_pred)

    print("\n" + "=" * 70)
    print("STEP 5 · 누수 있는 centroid 베이스라인 (전체로 centroid+검증) [참고용]")
    print("=" * 70)
    print(f"accuracy: {leak_acc*100:.2f}%  ({int(round(leak_acc*n))}/{n})")

    # === 최종 요약 표 ===
    print("\n" + "=" * 70)
    print("최종 요약")
    print("=" * 70)
    print(f"{'측정 방식':40} {'정확도':>8}  비고")
    print("-" * 70)
    print(f"{'[운영]1-NN 자기참조(완전 누수)':40} {nn_self_acc*100:>7.1f}%  신뢰 불가(자기가 자기 정답)")
    print(f"{'centroid 누수 있음(전체 기준+검증)':40} {leak_acc*100:>7.1f}%  참고용, 신뢰 불가")
    print(f"{'centroid 8:2 분리(올바른 검증)':40} {clean_acc*100:>7.1f}%  실제 성능")
    print(f"{'[운영]1-NN LOO(참고)':40} {nn_loo_acc*100:>7.1f}%  운영 방식의 누수 제거 실측")

    # === 결과 저장 ===
    result = {
        "model": DEFAULT_DENSE_MODEL,
        "seed": SEED,
        "n_inscope": n,
        "intent_distribution": dist,
        "diagnosis_leak": {
            "reference_set_overlap": f"{n}/{n} = 100%",
            "reference_cache_file": cache.name,
            "reference_cache_exists": cached,
            "prod_1nn_selfmatch_acc": nn_self_acc,
            "prod_1nn_leaveoneout_acc": nn_loo_acc,
        },
        "split": {
            "train_n": len(tr_idx), "eval_n": len(ev_idx),
            "train_dist": dict(Counter(tr_labels)),
            "eval_dist": dict(Counter(ev_labels)),
        },
        "centroid_clean_8_2": {
            "accuracy": clean_acc, "per_class": clean_per,
            "n_misclassified": len(misclassified), "misclassified": misclassified,
        },
        "centroid_leaky_full": {"accuracy": leak_acc, "per_class": leak_per},
        "summary_table": [
            {"방식": "[운영]1-NN 자기참조(완전 누수)", "정확도": round(nn_self_acc, 4), "비고": "신뢰 불가"},
            {"방식": "centroid 누수 있음(전체 기준+검증)", "정확도": round(leak_acc, 4), "비고": "참고용, 신뢰 불가"},
            {"방식": "centroid 8:2 분리(올바른 검증)", "정확도": round(clean_acc, 4), "비고": "실제 성능"},
            {"방식": "[운영]1-NN LOO(참고)", "정확도": round(nn_loo_acc, 4), "비고": "운영 방식 누수 제거 실측"},
        ],
    }
    OUT_RESULT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n결과 저장: {OUT_RESULT.relative_to(ROOT)}")
    print(f"centroid 저장: {OUT_CENTROIDS.relative_to(ROOT)} (dense_cache 미변경)")


if __name__ == "__main__":
    main()
