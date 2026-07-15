"""코퍼스 임베딩 일괄 생성 — 팀 공유용 단일 진입점.

한 사람이 이 스크립트를 실행해 data/dense_cache/ 에 벡터를 만들고 커밋하면, 모든 팀원이
동일한 벡터를 공유한다(각자 재인코딩 불필요 → 하드웨어·버전차로 인한 미세 불일치 제거).

캐시 파일명 = 유닛 텍스트의 SHA256. 코퍼스가 바뀌면 해시가 바뀌어 새 파일이 생기므로, 낡은
벡터를 실수로 쓰지 않는다. 코퍼스 갱신(재수집) 후에는 이 스크립트를 다시 실행해 재커밋하면 된다.

주의: 검색 시 질문(query) 인코딩은 각 실행에서 bge-m3로 이뤄지므로 모델 다운로드는 여전히 필요하다.
여기서 공유되는 것은 '문서 임베딩'이다.

실행: python3 src/embed_corpus.py   (첫 실행 시 bge-m3 ~2GB 다운로드)
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from chunking import build_units, load_records
from retrieval import DenseRetriever, ROOT

MODES = ["page", "faq_atomic", "table_row", "all"]


def main():
    manifest = {}
    all_units = None
    for mode in MODES:
        uids, texts, u2p = build_units(mode)
        DenseRetriever(uids, texts)  # 캐시 없으면 인코딩+저장, 있으면 그대로 재사용
        fname = DenseRetriever._cache_path(texts).name
        manifest[mode] = {"file": fname, "units": len(uids)}
        print(f"{mode:<12} {len(uids):>4}유닛 → dense_cache/{fname}")
        if mode == "all":
            all_units = (uids, texts, u2p)
    mpath = ROOT / "data" / "dense_cache" / "manifest.json"
    mpath.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"manifest → {mpath.relative_to(ROOT)}")

    # 제품용 청크 덤프 — all 모드 임베딩(2498028…npy)과 순서가 정확히 대응한다.
    # RAG가 출처 인용·필터링에 바로 쓰도록 페이지 메타데이터(source_url·title·업무)를 청크에 싣는다.
    uids, texts, u2p = all_units
    meta = {r["page_id"]: r for r in load_records()}
    cpath = ROOT / "data" / "chunks_all.jsonl"
    with open(cpath, "w", encoding="utf-8") as f:
        for u, t in zip(uids, texts):
            m = meta[u2p[u]]
            rec = {
                "chunk_id": u,
                "page_id": u2p[u],
                "source_url": m["source_url"],
                "page_title": m["page_title"],
                "business_function": m["business_function"],
                "text": t,
            }
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"chunks → {cpath.relative_to(ROOT)} ({len(uids)}청크, 메타데이터 포함)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
