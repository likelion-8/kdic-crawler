# src/chunker_dy.py
"""글자수 기반 청킹 — data/text/*.txt → data/chunks_dy.jsonl

parent_doc_id로 원본 역참조 가능 (Parent-Child Retrieval용).
크롤링 없이 로컬 텍스트만 다시 청킹하므로 단독 재실행 가능.

사용법:
  python3 src/chunker_dy.py
"""
import json

from crawler_dy import DATA, TEXT
from inventory_dy import PAGES

CHUNK_SIZE = 500
CHUNK_OVERLAP = 100


def chunk_text(text, size=CHUNK_SIZE, overlap=CHUNK_OVERLAP):
    # ponytail: 글자수 기반 단순 청킹 — 프로젝트 기술설계상 초기 프로토타입, 이후 교체 예정
    chunks, start = [], 0
    while start < len(text):
        end = min(start + size, len(text))
        chunks.append({"start": start, "end": end, "text": text[start:end]})
        if end == len(text):
            break
        start = end - overlap
    return chunks


def run():
    all_chunks = []
    for p in PAGES:
        doc_id = p["doc_id"]
        # newline="" 필수: 원문에 \r\n이 있어 universal newline 변환 시 청크 오프셋이 밀린다
        with (TEXT / f"{doc_id}.txt").open(encoding="utf-8", newline="") as fh:
            text = fh.read()
        for i, c in enumerate(chunk_text(text)):
            all_chunks.append({
                "chunk_id": f"{doc_id}-{i:03d}",
                "parent_doc_id": doc_id,
                "business_function": p["business_function"],
                "sub_category": p["sub_category"],
                "source_url": p["url"],
                **c,
            })
    with (DATA / "chunks_dy.jsonl").open("w", encoding="utf-8") as f:
        for c in all_chunks:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    print(f"완료: 페이지 {len(PAGES)}건, 청크 {len(all_chunks)}건 → data/chunks_dy.jsonl")


if __name__ == "__main__":
    run()
