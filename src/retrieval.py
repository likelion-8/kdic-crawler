"""BM25 · Dense · Hybrid 검색기. 검색 단위(unit)를 색인하고 PageRanked로 페이지 랭킹을 낸다.

색인 단위는 chunking.build_units(mode)가 정한다 — baseline은 통짜 페이지, 처치는 FAQ QA쌍 분할.
검색기는 unit 단위 [(unit_id, score)]를 반환하고, PageRanked가 unit2page로 접어
[(page_id, score)]를 만든다. 그래서 어떤 색인 단위든 평가는 페이지 단위로 동일하게 비교된다.

BM25는 kiwi 형태소 토큰, Dense는 bge-m3 임베딩(코사인), Hybrid는 두 페이지 랭킹의 RRF 결합.
주의: Dense는 8192토큰 초과 유닛의 뒷부분을 자동 절단한다(통짜 페이지 baseline의 한계).
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class BM25Retriever:
    def __init__(self, unit_ids, texts):
        from kiwipiepy import Kiwi
        from rank_bm25 import BM25Okapi
        self.kiwi = Kiwi()
        self.unit_ids = unit_ids
        self.bm25 = BM25Okapi([self._tok(t) for t in texts])

    def _tok(self, text):
        return [t.form for t in self.kiwi.tokenize(text)]

    def search(self, query, k):
        scores = self.bm25.get_scores(self._tok(query))
        ranked = sorted(zip(self.unit_ids, scores), key=lambda x: x[1], reverse=True)
        return ranked[:k]


class DenseRetriever:
    def __init__(self, unit_ids, texts, model="BAAI/bge-m3"):
        import numpy as np
        from sentence_transformers import SentenceTransformer
        # CPU 강제: 8192토큰 유닛의 attention(O(n²))이 MPS 22GB 한도를 넘는다. CPU는 시스템 RAM
        # 사용 → 통짜 8192도 그대로 인코딩(일회성 평가라 속도는 감수). 질의 인코딩에도 필요.
        self.model = SentenceTransformer(model, device="cpu")
        self.unit_ids = unit_ids
        # 유닛 임베딩은 texts 해시로 캐시 — 색인 단위(page/faq_atomic)가 바뀌면 자동 새 캐시.
        cache = self._cache_path(texts)
        if cache.exists():
            self.doc_emb = np.load(cache)
            return
        # normalize → 내적이 곧 코사인 유사도. 8192토큰 초과 유닛은 모델이 자동 절단.
        self.doc_emb = self.model.encode(
            texts, normalize_embeddings=True, show_progress_bar=True, batch_size=4)
        cache.parent.mkdir(exist_ok=True)
        np.save(cache, self.doc_emb)

    @staticmethod
    def _cache_path(texts):
        import hashlib
        h = hashlib.sha256("\x00".join(texts).encode()).hexdigest()[:16]
        return ROOT / "data" / "dense_cache" / f"{h}.npy"

    def search(self, query, k):
        q = self.model.encode([query], normalize_embeddings=True)[0]
        scores = self.doc_emb @ q
        ranked = sorted(zip(self.unit_ids, scores.tolist()), key=lambda x: x[1], reverse=True)
        return ranked[:k]


class PageRanked:
    """유닛 단위 검색기를 감싸 페이지 단위 랭킹으로 변환. 페이지의 순위 = 그 페이지 유닛 중 최고 순위."""
    def __init__(self, inner, unit2page):
        self.inner = inner
        self.unit2page = unit2page
        # dict는 삽입순 보존 → 페이지 등장 순서 유지(고유 페이지 목록)
        self.page_ids = list(dict.fromkeys(unit2page.values()))

    def search(self, query, k):
        seen = {}
        for uid, score in self.inner.search(query, len(self.inner.unit_ids)):
            p = self.unit2page[uid]
            if p not in seen:            # 유닛은 점수순 → 첫 등장이 그 페이지 최고점
                seen[p] = score
        ranked = sorted(seen.items(), key=lambda x: x[1], reverse=True)
        return ranked[:k]


def rrf(rankings, c=60):
    """Reciprocal Rank Fusion. rankings: 여러 검색기의 [(page_id, score)](점수순) 리스트.
    순위만 쓰므로 BM25·Dense 점수 스케일 정규화가 필요 없다."""
    from collections import defaultdict
    fused = defaultdict(float)
    for ranking in rankings:
        for rank, (pid, _) in enumerate(ranking):
            fused[pid] += 1.0 / (c + rank + 1)
    return sorted(fused.items(), key=lambda x: x[1], reverse=True)


class HybridRetriever:
    """두 페이지 단위 검색기(PageRanked)의 랭킹을 RRF로 결합."""
    def __init__(self, bm25, dense):
        self.bm25, self.dense = bm25, dense
        self.n = len(bm25.page_ids)

    def search(self, query, k):
        return rrf([self.bm25.search(query, self.n), self.dense.search(query, self.n)])[:k]
