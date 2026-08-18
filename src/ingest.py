"""신규 페이지 적재 — 관리자가 승인한 URL 을 코퍼스와 수집 대상에 넣는다(미구현 ① 해소).

**왜 있나.** AD-003 은 미리보기(파싱→청킹)까지 되고 [적재]를 누르면 change_request 를
APPROVED 로 바꾼 뒤 REINDEX 잡을 만드는데, **승인이 아무것도 적재하지 않았다.** REINDEX 는
data/corpus.jsonl 을 읽으므로 그 파일에 이 페이지가 없으면 색인에도 없다. 관리자가 청크를
검수해도 지식베이스에 넣을 수단이 없어 결국 개발자가 inventory.PAGES 를 코드로 고쳐야 했다
(요구사항 6.5 체크리스트 2번 미달성 · C 신규 페이지 흐름의 끝).

**무엇을 하나.** approve(ADD) 시점에
  1. URL 을 받아 파싱한다 — 미리보기와 **같은 파서**(crawler.preview.fetch_html·parse_document).
     관리자가 검수한 청크와 다른 본문이 적재되면 검수가 무의미해진다
  2. data/corpus.jsonl 에 레코드를 붙인다(같은 page_id 가 있으면 교체) — REINDEX 가 이걸 읽는다
  3. data/inventory_extra.jsonl 에 수집 대상 항목을 붙인다 — 다음 [전체 재수집]과 변경 감지가
     이 페이지도 다시 읽는다. inventory.PAGES 는 코드 상수라 파일로 확장한다
색인 자체는 하지 않는다 — 그건 이어지는 REINDEX 잡(게이트 통과 시에만 반영)의 몫이다.

**이음매.** ingest_page(record, *, fetcher=) 하나. fetcher 를 주입하면 네트워크 없이 시험한다.
"""
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger("ingest")

ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "data" / "corpus.jsonl"
INVENTORY_EXTRA = ROOT / "data" / "inventory_extra.jsonl"

# 관리자 폼(NewPageRecord)이 주는 8키 + owner. AD-003 규격(A-4).
RECORD_KEYS = ("page_id", "source_url", "business_function", "sub_category",
               "page_title", "required", "note", "summary")


def _read_jsonl(path: Path) -> list:
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def _write_jsonl(path: Path, rows: list) -> None:
    # LF 고정·utf-8 명시(CLAUDE.md 불변식) — CRLF 면 공유 임베딩 캐시 해시가 틀어진다
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    tmp.replace(path)


def build_corpus_record(record: dict, *, fetcher: Optional[Callable] = None) -> dict:
    """URL 을 받아 파싱해 corpus.jsonl 한 행을 만든다. 저장은 하지 않는다."""
    import sys
    for extra in (ROOT / "src", ROOT / "src" / "crawler"):
        if str(extra) not in sys.path:
            sys.path.insert(0, str(extra))
    from hashing import content_sha256
    from preview import fetch_html, parse_document

    fetch = fetcher or fetch_html
    fetched = fetch(record["source_url"])
    html = fetched.html if hasattr(fetched, "html") else str(fetched)
    final_url = getattr(fetched, "url", None) or record["source_url"]   # preview.FetchedPage.url = 최종 URL
    parsed = parse_document(html, final_url)
    if not (parsed.text or "").strip():
        raise ValueError("본문을 추출하지 못했습니다 — 빈 페이지는 적재하지 않습니다")

    return {
        "page_id": record["page_id"],
        "source_url": final_url,
        "business_function": record["business_function"],
        # 관리자가 비워 두면 파서가 뽑은 값으로 채운다(미리보기와 같은 규칙)
        "sub_category": record.get("sub_category") or parsed.sub_category or "",
        "page_title": record.get("page_title") or parsed.title or "",
        "required": bool(record.get("required", True)),
        "note": record.get("note") or "",
        "summary": record.get("summary") or parsed.summary or "",
        # 기존 코퍼스와 같은 날짜 형식(YYYY-MM-DD) — 색인기가 date.fromisoformat 으로 읽는다.
        # 시각까지 넣으면 "Invalid isoformat string" 으로 색인 단계가 죽는다(E2E 실측)
        "collected_at": datetime.now(timezone.utc).date().isoformat(),
        "content_sha256": content_sha256(parsed.text),
        "links": [], "attachments": [], "form_attachments": [], "videos": [], "images": [],
        "text": parsed.text,
    }


def ingest_page(record: dict, *, fetcher: Optional[Callable] = None,
                corpus_path: Path = CORPUS, inventory_path: Path = INVENTORY_EXTRA) -> dict:
    """승인된 신규 페이지를 코퍼스·수집 대상에 넣는다. 반환: {page_id, replaced, text_chars}."""
    missing = [k for k in ("page_id", "source_url", "business_function") if not record.get(k)]
    if missing:
        raise ValueError(f"필수 값 누락: {', '.join(missing)}")

    row = build_corpus_record(record, fetcher=fetcher)

    corpus = _read_jsonl(corpus_path)
    replaced = any(r.get("page_id") == row["page_id"] for r in corpus)
    corpus = [r for r in corpus if r.get("page_id") != row["page_id"]] + [row]
    _write_jsonl(corpus_path, corpus)

    inv = _read_jsonl(inventory_path)
    inv = [p for p in inv if p.get("id") != row["page_id"]] + [{
        "id": row["page_id"], "url": row["source_url"], "business": row["business_function"],
        "sub_category": row["sub_category"], "title": row["page_title"],
        "required": row["required"], "note": row["note"], "summary": row["summary"],
        "owner": record.get("owner") or "admin", "added_by_admin": True,
    }]
    _write_jsonl(inventory_path, inv)

    logger.info("적재: %s (%s) %d자 %s", row["page_id"], row["source_url"], len(row["text"]),
                "교체" if replaced else "신규")
    return {"page_id": row["page_id"], "replaced": replaced, "text_chars": len(row["text"])}


def remove_page(page_id: str, *, corpus_path: Path = CORPUS,
                inventory_path: Path = INVENTORY_EXTRA) -> bool:
    """관리자가 추가한 페이지를 코퍼스·수집 대상에서 뺀다(DELETE 승인). 코드 상수 inventory 의
    페이지는 여기서 못 뺀다 — 그건 is_active 비활성이 담당한다. 반환: 코퍼스에서 뺐는지."""
    corpus = _read_jsonl(corpus_path)
    kept = [r for r in corpus if r.get("page_id") != page_id]
    removed = len(kept) != len(corpus)
    if removed:
        _write_jsonl(corpus_path, kept)
    inv = _read_jsonl(inventory_path)
    _write_jsonl(inventory_path, [p for p in inv if p.get("id") != page_id])
    return removed
