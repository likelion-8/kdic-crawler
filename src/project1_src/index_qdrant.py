"""청크(all 모드) + 임베딩(bge-m3-ko)을 로컬 Qdrant(임베디드 파일 모드)에 적재.

서버 없이 QdrantClient(path=...)로 프로세스 안에서 바로 씀 — Docker/포트 불필요.
지금 규모(494벡터)엔 numpy 브루트포스로도 충분하지만, Qdrant로 옮겨두면 이후
실제 서비스 백엔드(필터링·영속화·HTTP API)로 이어가기 쉽다.

포인트 ID는 Qdrant가 문자열 chunk_id("faq_nramt#3" 등)를 못 받아서(정수/UUID만
허용) 순번 정수를 쓰고, 원래 chunk_id는 payload에 그대로 넣어 되짚을 수 있게 한다.

실행: python3 src/project1_src/index_qdrant.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "src"))

from chunking import build_units  # noqa: E402
from retrieval import DEFAULT_DENSE_MODEL, DenseRetriever  # noqa: E402

QDRANT_PATH = str(ROOT / "data" / "qdrant_local")
COLLECTION = "kdic_chunks_all"


def load_chunk_meta():
    """chunks_all.jsonl에서 chunk_id -> 메타데이터(payload용)."""
    import json
    meta = {}
    with open(ROOT / "data" / "chunks_all.jsonl", encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            meta[d["chunk_id"]] = d
    return meta


def validate_business_functions(meta):
    """business_function이 inventory.BUSINESSES(정식 6개 값)와 정확히 일치하는지 검증.

    Qdrant는 이 필드를 payload 필터링에 쓰므로("예금보험금 안내"로 필터 → 정확히 그
    문자열인 문서만 나옴), 공백 차이·오타·null이 하나라도 있으면 그 문서가 필터에서
    조용히 누락된다. 색인 직전에 걸러서 조용한 데이터 누락을 막는다.
    """
    from inventory import BUSINESSES
    bad = {uid: m.get("business_function") for uid, m in meta.items()
           if m.get("business_function") not in BUSINESSES}
    if bad:
        detail = "\n".join(f"  {uid}: {bf!r}" for uid, bf in bad.items())
        raise ValueError(
            f"business_function이 BUSINESSES 정식값과 안 맞는 청크 {len(bad)}건:\n{detail}\n"
            f"정식값: {BUSINESSES}"
        )


def main():
    from qdrant_client import QdrantClient
    from qdrant_client.models import Distance, PointStruct, VectorParams

    uids, texts, u2p = build_units("all")
    dense = DenseRetriever(uids, texts)  # 캐시 있으면 그대로 로드, 없으면 인코딩+저장
    meta = load_chunk_meta()
    validate_business_functions(meta)  # payload 필터링 깨지는 걸 색인 전에 미리 차단

    client = QdrantClient(path=QDRANT_PATH)
    dim = dense.doc_emb.shape[1]

    if client.collection_exists(COLLECTION):
        client.delete_collection(COLLECTION)
    client.create_collection(
        COLLECTION, vectors_config=VectorParams(size=dim, distance=Distance.COSINE))

    points = []
    for i, uid in enumerate(uids):
        m = meta.get(uid, {})
        points.append(PointStruct(
            id=i,
            vector=dense.doc_emb[i].tolist(),
            payload={
                "chunk_id": uid,
                "page_id": u2p[uid],
                "source_url": m.get("source_url"),
                "page_title": m.get("page_title"),
                "business_function": m.get("business_function"),
                "text": texts[i],
            },
        ))
    client.upsert(COLLECTION, points=points)

    count = client.count(COLLECTION).count
    print(f"적재 완료: {COLLECTION} ({count}포인트, 차원 {dim}, 모델 {DEFAULT_DENSE_MODEL})")
    print(f"저장 위치: {QDRANT_PATH}")


if __name__ == "__main__":
    sys.exit(main())
