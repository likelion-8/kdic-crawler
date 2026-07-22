"""검색기 라우팅 판단용 — 제품 모드(all)에서 BM25/Dense/Hybrid를 유형별로 직접 비교한다.

eval_retrieval.py의 [2]번 표는 Dense만 유형별로 쪼갰다(다른 청킹 모드와 비교가 목적이었으므로).
여기서는 청킹 모드는 이미 확정된 "all"로 고정하고, 세 검색기를 전부 유형별로 비교해
"이 유형엔 이 검색기가 유의미하게 낫다"는 라우팅 근거가 있는지를 본다.

Dense 모델은 retrieval.DEFAULT_DENSE_MODEL(현재 dragonkue/BGE-m3-ko)을 그대로 따른다.

판단 기준: 유형별 MRR 차이가 0.03 이상이면 "유의미"로 표시(임계값은 감이므로 논의 후 조정 가능).

실행: python3 src/project1_src/route_eval.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "src"))

from eval_retrieval import KS, build_retrievers, by_type_mrr, load_testset  # noqa: E402
from query_classifier import QuestionTypeClassifier  # noqa: E402
from retrieval import DEFAULT_DENSE_MODEL, RoutedRetriever  # noqa: E402

MARGIN = 0.03  # 이 이상 차이 나야 "유의미하게 낫다"로 판단
MODE = "all"   # 프로덕션이 실제로 쓰는 청킹 모드로 고정 (docs/CODEBASE.md 참고)


def evaluate_routed(routed, questions, ks=KS):
    """evaluate()와 같은 산식이지만, RoutedRetriever가 유형별로 다른 검색기를 타도록
    질문의 qtype(questions의 3번째 원소)을 search()에 그대로 넘겨준다.
    evaluate()/by_type_mrr()는 qtype을 안 넘기므로(계약이 search(q,k)뿐) 별도로 둔다."""
    maxk = max(ks)
    recall = {k: 0.0 for k in ks}
    rr_sum = 0.0
    for q, gold, qtype, *_ in questions:
        ranked = [pid for pid, _ in routed.search(q, maxk, qtype=qtype)]
        for k in ks:
            hits = sum(1 for pid in ranked[:k] if pid in gold)
            recall[k] += hits / len(gold)
        rr = 0.0
        for i, pid in enumerate(ranked, 1):
            if pid in gold:
                rr = 1.0 / i
                break
        rr_sum += rr
    n = len(questions)
    return {f"Recall@{k}": recall[k] / n for k in ks} | {"MRR": rr_sum / n}


def by_type_mrr_routed(routed, questions):
    from collections import defaultdict
    groups = defaultdict(list)
    for item in questions:
        groups[item[2]].append(item)
    return {t: evaluate_routed(routed, qs)["MRR"] for t, qs in groups.items()}


def leave_one_out_predictions(classifier):
    """분류기 정확도의 진짜 검증 — 자기 자신을 예시 풀에서 빼고 분류한다.
    안 빼면 모든 질문이 자기 자신과 유사도 1.0으로 매칭돼 정확도가 허위로 100%가 된다."""
    import numpy as np
    sims = classifier.emb @ classifier.emb.T  # (N, N) 자기 자신 포함 전체 유사도
    np.fill_diagonal(sims, -1)  # 자기 자신 제외
    best = sims.argmax(axis=1)
    return [classifier.types[i] for i in best]


def evaluate_routed_with_predicted_types(routed, questions, predicted_types, ks=KS):
    """evaluate_routed와 같지만, 정답 라벨 대신 분류기가 예측한 qtype으로 라우팅한다.
    실서비스에서 실제로 겪을 성능(라벨을 모르고 분류기에 의존)을 재는 것."""
    maxk = max(ks)
    rr_sum = 0.0
    for (q, gold, *_), pred_t in zip(questions, predicted_types):
        ranked = [pid for pid, _ in routed.search(q, maxk, qtype=pred_t)]
        rr = 0.0
        for i, pid in enumerate(ranked, 1):
            if pid in gold:
                rr = 1.0 / i
                break
        rr_sum += rr
    return rr_sum / len(questions)


def main():
    questions = load_testset()
    print(f"평가 질문 {len(questions)}건, 색인 모드: {MODE}, Dense 모델: {DEFAULT_DENSE_MODEL}\n")

    print(f"[{MODE}] 색인 중… (질문 인코딩에 수십 초 소요, 모델 로딩 포함)", flush=True)
    retrievers, _, n = build_retrievers(MODE)
    print(f"유닛 수: {n}\n")

    names = ["BM25", "Dense", "Hybrid"]
    per_type = {name: by_type_mrr(retrievers[name], questions) for name in names}

    types = sorted(per_type["Dense"], key=lambda t: -len(
        [q for q in questions if q[2] == t]))

    print("=== 유형별 MRR (검색기 × 유형, all 모드 고정) ===")
    print("유형".ljust(14) + "".join(n.rjust(10) for n in names) + "   최선".rjust(4))
    winners = {}
    for t in types:
        scores = {name: per_type[name][t] for name in names}
        best = max(scores, key=scores.get)
        margin_ok = all(scores[best] - v >= MARGIN for k, v in scores.items() if k != best)
        winners[t] = best if margin_ok else "(차이 미미)"
        row = t.ljust(14) + "".join(f"{scores[n]:>10.3f}" for n in names)
        print(row + "   " + winners[t])

    print("\n=== 라우팅 결정: 기본 Hybrid, table_lookup만 Dense ===")
    print(f"  Dense 단독 예외 유형: {sorted(RoutedRetriever.DENSE_ONLY_TYPES)}")

    routed = RoutedRetriever(retrievers["Hybrid"], retrievers["Dense"])
    routed_per_type = by_type_mrr_routed(routed, questions)
    routed_overall = evaluate_routed(routed, questions)["MRR"]

    print("\n유형".ljust(14) + "Dense단독".rjust(10) + "Hybrid단독".rjust(10) + "라우팅".rjust(10))
    for t in types:
        print(t.ljust(14) + f"{per_type['Dense'][t]:>10.3f}"
              f"{per_type['Hybrid'][t]:>10.3f}{routed_per_type[t]:>10.3f}")

    print(f"\n전체 MRR — Dense단독: {mrr_overall(retrievers['Dense'], questions):.3f}"
          f" / Hybrid단독: {mrr_overall(retrievers['Hybrid'], questions):.3f}"
          f" / 라우팅(정답라벨): {routed_overall:.3f}")

    print("\n=== 질문 유형 분류기 검증 (실서비스 조건 — qtype 모름, 자동 분류) ===")
    classifier = QuestionTypeClassifier()
    preds = leave_one_out_predictions(classifier)
    truth = classifier.types

    # 라우팅 결정에 실제로 영향을 주는 건 "table_lookup이냐 아니냐" 이진 판단뿐
    tp = sum(1 for p, t in zip(preds, truth) if p == "table_lookup" and t == "table_lookup")
    fp = sum(1 for p, t in zip(preds, truth) if p == "table_lookup" and t != "table_lookup")
    fn = sum(1 for p, t in zip(preds, truth) if p != "table_lookup" and t == "table_lookup")
    tn = sum(1 for p, t in zip(preds, truth) if p != "table_lookup" and t != "table_lookup")
    n_lookup = tp + fn
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / n_lookup if n_lookup else 0.0
    acc5way = sum(1 for p, t in zip(preds, truth) if p == t) / len(truth)

    print(f"5유형 전체 정확도(leave-one-out): {acc5way:.3f}")
    print(f"table_lookup 이진 판별 — precision: {precision:.3f}, recall: {recall:.3f}"
          f" (TP={tp} FP={fp} FN={fn} TN={tn}, 실제 table_lookup {n_lookup}건)")

    routed_predicted_overall = evaluate_routed_with_predicted_types(routed, questions, preds)
    print(f"\n라우팅(분류기 예측): {routed_predicted_overall:.3f}"
          f"  (참고 — 라우팅(정답라벨): {routed_overall:.3f}, Dense단독: "
          f"{mrr_overall(retrievers['Dense'], questions):.3f})")


def mrr_overall(retriever, questions):
    from eval_retrieval import evaluate
    return evaluate(retriever, questions)["MRR"]


if __name__ == "__main__":
    sys.exit(main())
