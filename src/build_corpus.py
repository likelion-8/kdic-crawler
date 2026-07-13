"""페이지별 메타데이터(data/meta/<id>.json)와 문서 코퍼스(data/corpus.jsonl) 생성.

사전조사 문서 '필요기능'의 메타데이터 요건을 반영한다:
출처 URL · 업무 카테고리 · 하위 분류 · 수집일자 · 페이지 전체 요약 · 첨부파일 및 이미지.
owner는 팀 내부 관리용 필드라 산출물에서 제외한다.

corpus.jsonl은 페이지(문서) 단위 1줄 = 메타데이터 + 본문 텍스트. 청킹의 입력이 된다.

실행: python3 src/build_corpus.py  (네트워크 불필요 — 로컬 raw_html/text 사용)
"""
import json
import subprocess
from datetime import date
from pathlib import Path
from urllib.parse import urljoin

from bs4 import BeautifulSoup

# 첨부·영상 추출은 jh 크롤러의 함수 재사용 — KDIC의 JS 버튼 다운로드(gfn_downloadFile)까지 잡는다
from crawl_mistaken_remittance_jh import (
    extract_attachments,
    extract_form_attachments,
    extract_videos,
    get_main_content,
)
from inventory import PAGES
from parse_raw_html import read_html

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw_html"
TEXT = ROOT / "data" / "text"
META = ROOT / "data" / "meta"
CORPUS = ROOT / "data" / "corpus.jsonl"


def changed_files():
    """HEAD 대비 변경(재수집·신규)된 파일 집합 — 이들의 수집일은 오늘이다."""
    out = subprocess.run(["git", "status", "--porcelain", "--", "data/raw_html"],
                         capture_output=True, text=True, cwd=ROOT).stdout
    return {line[3:].strip().strip('"') for line in out.splitlines() if line}


def commit_date(path):
    """크롤 시점 ≈ 원본 HTML의 마지막 커밋일 (미커밋이면 빈 문자열)."""
    out = subprocess.run(["git", "log", "-1", "--format=%cs", "--", str(path)],
                         capture_output=True, text=True, cwd=ROOT).stdout.strip()
    return out


def extract_images(html, base_url):
    """본문 영역의 이미지 목록 (alt + 절대 URL, 중복 제거)."""
    soup = BeautifulSoup(html, "html.parser")
    main = soup.find(id="contents") or soup.find(class_="contents") or soup
    seen, out = set(), []
    for img in main.find_all("img", src=True):
        url = urljoin(base_url, img["src"])
        if url not in seen:
            seen.add(url)
            out.append({"alt": img.get("alt", "").strip(), "url": url})
    return out


def build():
    META.mkdir(parents=True, exist_ok=True)
    today = date.today().isoformat()
    changed = changed_files()
    records = []
    for p in PAGES:
        doc_id = p["id"]
        html_path = RAW / f"{doc_id}.html"
        html = read_html(html_path)
        rel = str(html_path.relative_to(ROOT))
        collected = today if rel in changed else (commit_date(rel) or today)
        soup = BeautifulSoup(html, "html.parser")
        content = get_main_content(soup, doc_id)
        meta = {
            "doc_id": doc_id,
            "source_url": p["url"],
            "business_function": p["business"],
            "sub_category": p["sub_category"],
            "page_title": p["title"],
            "required": p["required"],
            "note": p["note"],
            "summary": p["summary"],
            "collected_at": collected,
            "attachments": extract_attachments(content, p["url"]),
            "form_attachments": extract_form_attachments(content, p["url"]),
            "videos": extract_videos(content, p["url"]),
            "images": extract_images(html, p["url"]),
        }
        (META / f"{doc_id}.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        records.append({**meta, "text": (TEXT / f"{doc_id}.txt").read_text(encoding="utf-8")})

    with CORPUS.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"완료: meta {len(records)}건 → data/meta/, corpus {len(records)}줄 → data/corpus.jsonl")


if __name__ == "__main__":
    build()
