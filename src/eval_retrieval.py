"""검색기 평가: Recall@k, MRR. 검색기는 search(query, k)->[(page_id, score)] 계약만 만족하면 됨.

정답은 data/testset/testset_all.jsonl 의 expected_sources(page_id 집합). 코퍼스로 답할 수 없는
out_of_scope 질문(expected_sources 빈 값)은 검색 평가 대상이 아니므로 제외한다.

실행: python3 src/eval_retrieval.py   (BM25·Dense·Hybrid 비교표 출력. 첫 실행 bge-m3 다운로드)
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TESTSET = ROOT / "data" / "testset" / "testset_all.jsonl"
KS = [1, 3, 5, 10]


def load_testset(path=TESTSET):
    """expected_sources 있는 질문만 (out_of_scope 제외) → [(q, {page_id,...}, qtype, [must_include]), ...]."""
    qs = []
    # encoding 명시 필수 — 윈도우 기본(cp949)은 UTF-8 한글 테스트셋을 못 읽는다.
    with open(path, encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            if d["expected_sources"]:
                qs.append((d["question"], set(d["expected_sources"]), d["question_type"], d["must_include"]))
    return qs


# 답변 단위 평가의 컨텍스트 예산(글자). 검색된 top-k 유닛을 이어붙여 이 길이로 자른 뒤 정답 포함 여부를
# 본다 — LLM에 넘길 컨텍스트를 근사한 것. 통짜 페이지는 긴 문서가 여기서 잘려 꼬리 정답을 잃는다.
CONTEXT_BUDGET = 6000


def answer_recall(unit_retriever, unit_texts, questions, k=5, budget=CONTEXT_BUDGET):
    """AnswerRecall@k: 검색된 top-k 유닛을 예산만큼 이어붙인 컨텍스트에 must_include가 모두 있으면 hit.
    페이지 단위 검색지표가 못 보는 '정답이 실제로 컨텍스트에 살아있나'를 잰다."""
    items = [(q, must) for q, _, _, must in questions if must]
    hit = 0
    for q, must in items:
        units = [u for u, _ in unit_retriever.search(q, k)]
        ctx = "\n".join(unit_texts[u] for u in units)[:budget]
        if all(m in ctx for m in must):
            hit += 1
    return hit / len(items)


def evaluate(retriever, questions, ks=KS):
    """Recall@k = (top-k에 든 정답 수)/(정답 수), MRR = 첫 정답의 역순위. 질문 평균."""
    maxk = max(ks)
    recall = {k: 0.0 for k in ks}
    rr_sum = 0.0
    for q, gold, *_ in questions:
        ranked = [pid for pid, _ in retriever.search(q, maxk)]
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


def _selftest():
    """지표 산식 검증 — 알려진 랭킹으로 Recall/MRR 값을 못 박는다 (모델 로드 불필요)."""
    class Fake:
        def __init__(self, order):
            self.order = order

        def search(self, q, k):
            return [(p, 0.0) for p in self.order][:k]

    qs = [("q", {"A"})]  # gold = {A}
    r = evaluate(Fake(["B", "A", "C"]), qs, ks=[1, 3])  # 랭킹 B,A,C
    assert abs(r["MRR"] - 0.5) < 1e-9, r          # A가 2위 → RR=1/2
    assert r["Recall@1"] == 0.0 and r["Recall@3"] == 1.0, r
    r2 = evaluate(Fake(["A", "B"]), qs, ks=[1])   # A가 1위
    assert r2["Recall@1"] == 1.0 and r2["MRR"] == 1.0, r2
    print("selftest ok")


def by_type_mrr(retriever, questions):
    """질문유형별 MRR — 표/엔티티 질문에서 검색기 강약을 드러낸다."""
    from collections import defaultdict
    groups = defaultdict(list)
    for item in questions:
        groups[item[2]].append(item)
    return {t: evaluate(retriever, qs)["MRR"] for t, qs in groups.items()}


def build_retrievers(mode):
    """색인 단위(mode)로 BM25/Dense/Hybrid 페이지 랭킹 검색기 + 유닛 텍스트(답변평가용) 구성."""
    from chunking import build_units
    from retrieval import BM25Retriever, DenseRetriever, HybridRetriever, PageRanked
    uids, texts, u2p = build_units(mode)
    bm25 = PageRanked(BM25Retriever(uids, texts), u2p)
    dense = PageRanked(DenseRetriever(uids, texts), u2p)
    hybrid = HybridRetriever(bm25, dense)
    return {"BM25": bm25, "Dense": dense, "Hybrid": hybrid}, dict(zip(uids, texts)), len(uids)


MODES = ["page", "faq_atomic", "table_row", "all"]


def main():
    _selftest()
    questions = load_testset()
    tail = load_testset(ROOT / "data" / "testset" / "testset_tail_probe.jsonl")
    from collections import Counter
    types = Counter(item[2] for item in questions)
    tps = sorted(types, key=lambda t: -types[t])
    print(f"검색 평가 {len(questions)}건 · 꼬리 프로브 {len(tail)}건 — 유형: {dict(types)}")

    mrr, per_type, arec, arec_tail, nunits = {}, {}, {}, {}, {}
    for mode in MODES:
        print(f"[{mode}] 색인·평가 중… (질문 인코딩에 수십 초 소요)", flush=True)
        retrievers, unit_texts, n = build_retrievers(mode)
        nunits[mode] = n
        mrr[mode] = {name: evaluate(r, questions)["MRR"] for name, r in retrievers.items()}
        per_type[mode] = by_type_mrr(retrievers["Dense"], questions)
        arec[mode] = {nm: answer_recall(retrievers[nm].inner, unit_texts, questions) for nm in ["BM25", "Dense"]}
        arec_tail[mode] = {nm: answer_recall(retrievers[nm].inner, unit_texts, tail) for nm in ["BM25", "Dense"]}

    def row(name, d, fmt="{:>11.3f}"):
        return name.ljust(12) + "".join(fmt.format(d[m]) for m in MODES)

    hdr = "".join(f"{m}({nunits[m]})".rjust(11) for m in MODES)
    print("\n=== [1] 문서찾기 MRR (검색기 × 색인단위) ===")
    print("검색기".ljust(12) + hdr)
    for name in ["BM25", "Dense", "Hybrid"]:
        print(row(name, {m: mrr[m][name] for m in MODES}))

    print("\n=== [2] Dense 유형별 MRR (색인단위별) — 어떤 청킹이 어떤 유형을 올리나 ===")
    print("유형".ljust(12) + hdr)
    for t in tps:
        print(row(f"{t}({types[t]})", {m: per_type[m][t] for m in MODES}))

    print("\n=== [3] AnswerRecall@5 전체 (정답이 컨텍스트 6000자에 포함?) ===")
    print("검색기".ljust(12) + hdr)
    for nm in ["BM25", "Dense"]:
        print(row(nm, {m: arec[m][nm] for m in MODES}))

    print(f"\n=== [4] AnswerRecall@5 꼬리 프로브 {len(tail)}건 (잘린 표 꼬리 겨냥) — 잘림 사각지대 ===")
    print("검색기".ljust(12) + hdr)
    for nm in ["BM25", "Dense"]:
        print(row(nm, {m: arec_tail[m][nm] for m in MODES}))
    return 0


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(ROOT / "src"))
    sys.exit(main())
