"""intent 1-NN 분류의 '형제 효과' 진단 — 88.8%(LOO)가 비슷한 형제 질문 덕에
부풀려진 건 아닌지 확인한다.

방법:
  - in-scope 질문 821개를 임베딩, 각 질문의 leave-one-out 최근접(자기 제외)을 찾는다.
  - 그 최근접이 '같은 페이지(page_id)에서 나온 형제 질문'인지 본다.
  - 최근접이 형제인 경우 vs 아닌 경우로 나눠 1-NN intent 정확도를 각각 잰다.
  - 추가로 leave-page-out(같은 페이지 형제 전부 제외) 정확도까지 재서,
    형제를 못 보게 하면 정확도가 얼마나 떨어지는지 확인한다.

읽기 전용: retrieval에서 모델만 빌려 씀. dense_cache/운영 로직 안 건드림.
실행: python3 experiments/eval_intent_sibling.py
"""
import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent   # experiments/ -> 리포 루트
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "src" / "crawler"))
from retrieval import DEFAULT_DENSE_MODEL, _get_model  # noqa: E402

TESTSET = ROOT / "data" / "testset" / "testset_all.jsonl"
OUT_RESULT = ROOT / "data" / "intent_sibling_result.json"
INTENTS = ["informational", "civil_petition"]


def load_inscope():
    rows = [json.loads(l) for l in open(TESTSET, encoding="utf-8") if l.strip()]
    inscope = [r for r in rows if r.get("expected_sources")]
    q = [r["question"] for r in inscope]
    intents = [r["intent"] for r in inscope]
    # page_id: expected_sources 첫 항목(정답 페이지). 형제 판정 기준.
    pages = [r["expected_sources"][0] for r in inscope]
    return q, intents, pages


def main():
    q, intents, pages = load_inscope()
    n = len(q)
    print(f"in-scope 질문 {n}개 · 임베딩 모델 로딩: {DEFAULT_DENSE_MODEL}")
    model = _get_model(DEFAULT_DENSE_MODEL)
    vecs = np.asarray(model.encode(q, normalize_embeddings=True,
                                   show_progress_bar=False, batch_size=8))

    S = vecs @ vecs.T          # (n, n) 코사인 유사도(정규화됨)
    np.fill_diagonal(S, -1e9)  # 자기 자신 제외 = leave-one-out

    # 페이지별 형제 수 분포(참고)
    page_counts = Counter(pages)
    multi = sum(1 for c in page_counts.values() if c > 1)
    print(f"정답 페이지 {len(page_counts)}개 · 형제(같은 페이지 질문 2개 이상) 있는 페이지 {multi}개")

    # ── LOO 1-NN: 최근접이 형제냐 아니냐로 쪼개서 정확도 ──
    nn = S.argmax(axis=1)
    nn_sim = S[np.arange(n), nn]
    sib_correct = sib_total = non_correct = non_total = 0
    sib_sims, non_sims = [], []
    for i in range(n):
        j = nn[i]
        is_sibling = pages[i] == pages[j]      # 최근접이 같은 페이지에서 나옴?
        correct = intents[j] == intents[i]     # 1-NN 예측이 맞았나?
        if is_sibling:
            sib_total += 1
            sib_correct += correct
            sib_sims.append(nn_sim[i])
        else:
            non_total += 1
            non_correct += correct
            non_sims.append(nn_sim[i])

    loo_acc = (sib_correct + non_correct) / n
    print("\n" + "=" * 62)
    print("LOO 1-NN — 최근접이 '형제(같은 페이지)'냐로 분해")
    print("=" * 62)
    print(f"전체 LOO 정확도: {loo_acc*100:.1f}%  ({sib_correct+non_correct}/{n})")
    print(f"  최근접이 형제:   {sib_total:4d}건 ({sib_total/n*100:4.1f}%)  "
          f"정확도 {sib_correct/max(sib_total,1)*100:5.1f}%  평균유사도 {np.mean(sib_sims):.3f}")
    print(f"  최근접이 비형제: {non_total:4d}건 ({non_total/n*100:4.1f}%)  "
          f"정확도 {non_correct/max(non_total,1)*100:5.1f}%  평균유사도 {np.mean(non_sims):.3f}")

    # ── leave-page-out: 같은 페이지 형제 전부 제외하고 최근접 ──
    lpo_correct = 0
    S2 = vecs @ vecs.T
    pages_arr = np.array(pages)
    for i in range(n):
        row = S2[i].copy()
        row[pages_arr == pages[i]] = -1e9      # 같은 페이지(자기+형제) 전부 제외
        j = int(row.argmax())
        lpo_correct += intents[j] == intents[i]
    lpo_acc = lpo_correct / n
    print("\n" + "=" * 62)
    print("Leave-Page-Out — 같은 페이지 형제 전부 제외(진짜 낯선 질문 조건)")
    print("=" * 62)
    print(f"정확도: {lpo_acc*100:.1f}%  ({lpo_correct}/{n})")

    print("\n" + "=" * 62)
    print("요약 — 형제 효과가 정확도를 얼마나 부풀렸나")
    print("=" * 62)
    print(f"  LOO(자기만 제외):        {loo_acc*100:.1f}%")
    print(f"  Leave-Page-Out(형제도 제외): {lpo_acc*100:.1f}%")
    print(f"  형제 효과로 인한 거품:    {(loo_acc-lpo_acc)*100:+.1f}%p")

    OUT_RESULT.write_text(json.dumps({
        "n_inscope": n,
        "loo_1nn_acc": round(loo_acc, 4),
        "nearest_is_sibling": {
            "count": sib_total, "ratio": round(sib_total/n, 4),
            "acc": round(sib_correct/max(sib_total,1), 4),
            "avg_sim": round(float(np.mean(sib_sims)), 4),
        },
        "nearest_is_non_sibling": {
            "count": non_total, "ratio": round(non_total/n, 4),
            "acc": round(non_correct/max(non_total,1), 4),
            "avg_sim": round(float(np.mean(non_sims)), 4),
        },
        "leave_page_out_acc": round(lpo_acc, 4),
        "sibling_inflation_pp": round((loo_acc-lpo_acc)*100, 2),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n결과 저장: {OUT_RESULT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
