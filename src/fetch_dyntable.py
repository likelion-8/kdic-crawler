# scripts/fetch_dyntable.py
"""동적 조회 화면의 결과표 수집 (search_ui 페이지).

왜 필요한가: '보험금 지급대상 금융회사' 같은 화면은 검색 폼 + 페이지네이션 결과표다.
그냥 크롤하면 첫 페이지 10행만 잡히고 나머지는 안 잡히니, chunker 가 그것마저 버린다.

메커니즘 역해석 (페이지 인라인 JS 의 chgPagingNo):
    $("#srchForm").append(<input hidden name="curPage" value={0-based 페이지}>)
    $("#srchForm").append(<input hidden name="pageSize" value="10">)
    → 같은 URL 로 POST
즉 세션 쿠키를 얻은 뒤 curPage 를 0,1,2… 로 올리며 POST 하면 전량을 받을 수 있다.

출력: data/dyn/<page_id>.jsonl — 표 1행 = 1레코드. chunker 가 record 청크로 합류시킨다.
"""
import argparse
import json
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from crawler_yj import DATA, HEADERS, now_iso
from inventory_yj import PAGES

BY_ID = {p["id"]: p for p in PAGES}
# 페이지네이션 상한. 20이면 200행에서 잘린다 — 보호대상 금융회사는 289행이라 그보다 많다(실측).
# 새 행이 안 나오면 알아서 멈추므로 넉넉히 잡는다.
MAX_PAGES = 300


def is_template_row(cells):
    """JS 가 값을 채워 넣기 전의 템플릿 행인가.

    실측: 보호대상금융상품검색(dp_prdct_srch)에서 '금융회사 선택' 팝업의 템플릿 표를 잡았다.
    셀 값이 '#PRSNCONM', '#COADDR' 같은 치환 토큰이었다 — 데이터가 아니라 자리표시자다.
    이걸 그대로 청크로 만들면 챗봇이 "은행명: #PRSNCONM" 이라고 답한다.
    """
    return any(c.startswith("#") or "{{" in c for c in cells)


def parse_rows(html, selector="div.contents"):
    """결과표를 (헤더, 행) 으로 판다.

    '첫 번째로 헤더+행이 있는 표' 를 고르면 안 된다 — 검색 폼의 팝업 템플릿 표를 집는다(실측).
    데이터 행(템플릿이 아닌)이 가장 많은 표를 고른다.
    """
    body = BeautifulSoup(html, "lxml").select_one(selector)
    best = ([], [])
    for table in body.find_all("table"):
        heads = [th.get_text(" ", strip=True) for th in table.find_all("th")]
        rows = []
        for tr in table.find_all("tr"):
            tds = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
            if tds and len(tds) == len(heads) and not is_template_row(tds):
                rows.append(dict(zip(heads, tds)))
        if heads and rows and len(rows) > len(best[1]):
            best = (heads, rows)
    return best


def crawl(page_id, delay=1.0):
    page = BY_ID[page_id]
    s = requests.Session()
    r = s.get(page["url"], headers=HEADERS, timeout=30)   # 세션 쿠키 확보
    r.raise_for_status()
    r.encoding = "utf-8"

    heads, all_rows = [], []
    seen = set()
    for cur in range(MAX_PAGES):            # curPage 는 0-based
        if cur == 0:
            html = r.text                   # 1페이지는 방금 받은 응답
        else:
            resp = s.post(
                page["url"],
                headers={**HEADERS, "Referer": page["url"]},
                data={"curPage": str(cur), "pageSize": "10"},
                timeout=30,
            )
            resp.encoding = "utf-8"
            html = resp.text
        h, rows = parse_rows(html, page.get("body_selector", "div.contents"))
        if not rows:
            break
        heads = heads or h
        fresh = [x for x in rows if json.dumps(x, ensure_ascii=False) not in seen]
        if not fresh:                        # 같은 페이지가 반복되면 끝
            break
        for x in fresh:
            seen.add(json.dumps(x, ensure_ascii=False))
        all_rows += fresh
        time.sleep(delay)

    outdir = DATA / "dyn"
    outdir.mkdir(parents=True, exist_ok=True)
    stamp = now_iso()
    with (outdir / f"{page_id}.jsonl").open("w", encoding="utf-8") as f:
        for i, row in enumerate(all_rows):
            f.write(json.dumps({
                "record_id": f"{i:03d}",
                "page_id": page_id,
                "business_function": page["business"],
                "sub_category": page["sub_category"],
                "title": page["title"],
                "source_url": page["url"],
                "collected_at": stamp,
                "fields": row,
            }, ensure_ascii=False) + "\n")
    print(f"[{page_id}] {len(all_rows)}행 수집 (열: {', '.join(heads)}) -> data/dyn/{page_id}.jsonl")
    return len(all_rows)


def main():
    ap = argparse.ArgumentParser(description="동적 조회 화면의 결과표 전량 수집")
    ap.add_argument("ids", nargs="*", help="page_id (미지정 시 content_type=search_ui 전체)")
    ap.add_argument("--delay", type=float, default=1.0)
    args = ap.parse_args()

    ids = args.ids
    if not ids:      # 지정 안 하면 meta 에서 search_ui 페이지를 찾는다
        ids = [json.loads(p.read_text(encoding="utf-8"))["page_id"]
               for p in (DATA / "meta").glob("*.json")
               if json.loads(p.read_text(encoding="utf-8"))["content_type"] == "search_ui"]
    if not ids:
        print("search_ui 페이지 없음"); return
    total = sum(crawl(i, args.delay) for i in ids)
    print(f"\n합계 {total}행. 청크 반영: python3 chunker.py")


if __name__ == "__main__":
    main()