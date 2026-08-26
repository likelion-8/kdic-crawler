"""원문 변경 감지 — 홈페이지를 다시 읽어 본문 해시가 저장본과 다른 페이지를 표시한다.

**왜 있나.** 기획서(AD-004 R2)는 "원본이 바뀐 페이지 N건"과 "마지막 확인" 시각을 약속하는데,
비교를 실제로 돌리는 주체가 없었다(미구현 ②). [지금 확인]은 확인 시각만 기록했고, 변경이
드러나는 유일한 경로는 관리자가 감으로 [전체 재수집]을 돌릴 때의 변환 단계뿐이었다.
관리자는 "3건은 진짜인가?"에서 매번 개발자를 불렀다.

**무엇을 하나.** 수집 대상(inventory.PAGES) 중 정적 페이지를 다시 읽어 **본문 텍스트의
content_sha256** 을 documents 의 저장 해시와 대조한다(갱신 감지 기준은 HTML 이 아니라
본문 텍스트다 — 판본·세션토큰 탓에 HTML 은 튄다, CLAUDE.md 불변식). 다르면
index_status='PENDING' 으로 표시한다. **저장하거나 색인하지 않는다** — 표시만 한다. 실제
반영은 관리자가 [선택 재수집]을 눌러 게이트를 지나야 한다.

**이음매.** detect(pages, *, fetch, saved) 하나다. fetch 와 saved(page_id→hash) 를 주입하면
네트워크·DB 없이 판정 로직을 시험할 수 있다. 워커의 재수집 변환 단계와 같은 변환 체인
(html_to_text → strip_noise → merge_paged → content_sha256)을 쓴다 — 두 경로의 판정이
다르면 감지는 '변경'인데 재수집은 '동일'이라는 모순이 생긴다.

동적 표(dyn_table)·페이지네이션 페이지는 감지 대상에서 뺀다 — 별도 스크립트로만 수집되고
한 번의 GET 으로 본문을 얻을 수 없다. 이 페이지들의 변경은 재수집 변환 단계가 잡는다.
"""
import logging
import time
from typing import Callable, Optional

logger = logging.getLogger("change_detect")

# 예의 있는 수집 간격 — 워커 재수집·원 크롤러와 같은 태도
POLITE_SLEEP_S = 0.5


def _text_of(page_id: str, html: str) -> str:
    """워커 변환 단계와 동일한 체인. 여기서 갈라지면 감지와 재수집의 판정이 어긋난다."""
    from crawler_dy import html_to_text
    from parse_raw_html import merge_paged, strip_noise
    return merge_paged(page_id, strip_noise(html_to_text(html)))


def detect(pages: list, *, fetch: Callable[[str], str], saved: dict,
           sleep: Optional[Callable[[float], None]] = time.sleep,
           on_progress: Optional[Callable[[int, int], None]] = None) -> dict:
    """정적 페이지를 다시 읽어 저장 해시와 대조한다.

    pages : inventory.PAGES 항목들({id,url,expect?,dyn_table?})
    fetch : url -> html
    saved : page_id -> 저장된 content_sha256 (documents 테이블에서 읽어 넘긴다)
    on_progress : 페이지 하나를 끝낼 때마다 (처리한 수, 전체 수). 워커가 잡 단계에 적어
                  화면이 %를 그린다 — 58페이지를 한 단계 안에서 도니 상태만으론 진행이 안 보인다

    돌려주는 dict:
      changed   본문 해시가 다른 page_id 목록 → 호출자가 PENDING 으로 표시
      unchanged 같은 page_id 목록
      failed    [{page_id, reason}] — 받지 못했거나 옛 판본만 온 페이지. **변경으로 치지
                않는다** — 못 읽은 것을 바뀐 것으로 적으면 관리자가 헛걸음한다
      skipped   동적 표 등 감지 대상 밖 page_id
    """
    from hashing import content_sha256

    changed, unchanged, failed, skipped = [], [], [], []
    for done, p in enumerate(pages, 1):
        pid = p["id"]
        if p.get("dyn_table"):
            skipped.append(pid)
            if on_progress: on_progress(done, len(pages))
            continue
        html, last = None, ""
        for _attempt in range(3):
            try:
                candidate = fetch(p["url"])
            except Exception as exc:  # noqa: BLE001 — 페이지 단위로 수렴
                last = f"{type(exc).__name__}: {exc}"
                if sleep: sleep(1.0)
                continue
            if p.get("expect") and p["expect"] not in candidate:
                # 서버가 옛 판본을 준 것 — inventory 가 못박은 문자열이 든 판본만 채택
                last = "expect 판본 불일치(옛 판본 수신)"
                if sleep: sleep(1.0)
                continue
            html = candidate
            break
        if html is None:
            failed.append({"page_id": pid, "reason": last})
            if on_progress: on_progress(done, len(pages))
            continue
        new_hash = content_sha256(_text_of(pid, html))
        if saved.get(pid) is None:
            # 저장본이 없으면 비교 기준이 없다 — 신규 페이지는 AD-003 적재 흐름의 몫
            skipped.append(pid)
        elif new_hash != saved[pid]:
            changed.append(pid)
        else:
            unchanged.append(pid)
        if on_progress: on_progress(done, len(pages))
        if sleep: sleep(POLITE_SLEEP_S)

    logger.info("변경 감지: 변경 %d · 동일 %d · 실패 %d · 제외 %d",
                len(changed), len(unchanged), len(failed), len(skipped))
    return {"changed": changed, "unchanged": unchanged, "failed": failed, "skipped": skipped}


def run(session, on_progress: Optional[Callable[[int, int], None]] = None) -> dict:
    """실제 실행 — 저장 해시를 읽고, 감지하고, PENDING 을 표시한다. 워커·API 가 부른다.

    PENDING 표시는 '이번에 변경으로 판정된 것'으로 **덮어쓴다**: 이전에 PENDING 이었는데
    이번에 동일로 판정되면 되돌린다(관리자가 재수집 없이 원문이 원래대로 돌아온 경우).
    단 REINDEXING(재색인 진행 중)은 건드리지 않는다 — 워커가 소유한 상태다.
    """
    import sys
    from pathlib import Path
    from sqlalchemy import select, update

    root = Path(__file__).resolve().parent
    for extra in (root, root / "crawler"):
        if str(extra) not in sys.path:
            sys.path.insert(0, str(extra))
    from crawler_dy import fetch
    from inventory import PAGES
    from schema import documents

    rows = session.execute(
        select(documents.c.page_id, documents.c.content_sha256, documents.c.index_status)
        .where(documents.c.is_active.is_(True))).all()
    saved = {r.page_id: r.content_sha256 for r in rows}
    reindexing = {r.page_id for r in rows if r.index_status == "REINDEXING"}

    result = detect(PAGES, fetch=fetch, saved=saved, on_progress=on_progress)

    to_pending = [pid for pid in result["changed"] if pid not in reindexing]
    to_clear = [pid for pid in result["unchanged"] if pid not in reindexing]
    if to_pending:
        session.execute(update(documents).where(documents.c.page_id.in_(to_pending))
                        .values(index_status="PENDING"))
    if to_clear:
        # PENDING 이던 것만 되돌린다 — 다른 상태(예: 정상 색인 상태값)를 건드리지 않는다
        session.execute(update(documents)
                        .where(documents.c.page_id.in_(to_clear),
                               documents.c.index_status == "PENDING")
                        .values(index_status=None))
    session.commit()
    result["marked_pending"] = to_pending
    return result
