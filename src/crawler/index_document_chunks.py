"""documents/document_chunks(신규 스키마, schema.py)에 실제 문서+청크+임베딩 적재.

kdic_chunks_all(index_pgvector.py, 레거시 flat 테이블)을 대체하는 정식 스키마 적재 —
documents는 data/corpus.jsonl(페이지 단위 원문), document_chunks는
build_units("all")+load_chunk_meta()로 만든 청크에 임베딩을 붙여 넣는다.

실행: python3 src/crawler/index_document_chunks.py   (여러 번 돌려도 안전)

## 2026-08-10 — DELETE 후 전량 재삽입에서 UPSERT 로 바꿨다

이전에는 `DELETE FROM document_chunks` → `DELETE FROM documents` → 전량 INSERT 였다.
파일 하나로 돌리는 크롤러 스크립트일 때는 멱등해서 문제가 없었는데, 관리자 화면이 같은
테이블을 쓰기 시작하면서 두 가지가 깨졌다.

1. **관리자 입력값이 통째로 사라진다.** documents 에 P3 확장 7컬럼(owner·collection_status·
   index_status·split_rule·collection_note·link_check·first_indexed_at)이 붙었는데
   corpus.jsonl 16키에는 없다. 재적재 한 번에 관리자가 화면에서 적어 둔 담당자·수집 사유가
   빈칸이 된다. 에러도 안 나고 조용히.
2. **documents.id 가 매번 새로 발급된다.** 무엇이 이 행을 가리키든 재적재마다 연결이 끊긴다.
   검색 인덱스 버전 관리·변경 요청·활동 로그가 전부 "그 시점의 그 문서"를 가리켜야 하는데
   대상이 매번 사라지면 성립하지 않는다.

그래서 **크롤러가 소유한 컬럼만 갱신하고 나머지는 건드리지 않는다**(_CRAWLER_OWNED).
is_active 도 갱신 대상이 아니다 — 관리자가 검색에서 뺀 페이지를 재수집이 되살리면 안 된다.

## 소유 구분

| | 소유자 | 컬럼 |
|---|---|---|
| 크롤러 | 이 스크립트 | source_url·page_title·business_function·sub_category·content·summary·content_sha256·collected_at·metadata |
| 관리자 | 화면(AD-002) | owner·collection_status·index_status·split_rule·collection_note·link_check·first_indexed_at·is_active |

`first_indexed_at` 은 이 스크립트가 채우지 않는다 — 읽는 코드가 아직 없어(web/src 검색 0건)
값을 만들어 둘 이유가 없다. 화면에서 필요해지는 시점에 그 기능과 함께 넣는다.

## 코퍼스에서 빠진 페이지는 지우지 않는다

예전에는 DELETE 로 같이 사라졌다. 지금은 남겨 두고 경고만 찍는다 — 페이지 삭제는 관리자의
변경 요청(change-request)으로만 하기로 했고(핸드오프 K7·K8), 스크립트가 조용히 지우면 그
경로를 우회하는 데다 되돌릴 수 없다. 청크는 재현 불가능하므로 새 빌드에 없는 것을 지운다.
"""
import gzip
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "src"))

from chunking import build_units, is_faq, is_table, load_records  # noqa: E402
from db import get_engine  # noqa: E402
from retrieval import DEFAULT_DENSE_MODEL, DenseRetriever  # noqa: E402
from schema import document_chunks, documents, search_index_versions  # noqa: E402

from sqlalchemy import func, select, text, update  # noqa: E402
from sqlalchemy.dialects.postgresql import insert as pg_insert  # noqa: E402

CORPUS = ROOT / "data" / "corpus.jsonl"


def load_chunk_meta():
    """chunks_all.jsonl에서 chunk_id -> 메타데이터. (Qdrant 시절 index_qdrant.py 에서 옮겨옴 —
    2026-08-31 정리. 색인기와 워커(검증 단계)가 같은 로더를 쓴다.)"""
    import json
    meta = {}
    with open(ROOT / "data" / "chunks_all.jsonl", encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            meta[d["chunk_id"]] = d
    return meta


def validate_business_functions(meta):
    """business_function이 inventory.BUSINESSES(정식 6개 값)와 정확히 일치하는지 검증.

    이 필드는 검색 필터·관리자 화면 분류의 키다. 공백 차이·오타·null이 하나라도 있으면 그
    문서가 필터에서 조용히 누락되므로 색인 직전에 걸러서 조용한 데이터 누락을 막는다.
    """
    from inventory import BUSINESSES
    bad = {uid: m.get("business_function") for uid, m in meta.items()
           if m.get("business_function") not in BUSINESSES}
    if bad:
        detail = "
".join(f"  {uid}: {bf!r}" for uid, bf in bad.items())
        raise ValueError(
            f"business_function이 BUSINESSES 정식값과 안 맞는 청크 {len(bad)}건:
{detail}
"
            f"정식값: {BUSINESSES}"
        )

_EXTRA_META_KEYS = ("required", "note", "links", "attachments", "form_attachments", "videos", "images")

# 재적재 때 덮어쓸 컬럼 = 크롤러가 corpus.jsonl 에서 만들어내는 값만. 여기 없는 컬럼은
# 충돌 시 그대로 둔다(관리자 입력값·is_active·id·first_indexed_at).
_CRAWLER_OWNED = ("source_url", "page_title", "business_function", "sub_category",
                  "content", "summary", "content_sha256", "collected_at", "metadata")

# 청크는 전부 크롤러 소유다(관리자가 손대는 컬럼이 없다). is_active 만 예외로,
# 부모 문서에서 트리거로 내려오는 값이라 여기서 덮지 않는다.
_CHUNK_OWNED = ("document_id", "chunk_index", "chunk_type", "text", "embedding",
                "business_function", "page_title", "source_url")


def _chunk_type(page_text):
    if is_faq(page_text):
        return "faq"
    if is_table(page_text):
        return "table"
    return "page"


# 스냅샷을 되돌렸을 때 같은 인덱스가 나오려면 입력만으론 부족하다 — 그때의 빌드 설정이 함께
# 있어야 한다. 여기 담는 건 **적재 시점** 파라미터뿐이다(README §3.4). Top-K·리랭킹·하이브리드
# 결합비 같은 검색 시점 값은 질의할 때 적용되므로 인덱스를 재현하는 것과 무관하다.
_BUILD_PARAMS = {
    "chunk_mode": "all",                      # chunking.build_units("all") — 구조 인식 청킹
    "embedding_model": DEFAULT_DENSE_MODEL,
    "builder": "src/crawler/index_document_chunks.py",
}

# 2026-07-30 held-out 89문항 정식 측정치(리랭킹 Off). docs/pipeline_heldout_baseline_89q.md.
#
# 첫 ACTIVE 행에만 넣는다. 3주차 재적재가 "직전 버전 대비"로 게이트를 판정하는데 비교 대상이
# 비어 있으면 첫 재적재만 예외 처리해야 하기 때문이다. 이 스크립트가 잰 값이 아니므로 출처와
# 측정일을 함께 박아 둔다 — 나중에 Smoke 가 채우는 값과 성격이 다르다.
_BASELINE_METRICS = {
    "recall_at_1": 0.606, "recall_at_3": 0.854, "recall_at_5": 0.922,
    "recall_at_10": 0.949, "mrr": 0.806,
    "testset": "testset_pipeline.jsonl (89문항, held-out)",
    "reranker": False,
    "measured_at": "2026-07-30",
    "source": "docs/pipeline_heldout_baseline_89q.md",
}


def _record_active_version(conn, doc_count, chunk_count, chunk_mode: str = "all"):
    """지금 적재한 인덱스가 곧 운영본이라는 사실을 search_index_versions 에 남긴다.

    유지하는 불변식은 하나다 — **ACTIVE 행 1개 = 지금 운영 중인 인덱스**. 그래서 행이 없으면
    만들고, 있으면 스냅샷·카운트를 현재 상태로 갱신한다.

    ⚠️ 버전 '전환'(새 행 생성 + 기존 ACTIVE -> SUPERSEDED)은 여기서 하지 않는다. 전환은
    정합성 검증과 Smoke 평가를 통과해야 일어나는 일인데(docs/search_index_versioning.md §3)
    이 스크립트에는 그 게이트가 없다 — 개발자가 직접 돌리는 적재 도구다. 전환·롤백은 3주차
    재적재 워커 몫이고, 그때 이 함수가 그 자리를 물려받는다.
    """
    snapshot = gzip.compress(CORPUS.read_bytes())
    active_id = conn.execute(
        select(search_index_versions.c.id)
        .where(search_index_versions.c.status == "ACTIVE")
    ).scalar()

    values = dict(source_snapshot=snapshot, build_params={**_BUILD_PARAMS, "chunk_mode": chunk_mode},
                  doc_count=doc_count, chunk_count=chunk_count)
    if active_id is None:
        conn.execute(search_index_versions.insert().values(
            status="ACTIVE", activated_at=func.now(),
            metrics=_BASELINE_METRICS,
            note="버전 관리 도입 시점의 운영 인덱스. 지표는 별도 측정치(_BASELINE_METRICS 주석 참고).",
            **values,
        ))
        return "생성"
    # metrics 는 덮지 않는다 — 평가가 잰 값이라 적재 스크립트가 건드릴 성질이 아니다.
    # activated_at 은 올린다(2026-08-18) — 같은 ACTIVE 행을 갱신하는 구조라 id 는 그대로인데,
    # 이 시각이 안 바뀌면 "색인이 교체됐다"를 아무도 알 수 없다. 질의 캐시 자동 무효화(PRD-03)와
    # 검색 엔진 재조립이 (id, activated_at) 을 보고 판단한다. 종전에는 이 값이 08-10 에 멈춰
    # 있어 캐시 무효화가 사실상 죽어 있었다.
    conn.execute(update(search_index_versions)
                 .where(search_index_versions.c.id == active_id)
                 .values(activated_at=func.now(), **values))
    return "갱신"


def main(chunk_mode: str = "all"):
    """chunk_mode: chunking.build_units 의 mode(2026-08-18 인자화 — 관리자 재적재 모달의 청킹
    모드가 여기까지 관통한다. 종전 "all" 고정). 버전 기록 build_params 에도 실린다."""
    records = load_records()
    page_text = {r["page_id"]: r["text"] for r in records}
    # 청크 메타 중 business_function·page_title·source_url 은 **페이지 단위** 값이라 페이지
    # 레코드에서 직접 뽑는다. 종전에는 chunks_all.jsonl(all 모드 산출물)의 chunk_id 로 조회해서,
    # 다른 청킹 모드로 돌리면 id 가 안 맞아 .get(uid, {}) 가 빈 dict 를 주고 NULL 이 조용히 들어갔다.
    page_meta = {r["page_id"]: {"business_function": r.get("business_function"),
                                "page_title": r.get("page_title"),
                                "source_url": r.get("source_url")} for r in records}

    uids, texts, u2p = build_units(chunk_mode)
    dense = DenseRetriever(uids, texts)  # 캐시 있으면 그대로 로드
    chunk_meta = load_chunk_meta()
    validate_business_functions(chunk_meta)

    doc_rows = [{
        "page_id": r["page_id"],
        "source_url": r.get("source_url"),
        "page_title": r.get("page_title"),
        "business_function": r.get("business_function"),
        "sub_category": r.get("sub_category"),
        "content": r.get("text"),
        "summary": r.get("summary"),
        "content_sha256": r.get("content_sha256"),
        "collected_at": date.fromisoformat(r["collected_at"]) if r.get("collected_at") else None,
        "metadata": {k: r.get(k) for k in _EXTRA_META_KEYS},
    } for r in records]

    engine = get_engine()
    with engine.begin() as conn:
        # --- 1) documents UPSERT (page_id 기준) ---
        # page_id 에 unique 가 걸려 있어 충돌 대상이 된다(schema.py). 갱신은 크롤러 소유
        # 컬럼만 — 관리자 확장 7컬럼과 is_active 는 set_ 에 없으므로 기존 값이 살아남는다.
        doc_stmt = pg_insert(documents).values(doc_rows)
        conn.execute(doc_stmt.on_conflict_do_update(
            index_elements=["page_id"],
            set_={c: doc_stmt.excluded[c] for c in _CRAWLER_OWNED},
        ))

        page_id_to_doc_id = dict(conn.execute(text("SELECT page_id, id FROM documents")).all())

        chunk_rows = []
        for i, uid in enumerate(uids):
            pid = u2p[uid]
            m = page_meta.get(pid, {})
            suffix = uid.rsplit("#", 1)[1] if "#" in uid else "0"
            chunk_rows.append({
                "document_id": page_id_to_doc_id[pid],
                "chunk_id": uid,
                "chunk_index": int(suffix),
                "chunk_type": _chunk_type(page_text[pid]),
                "text": texts[i],
                "embedding": dense.doc_emb[i].tolist(),
                "business_function": m.get("business_function"),
                "page_title": m.get("page_title"),
                "source_url": m.get("source_url"),
            })

        # --- 2) document_chunks UPSERT (chunk_id 기준) ---
        chunk_stmt = pg_insert(document_chunks).values(chunk_rows)
        conn.execute(chunk_stmt.on_conflict_do_update(
            index_elements=["chunk_id"],
            set_={c: chunk_stmt.excluded[c] for c in _CHUNK_OWNED},
        ))

        # --- 3) 이번 빌드에 없는 청크 삭제 ---
        # 페이지 본문이 바뀌면 분할 경계가 밀려 그 페이지의 청크 개수·번호가 달라진다.
        # 남겨 두면 옛 경계의 청크가 검색에 계속 걸린다(문서는 최신, 근거는 과거).
        stale = conn.execute(
            document_chunks.delete()
            .where(document_chunks.c.chunk_id.notin_(uids))
            .returning(document_chunks.c.chunk_id)
        ).scalars().all()

        # --- 4) is_active 를 부모 문서에 다시 맞춘다 ---
        # documents.is_active -> document_chunks.is_active 트리거는 documents 를 UPDATE 할 때만
        # 돈다(schema.py trg_sync_document_chunks_is_active). 위 UPSERT 는 is_active 를 안 건드리므로
        # 트리거가 안 돌고, 새로 INSERT 된 청크는 기본값 true 로 들어간다 — 비활성 문서의 청크가
        # 검색에 되살아나는 조용한 버그가 여기서 난다. 그래서 한 번 맞춰 준다.
        revived = conn.execute(text("""
            UPDATE document_chunks c SET is_active = d.is_active
              FROM documents d
             WHERE c.document_id = d.id AND c.is_active IS DISTINCT FROM d.is_active
        """)).rowcount

        # --- 5) 코퍼스에서 빠진 페이지 확인(삭제하지 않는다) ---
        orphans = conn.execute(
            documents.select()
            .with_only_columns(documents.c.page_id)
            .where(documents.c.page_id.notin_([r["page_id"] for r in doc_rows]))
        ).scalars().all()

        doc_count = conn.execute(text("SELECT count(*) FROM documents")).scalar()
        chunk_count = conn.execute(text("SELECT count(*) FROM document_chunks")).scalar()

        # --- 6) 이 인덱스가 운영본임을 기록 (docs/search_index_versioning.md) ---
        version_action = _record_active_version(conn, doc_count, chunk_count, chunk_mode)

    print(f"적재 완료: documents {doc_count}행, document_chunks {chunk_count}행")
    print(f"  활성 검색 버전 {version_action} (corpus 스냅샷 {len(gzip.compress(CORPUS.read_bytes())) // 1024}KB)")
    print(f"  코퍼스 기준: 문서 {len(doc_rows)}건 · 청크 {len(uids)}건")
    if stale:
        print(f"  옛 경계 청크 삭제: {len(stale)}건 ({', '.join(stale[:5])}{' …' if len(stale) > 5 else ''})")
    if revived:
        print(f"  is_active 재동기화: {revived}건")
    if orphans:
        print(f"  ⚠️ 코퍼스에 없는 문서 {len(orphans)}건이 DB 에 남아 있다(자동 삭제하지 않는다): "
              f"{', '.join(orphans)}")
        print("     삭제하려면 관리자 화면의 변경 요청(change-request)으로 처리할 것.")


if __name__ == "__main__":
    sys.exit(main())
