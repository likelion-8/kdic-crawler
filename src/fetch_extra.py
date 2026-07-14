"""페이지네이션 뒷페이지 + 게시판 상세(detailView) 원본 HTML 수집.

왜 필요한가: chgPagingNo 페이지네이션이 있는 페이지(예: 예금보험금 지급대상 금융회사,
FAQ 목록)는 그냥 크롤하면 1페이지 10행만 잡힌다. 안내자료 다운로드(dp_gudn_data) 같은
게시판은 첨부파일이 게시글 상세 페이지에 있어 목록만 크롤하면 파일 URL이 안 잡힌다.

메커니즘 (페이지 인라인 JS 역해석 — fetch_dyntable.py와 동일 실측):
  뒷페이지:  같은 URL로 {curPage: n(0-based), pageSize: 10} POST
  게시글 상세: function detailView(bbsId)가 지정한 action URL로 {bbsId, curPage: 0} POST

저장 (기존 raw_html → text → corpus 파이프라인에 그대로 합류):
  data/raw_html/paged/<id>_p<n>.html    → parse_raw_html.py가 새 라인만 텍스트에 병합
  data/raw_html/detail/<id>__<bbsId>.html → build_corpus.py가 첨부를 corpus에 병합

실행: python3 src/fetch_extra.py [page_id ...]   # 미지정 시 대상 페이지 자동 발견
"""
import re
import sys
import time
from pathlib import Path
from urllib.parse import urljoin

import requests

from crawler_dy import HEADERS, html_to_text
from inventory import PAGES
from parse_raw_html import is_paging_chrome, read_html, strip_noise

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw_html"
PAGED = RAW / "paged"
DETAIL = RAW / "detail"
MAX_PAGES = 300  # fetch_dyntable.py와 동일 — 새 내용이 없으면 알아서 멈춘다
DELAY = 0.7

# 게시판형 상세: detailView(bbsId) 한 개 인자 + action URL. 두 개 인자짜리
# detailView(예: ms_trgt_fnst의 검색 필터)는 목록 재조회라 상세 수집 대상이 아니다.
BOARD_DETAIL_FN = re.compile(
    r"function detailView\(bbsId\)[\s\S]{0,600}?attr\(\"action\",\s*'([^']+)'\)"
)
BOARD_DETAIL_ID = re.compile(r"detailView\((\d+)\)")


def text_lines(html):
    return [l for l in strip_noise(html_to_text(html)).split("\n") if l.strip()]


def fetch_paged(session, page, base_html):
    """curPage를 올리며 POST — 새 라인이 안 나올 때까지. 저장한 페이지 수를 돌려준다."""
    for f in PAGED.glob(f"{page['id']}_p*.html"):  # 재수집 시 이전 산출물 제거
        f.unlink()
    # ponytail: 라인 단위 신규성 판단 — 페이지 공통 UI는 전부 겹치고 표 행·FAQ 항목만 남는다.
    # 페이징 UI("첫 페이지", 페이지 번호, 범위 초과 응답)는 신규 내용으로 치지 않는다.
    seen = set(text_lines(base_html))
    saved = 0
    for cur in range(1, MAX_PAGES):
        r = session.post(
            page["url"],
            headers={**HEADERS, "Referer": page["url"]},
            data={"curPage": str(cur), "pageSize": "10"},
            timeout=30,
        )
        r.raise_for_status()
        r.encoding = "utf-8"
        lines = text_lines(r.text)
        if not any(l not in seen and not is_paging_chrome(l) for l in lines):
            break
        seen.update(lines)
        PAGED.mkdir(parents=True, exist_ok=True)
        (PAGED / f"{page['id']}_p{cur + 1}.html").write_text(r.text, encoding="utf-8")
        saved += 1
        time.sleep(DELAY)
    return saved


def fetch_details(session, page, base_html):
    """게시글 상세 HTML 수집. 목록 전 페이지(뒷페이지 포함)에서 bbsId를 모은다."""
    m = BOARD_DETAIL_FN.search(base_html)
    if not m:
        return 0
    action = urljoin(page["url"], m.group(1))
    ids = set(BOARD_DETAIL_ID.findall(base_html))
    for f in PAGED.glob(f"{page['id']}_p*.html"):
        ids |= set(BOARD_DETAIL_ID.findall(read_html(f)))
    DETAIL.mkdir(parents=True, exist_ok=True)
    for bbs_id in sorted(ids):
        r = session.post(
            action,
            headers={**HEADERS, "Referer": page["url"]},
            data={"bbsId": bbs_id, "curPage": "0"},
            timeout=30,
        )
        r.raise_for_status()
        r.encoding = "utf-8"
        (DETAIL / f"{page['id']}__{bbs_id}.html").write_text(r.text, encoding="utf-8")
        time.sleep(DELAY)
    return len(ids)


def main():
    only = set(sys.argv[1:])
    total_paged = total_detail = 0
    for page in PAGES:
        if only and page["id"] not in only:
            continue
        src = RAW / f"{page['id']}.html"
        if not src.exists():
            continue
        html = read_html(src)
        has_paging = "chgPagingNo(" in html
        has_board = BOARD_DETAIL_FN.search(html) is not None
        if not has_paging and not has_board:
            continue
        s = requests.Session()
        r = s.get(page["url"], headers=HEADERS, timeout=30)  # 세션 쿠키 확보
        r.raise_for_status()
        n_paged = fetch_paged(s, page, html) if has_paging else 0
        n_detail = fetch_details(s, page, html) if has_board else 0
        total_paged += n_paged
        total_detail += n_detail
        print(f"[{page['id']}] 뒷페이지 {n_paged}건, 게시글 상세 {n_detail}건")
    print(f"\n완료: 뒷페이지 {total_paged}건 → data/raw_html/paged/, "
          f"상세 {total_detail}건 → data/raw_html/detail/")
    print("다음 단계: python3 src/parse_raw_html.py && python3 src/build_corpus.py")


if __name__ == "__main__":
    main()
