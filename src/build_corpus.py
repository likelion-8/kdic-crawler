"""페이지별 메타데이터(data/meta/<id>.json)와 문서 코퍼스(data/corpus.jsonl) 생성.

사전조사 문서 '필요기능'의 메타데이터 요건을 반영한다:
출처 URL · 업무 카테고리 · 하위 분류 · 수집일자 · 페이지 전체 요약 · 첨부파일 및 이미지.
owner는 팀 내부 관리용 필드라 산출물에서 제외한다.

corpus.jsonl은 페이지(문서) 단위 1줄 = 메타데이터 + 본문 텍스트. 청킹의 입력이 된다.

갱신 감지는 본문 텍스트의 content_sha256 으로 한다. 직전 상태는 지난 실행이 남긴
data/meta/<page_id>.json 이며, 해시가 같으면 collected_at 을 그대로 물려받는다.
(원본 HTML 은 판본 혼재·세션 토큰 탓에 본문이 그대로여도 바뀌므로 기준이 못 된다.)

실행: python3 src/build_corpus.py  (네트워크 불필요 — 로컬 raw_html/text 사용)
"""
import json
import re
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
from hashing import content_sha256
from inventory import PAGES
from parse_raw_html import read_html

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw_html"
PAGED = RAW / "paged"
DETAIL = RAW / "detail"
TEXT = ROOT / "data" / "text"
META = ROOT / "data" / "meta"
CORPUS = ROOT / "data" / "corpus.jsonl"

BOARD_DETAIL_ID = re.compile(r"detailView\((\d+)\)")


def previous_meta(page_id):
    """지난 실행이 남긴 메타 (최초 실행이면 None)."""
    path = META / f"{page_id}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


# ---- 페이지 내 이동 링크 추출 ------------------------------------------------
# KDIC 본사이트는 href가 전부 "javascript:void(0)"이고 실제 URL이 onclick에 있다.
#   gfn_openUrl('https://...'+'path')  /  window.open('url', ...)  /  location.href='url'
# fins 포털은 평범한 href를 쓴다. 두 경우 모두 여기서 잡는다.
ONCLICK_OPENURL = re.compile(r"gfn_openUrl\(([^)]*)\)")
ONCLICK_WINOPEN = re.compile(r"window\.open\(\s*['\"]([^'\"]+)['\"]")
ONCLICK_LOCHREF = re.compile(r"location\.href\s*=\s*['\"]([^'\"]+)['\"]")
QUOTED = re.compile(r"'([^']*)'")
# 본문(.contents) 안에 섞여 들어오는 사이트 공통 UI — 링크로서 의미 없음
LINK_NOISE_CLASSES = {"chatbot", "btnScrolltop", "thirty", "siteMove", "snsBtn",
                      "btnFirst", "btnPrev", "btnNext", "btnLast"}
LINK_NOISE_TEXTS = {"KOR", "ENG", "sns 목록 열기", "상단으로 이동"}
LINK_NOISE_HOSTS = ("pubkbot.kdic.or.kr", "kdic30th.kr")
ATTACH_SUFFIXES = (".hwp", ".hwpx", ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".zip")


def extract_links(content, base_url):
    """본문 영역에서 버튼/링크로 이동 가능한 URL 목록 (첨부파일은 attachments 몫)."""
    seen, out = set(), []
    for tag in content.find_all(["a", "button"]):
        if LINK_NOISE_CLASSES & set(tag.get("class", [])):
            continue
        text = tag.get_text(" ", strip=True)
        if not text or text in LINK_NOISE_TEXTS:
            continue
        onclick = tag.get("onclick", "") or ""
        href = (tag.get("href") or "").strip()
        url = None
        m = ONCLICK_OPENURL.search(onclick)
        if m:  # 인자가 'a'+'b' 문자열 결합 형태 — 리터럴만 이어 붙인다
            url = "".join(QUOTED.findall(m.group(1)))
        elif ONCLICK_WINOPEN.search(onclick):
            url = ONCLICK_WINOPEN.search(onclick).group(1)
        elif ONCLICK_LOCHREF.search(onclick):
            url = ONCLICK_LOCHREF.search(onclick).group(1)
        elif href and not href.startswith(("javascript:", "#", "mailto:", "tel:")):
            url = href
        if not url:
            continue
        url = urljoin(base_url, url)
        path = url.split("?")[0].lower()
        if url in seen or url == base_url or path.endswith(ATTACH_SUFFIXES):
            continue
        if any(h in url for h in LINK_NOISE_HOSTS):
            continue
        seen.add(url)
        out.append({"text": text, "url": url})
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


def board_detail_attachments(page_id, page_url):
    """게시판 상세 HTML(raw_html/detail/, fetch_extra.py 수집분)의 첨부를 모은다.

    첨부가 어느 게시글 것인지 알 수 있도록, 목록 페이지의 detailView(bbsId) 앵커
    텍스트(게시글 제목)를 라벨 앞에 붙인다.
    """
    files = sorted(DETAIL.glob(f"{page_id}__*.html"))
    if not files:
        return [], []
    titles = {}
    for f in [RAW / f"{page_id}.html", *PAGED.glob(f"{page_id}_p*.html")]:
        if not f.exists():
            continue
        for a in BeautifulSoup(read_html(f), "html.parser").find_all(onclick=True):
            m = BOARD_DETAIL_ID.match(a.get("onclick", ""))
            if m:
                titles[m.group(1)] = a.get_text(" ", strip=True)
    atts, form_atts, seen = [], [], set()
    for f in files:
        bbs_id = f.stem.split("__")[1]
        title = titles.get(bbs_id, "")
        content = get_main_content(BeautifulSoup(read_html(f), "html.parser"), f.stem)
        for a in extract_attachments(content, page_url):
            if a["url"] in seen:
                continue
            seen.add(a["url"])
            atts.append({**a, "text": f"{title} — {a['text']}" if title else a["text"]})
        for fa in extract_form_attachments(content, page_url):
            form_atts.append(
                {**fa, "label": f"{title} — {fa['label']}" if title else fa["label"]})
    return atts, form_atts


def build():
    META.mkdir(parents=True, exist_ok=True)
    today = date.today().isoformat()
    records, updated, added = [], [], []
    for p in PAGES:
        page_id = p["id"]
        html = read_html(RAW / f"{page_id}.html")
        text = (TEXT / f"{page_id}.txt").read_text(encoding="utf-8")
        sha = content_sha256(text)
        prev = previous_meta(page_id)
        if prev is None:
            added.append(page_id)
            collected = today
        # content_sha256 이 없던 기존 메타(해시 도입 전)는 변경 없음으로 보고 수집일을 지킨다
        elif prev.get("content_sha256", sha) == sha:
            collected = prev["collected_at"]
        else:
            updated.append(page_id)
            collected = today
        soup = BeautifulSoup(html, "html.parser")
        content = get_main_content(soup, page_id)
        dtl_atts, dtl_form_atts = board_detail_attachments(page_id, p["url"])
        meta = {
            "page_id": page_id,
            "source_url": p["url"],
            "business_function": p["business"],
            "sub_category": p["sub_category"],
            "page_title": p["title"],
            "required": p["required"],
            "note": p["note"],
            "summary": p["summary"],
            "collected_at": collected,
            "content_sha256": sha,
            "links": extract_links(content, p["url"]),
            "attachments": extract_attachments(content, p["url"]) + dtl_atts,
            "form_attachments": extract_form_attachments(content, p["url"]) + dtl_form_atts,
            "videos": extract_videos(content, p["url"]),
            "images": extract_images(html, p["url"]),
        }
        (META / f"{page_id}.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        records.append({**meta, "text": text})

    with CORPUS.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"완료: meta {len(records)}건 → data/meta/, corpus {len(records)}줄 → data/corpus.jsonl")
    print(f"  갱신 {len(updated)}건{': ' + ', '.join(updated) if updated else ''}")
    print(f"  신규 {len(added)}건{': ' + ', '.join(added) if added else ''}")


if __name__ == "__main__":
    build()
