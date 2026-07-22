# src/project1_src/crawler_dy.py
"""크롤러 + 결정론적 HTML→텍스트 변환 — 기능2·기능3 담당분.

inventory_dy.PAGES 목록만 수집한다. LLM 미사용, 규칙 기반 변환.
저장 구조: data/raw_html/<doc_id>.html · data/text/<doc_id>.txt · data/meta/<doc_id>.json

사용법:
  python3 src/project1_src/crawler_dy.py   # 전체 8건 수집
"""
import json
import re
import time
from datetime import date
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from inventory import pages_for

# 통합 inventory(표준 스키마)를 이 크롤러가 쓰던 원래 필드명으로 매핑
PAGES = [
    {
        "page_id": p["id"],
        "business_function": p["business"],
        "sub_category": p["sub_category"],
        "page_title": p["title"],
        "url": p["url"],
        "required": "필수" if p["required"] else "분석필요",
        "reason": p["note"],
        "summary": p["summary"],
    }
    for p in pages_for("dy")
]

ROOT = Path(__file__).resolve().parent.parent.parent
DATA = ROOT / "data"
RAW = DATA / "raw_html"
TEXT = DATA / "text"
META = DATA / "meta"
ATTACH_EXT = re.compile(r"\.(pdf|hwp|hwpx|docx?|xlsx?|pptx?|zip)(\?|$)", re.I)
HEADERS = {"User-Agent": "Mozilla/5.0 (likelion-yesom24-pipeline; data collection for KDIC RAG project)"}


def fetch(url):
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    r.encoding = r.apparent_encoding or "utf-8"
    return r.text


def table_to_text(tbl):
    rows = []
    for tr in tbl.find_all("tr"):
        cells = [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]
        if any(cells):
            rows.append(" | ".join(cells))
    return "\n".join(rows)


def html_to_text(html):
    """결정론적 HTML→텍스트. 표는 '|' 구분 행으로 보존, 본문 영역 우선."""
    soup = BeautifulSoup(html, "html.parser")
    for t in soup(["script", "style", "noscript", "header", "footer", "nav"]):
        t.decompose()
    # kdic·fins 모두 본문은 class="contents" div. fins는 <body> 2개(첫번째 빈 것)라 body 폴백 금지
    main = soup.find(id="contents") or soup.find(class_="contents") or soup.find("main") or soup
    # 표를 먼저 텍스트 행으로 치환해 구조 보존
    for tbl in main.find_all("table"):
        tbl.replace_with(BeautifulSoup("<p>" + table_to_text(tbl) + "</p>", "html.parser"))
    text = main.get_text("\n", strip=True)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


def extract_attachments(html, base_url):
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if ATTACH_EXT.search(href) or "FileDown" in href or "fileDown" in href:
            out.append({"name": a.get_text(" ", strip=True) or href, "url": urljoin(base_url, href)})
    # 중복 제거 (순서 유지)
    seen, uniq = set(), []
    for f in out:
        if f["url"] not in seen:
            seen.add(f["url"])
            uniq.append(f)
    return uniq


def run():
    for d in (RAW, TEXT, META):
        d.mkdir(parents=True, exist_ok=True)
    for p in PAGES:
        doc_id = p["page_id"]
        print(f"[{doc_id}] {p['sub_category']} ... ", end="", flush=True)
        html = fetch(p["url"])
        (RAW / f"{doc_id}.html").write_text(html, encoding="utf-8")
        text = html_to_text(html)
        (TEXT / f"{doc_id}.txt").write_text(text, encoding="utf-8")
        meta = {
            "page_id": doc_id,
            "source_url": p["url"],
            "business_function": p["business_function"],
            "sub_category": p["sub_category"],
            "page_title": p["page_title"],
            "required": p["required"],
            "summary": p["summary"],
            "collected_at": date.today().isoformat(),
            "attachments": extract_attachments(html, p["url"]),
            "char_count": len(text),
            "raw_path": f"data/raw_html/{doc_id}.html",
            "text_path": f"data/text/{doc_id}.txt",
        }
        (META / f"{doc_id}.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"ok ({len(text)}자, 첨부 {len(meta['attachments'])}건)")
        time.sleep(1)  # 공공기관 사이트 부하 방지
    print(f"\n완료: 페이지 {len(PAGES)}건 → data/")


if __name__ == "__main__":
    run()
