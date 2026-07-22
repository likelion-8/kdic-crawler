"""BM25 · Dense · Hybrid 검색기. 검색 단위(unit)를 색인하고 PageRanked로 페이지 랭킹을 낸다.

색인 단위는 chunking.build_units(mode)가 정한다 — baseline은 통짜 페이지, 처치는 FAQ QA쌍 분할.
검색기는 unit 단위 [(unit_id, score)]를 반환하고, PageRanked가 unit2page로 접어
[(page_id, score)]를 만든다. 그래서 어떤 색인 단위든 평가는 페이지 단위로 동일하게 비교된다.

BM25는 kiwi 형태소 토큰, Dense는 bge-m3 임베딩(코사인), Hybrid는 두 페이지 랭킹의 RRF 결합.
주의: Dense는 8192토큰 초과 유닛의 뒷부분을 자동 절단한다(통짜 페이지 baseline의 한계).
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 프로덕션 Dense 임베딩 모델. 2026-07-21 팀 비교 결과 bge-m3-ko 채택(project_context.md 9.1).
DEFAULT_DENSE_MODEL = "dragonkue/BGE-m3-ko"


class BM25Retriever:
    def __init__(self, unit_ids, texts, unit2bf=None):
        from kiwipiepy import Kiwi
        from rank_bm25 import BM25Okapi
        self.kiwi = Kiwi()
        self.unit_ids = unit_ids
        self.unit2bf = unit2bf  # unit_id → business_function (업무 필터용, 없으면 필터 무시)
        self.bm25 = BM25Okapi([self._tok(t) for t in texts])

    def _tok(self, text):
        return [t.form for t in self.kiwi.tokenize(text)]

    def search(self, query, k, business_function=None):
        scores = self.bm25.get_scores(self._tok(query))
        ranked = sorted(zip(self.unit_ids, scores), key=lambda x: x[1], reverse=True)
        # 업무 필터: 전체 랭킹에서 해당 업무만 남긴 뒤 상위 k → BM25 자체의 '업무 내' 랭킹이 됨
        # (RRF가 이 업무 내 랭킹을 융합하도록 — 상위 k 자른 뒤 필터하면 RRF가 왜곡됨).
        if business_function is not None and self.unit2bf is not None:
            ranked = [r for r in ranked if self.unit2bf.get(r[0]) == business_function]
        return ranked[:k]


_MODEL_CACHE = {}
_QEMB_CACHE = {}


def _encode_query(model, query):
    """질문 임베딩 메모이즈 — 같은 질문이 evaluate·by_type_mrr·answer_recall에서 여러 번,
    또 모드 4개에서 반복 인코딩된다(CPU라 느림). 모델이 공유되므로 질문 텍스트로 캐시하면 안전."""
    if query not in _QEMB_CACHE:
        _QEMB_CACHE[query] = model.encode([query], normalize_embeddings=True)[0]
    return _QEMB_CACHE[query]


def _get_model(name):
    """bge-m3 모델을 프로세스당 1회만 로딩해 재사용(로딩 ~9초). 여러 모드를 한 실행에서 평가할 때
    모델을 매번 새로 올리면 수십 초가 낭비되고 출력이 없어 멈춘 것처럼 보인다."""
    if name not in _MODEL_CACHE:
        from sentence_transformers import SentenceTransformer
        print(f"  {name} 로딩 중… (첫 로딩 ~10초, 캐시 없으면 ~2GB 다운로드)", flush=True)
        # CPU 강제: 8192토큰 유닛의 attention(O(n²))이 MPS 22GB 한도를 넘는다.
        _MODEL_CACHE[name] = SentenceTransformer(name, device="cpu")
    return _MODEL_CACHE[name]


class DenseRetriever:
    def __init__(self, unit_ids, texts, model=DEFAULT_DENSE_MODEL, unit2bf=None):
        import numpy as np
        self.model = _get_model(model)
        self.unit_ids = unit_ids
        self.unit2bf = unit2bf  # unit_id → business_function (업무 필터용, 없으면 필터 무시)
        # 유닛 임베딩은 (모델+texts) 해시로 캐시하며 data/dense_cache/ 는 팀 공유용으로 커밋된다
        # (src/embed_corpus.py 로 생성). 같은 코퍼스·같은 모델이면 팀원 모두 동일 파일을 불러 써 재인코딩 불필요.
        cache = self._cache_path(texts, model)
        if cache.exists():
            self.doc_emb = np.load(cache)
            return
        # normalize → 내적이 곧 코사인 유사도. 8192토큰 초과 유닛은 모델이 자동 절단.
        self.doc_emb = self.model.encode(
            texts, normalize_embeddings=True, show_progress_bar=True, batch_size=4)
        cache.parent.mkdir(exist_ok=True)
        np.save(cache, self.doc_emb)

    @staticmethod
    def _cache_path(texts, model=DEFAULT_DENSE_MODEL):
        # 모델명을 키에 포함 — 안 하면 모델을 바꿔도 이전 모델 벡터를 재사용하는 조용한 버그가 난다.
        import hashlib
        h = hashlib.sha256((model + "\x00" + "\x00".join(texts)).encode()).hexdigest()[:16]
        return ROOT / "data" / "dense_cache" / f"{h}.npy"

    def search(self, query, k, business_function=None):
        q = _encode_query(self.model, query)
        scores = self.doc_emb @ q
        ranked = sorted(zip(self.unit_ids, scores.tolist()), key=lambda x: x[1], reverse=True)
        if business_function is not None and self.unit2bf is not None:
            ranked = [r for r in ranked if self.unit2bf.get(r[0]) == business_function]
        return ranked[:k]


class QdrantDenseRetriever:
    """DenseRetriever와 동일한 search(query,k)->[(unit_id,score)] 계약이지만,
    numpy 브루트포스 대신 로컬 Qdrant(임베디드 파일 모드) 컬렉션에 쿼리한다.

    Qdrant 포인트 id는 정수(순번)라 payload의 chunk_id로 원래 unit_id를 되짚는다.
    코사인 거리 컬렉션이라 반환 score가 곧 코사인 유사도(내적)와 동일하다.
    """
    def __init__(self, path, collection, model=DEFAULT_DENSE_MODEL):
        from qdrant_client import QdrantClient
        self.client = QdrantClient(path=path)
        self.collection = collection
        self.model = _get_model(model)
        # PageRanked가 len(inner.unit_ids)로 "전체 랭킹 요청 개수"를 정하므로 필요
        # (내용은 안 쓰이고 개수만 참조됨).
        self.unit_ids = list(range(self.client.count(collection).count))

    def search(self, query, k, business_function=None):
        q = _encode_query(self.model, query)
        flt = None
        if business_function is not None:
            # payload의 business_function이 정확히 일치하는 포인트만 검색(인덱스 레벨 필터).
            from qdrant_client.models import FieldCondition, Filter, MatchValue
            flt = Filter(must=[FieldCondition(
                key="business_function", match=MatchValue(value=business_function))])
        hits = self.client.query_points(
            self.collection, query=q.tolist(), limit=k, query_filter=flt).points
        return [(h.payload["chunk_id"], h.score) for h in hits]


class PageRanked:
    """유닛 단위 검색기를 감싸 페이지 단위 랭킹으로 변환. 페이지의 순위 = 그 페이지 유닛 중 최고 순위."""
    def __init__(self, inner, unit2page):
        self.inner = inner
        self.unit2page = unit2page
        # dict는 삽입순 보존 → 페이지 등장 순서 유지(고유 페이지 목록)
        self.page_ids = list(dict.fromkeys(unit2page.values()))

    def search(self, query, k, business_function=None):
        seen = {}
        for uid, score in self.inner.search(
                query, len(self.inner.unit_ids), business_function=business_function):
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

    def search(self, query, k, business_function=None):
        return rrf([self.bm25.search(query, self.n, business_function=business_function),
                    self.dense.search(query, self.n, business_function=business_function)])[:k]


class RoutedRetriever:
    """질문 유형(qtype)별로 Hybrid/Dense 중 하나로 라우팅.

    2026-07-21 route_eval.py 비교(all 모드, bge-m3-ko 기준) — 유형별 MRR:
        유형            BM25    Dense  Hybrid
        fact           0.694   0.729   0.737
        table_lookup   0.434   0.893   0.638   ← BM25가 약해 Hybrid가 확실히 손해
        faq            0.912   0.887   0.903
        link_guide     0.609   0.592   0.693
        file_download  0.882   1.000   1.000
    table_lookup만 빼면 Hybrid가 Dense와 같거나 근소하게 낫다. 그래서 예외를 하나로
    최소화해 "기본 Hybrid, table_lookup만 Dense"로 라우팅한다(가중평균 MRR 0.784,
    Dense 단일 0.770·Dense 기본+예외 방식 0.777보다 높음).

    qtype을 안다면(예: 평가 시 테스트셋 라벨) search()에 직접 넘기면 그걸 우선 쓴다.
    모르면(실서비스 기본 경로) classifier로 자동 분류한다 — query_classifier.py의
    QuestionTypeClassifier 참고. classifier도 없으면 안전하게 기본값(Hybrid)으로 처리한다.
    """
    DENSE_ONLY_TYPES = {"table_lookup"}

    def __init__(self, hybrid, dense, classifier=None, bf_classifier=None):
        self.hybrid = hybrid
        self.dense = dense
        self.classifier = classifier        # 질문 유형(table_lookup 여부) 분류 → 검색기 선택
        self.bf_classifier = bf_classifier  # 업무(business_function) 분류 → 검색 범위 필터

    def search(self, query, k, qtype=None, business_function=None):
        # qtype/business_function을 직접 주면(예: 평가 시 정답 라벨) 그걸 우선, 없으면 자동 분류.
        if qtype is None and self.classifier is not None:
            qtype = self.classifier.classify(query)
        if business_function is None and self.bf_classifier is not None:
            business_function = self.bf_classifier.classify(query)
        retriever = self.dense if qtype in self.DENSE_ONLY_TYPES else self.hybrid
        return retriever.search(query, k, business_function=business_function)
