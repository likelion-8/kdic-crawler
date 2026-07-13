# scripts/crawler.py
"""크롤러 + 결정론적 HTML→텍스트 변환.

원칙(기획서): HTML→텍스트 변환은 규칙 기반. LLM 미사용. 원문 보존.
저장 구조: data/raw_html/<id>.html · data/text/<id>.txt · data/meta/<id>.json

resume 지원: meta/<id>.json 이 있으면 건너뛴다 (--force 로 무시).
"""
import argparse
import copy
import hashlib
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup, NavigableString

from inventory import pages_for

PAGES = pages_for("yj")

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}
DELAY_SEC = 1.0
DOWNLOAD_RE = re.compile(r"gfn_downloadFile\s*\(\s*'([^']*)'\s*,\s*'([^']*)'\s*\)")
# 신청·조회 버튼은 href 가 아니라 onclick="gfn_openUrl('https://…')" 안에 URL 이 있다
OPENURL_RE = re.compile(r"gfn_openUrl\s*\(\s*'([^']+)'")

# 헤더/푸터 크롬. div.contents 안쪽까지 섞여 들어오므로 '정확일치'로만 지운다.
# 정확일치로만 지우는 이유: "예솜이 : ..." 같은 캐릭터 대사는 진짜 콘텐츠라 부분일치로 지우면 오제거된다.
NOISE_EXACT = {
    "글자", "크기", "글자확대", "글자축소", "KOR", "ENG", "상단으로 이동",
    "퀵메뉴", "예솜이", "에게 물어보세요", "똑똑한 예보챗봇비서",
    "앱 설치", "QR 코드", "공식", "홈페이지",
    "KDIC(예금보험공사)", "KDIC(예금보험공사) 금융안심포털",
    "창립 30주년 예금보험공사 디지털역사관 바로가기",
    "좌우로 움직여보세요", "열기", "닫기",
}
# 레이아웃 마커: camelCase 클래스명이 텍스트로 노출되는 케이스 (lineBox, topTit 등)
NOISE_LINE = re.compile(r"^[a-z][a-zA-Z0-9_]*[A-Z][a-zA-Z0-9_]*$")

# 모든 페이지 헤더/푸터에 붙는 크롬 링크. 정확일치로만 제외해 본문 교차참조 링크는 살린다.
NOISE_URLS = {
    "http://www.kdic30th.kr",
    "https://www.kdic.or.kr/sp/main.do",
    "https://www.kdic.or.kr/en/main.do",     # 헤더의 ENG 전환 버튼
}


def now_iso():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def sha1(s):
    return hashlib.sha1(s.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- 표 → 마크다운
def _cell(td):
    return re.sub(r"\s+", " ", td.get_text(" ", strip=True)).replace("|", "\\|")


# JS 가 채우는 빈 결과표의 셀 값. 크롤 시점엔 껍데기라 그대로 두면 거짓이 된다.
PLACEHOLDER_CELL = {"", "0", "-", "0원"}


def _is_shell_table(body):
    """JS 가 채우기 전의 '빈 껍데기 표' 인가. body = [(원본 셀, 펼친 셀)] 데이터 행들."""
    vals = [c.strip() for raw, cells in body if len(raw) > 1 for c in cells[1:]]
    return bool(vals) and all(v in PLACEHOLDER_CELL for v in vals)


def _is_placeholder_row(raw):
    """같은 안내문이 여러 칸에 복사된 행. colspan 펼치기 '전' 원본 셀로 판정해야 한다."""
    v = [c.strip() for c in raw]
    return len(v) > 1 and len(set(v)) == 1


def table_to_md(table):
    """<table> 을 마크다운 파이프 표로. 빈 결과표는 버리고, 없는 사실을 근거로 삼지 않게 한다."""
    rows = []            # [(원본 셀, colspan 펼친 셀)]
    for tr in table.select("tr"):
        raw, cells = [], []
        for c in tr.find_all(["th", "td"], recursive=False):
            span = int(c.get("colspan", 1) or 1)
            raw.append(_cell(c))
            cells.extend([_cell(c)] * span)
        if cells:
            rows.append((raw, cells))
    if not rows:
        return ""
    head = rows[0][1]
    body = [(raw, cells) for raw, cells in rows[1:] if not _is_placeholder_row(raw)]
    if len(rows) > 1 and (not body or _is_shell_table(body)):
        return ""
    rows = [head] + [cells for _, cells in body]
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    out = ["| " + " | ".join(rows[0]) + " |", "|" + "---|" * width]
    for r in rows[1:]:
        out.append("| " + " | ".join(r) + " |")
    caption = table.find("caption")
    if caption:
        out.insert(0, _cell(caption))
    return "\n".join(out)


# ------------------------------------------------------- DOM → 텍스트 (결정론)
HEADING_SEL = "h2, h3, h4, h5, dt"
HEADING_SKIP = {"퀵메뉴"}


def mark_headings(body):
    """헤딩·아코디언 제목을 '## 제목' 한 줄로 치환한다. (요소 전체 치환 — 부분 삽입은 안 됨)"""
    for h in body.select(HEADING_SEL):
        txt = re.sub(r"\s+", " ", h.get_text(" ", strip=True)).strip()
        txt = re.sub(r"\s*(열기|닫기)$", "", txt).strip()
        if txt and txt not in HEADING_SKIP:
            h.replace_with(NavigableString(f"\n## {txt}\n"))
    return body


def node_to_text(body, base_url=""):
    """DOM → 텍스트. 이미지·영상은 '있다는 사실 + 절대 주소'로 남긴다."""
    body = copy.copy(body)
    for tag in body(["script", "style", "noscript"]):
        tag.decompose()
    for img in body.find_all("img"):
        alt = (img.get("alt") or "").strip()
        src = urljoin(base_url, (img.get("src") or "").strip()) if img.get("src") else ""
        if alt:
            body_txt = f"\n[그림: {alt}" + (f" | {src}]" if src else "]") + "\n"
            img.replace_with(NavigableString(body_txt))
        else:
            img.replace_with(NavigableString(""))
    for m in body.find_all(["video", "iframe"]):
        src = urljoin(base_url, (m.get("src") or "").strip()) if m.get("src") else ""
        m.replace_with(NavigableString(f"\n[영상: {src}]\n" if src else "\n[영상 있음]\n"))
    for table in body.find_all("table"):
        table.replace_with(NavigableString("\n\n" + table_to_md(table) + "\n\n"))
    mark_headings(body)
    return body.get_text("\n", strip=True)


def collapse(text):
    """공백 정리 + 레이아웃 마커 제거 + 헤더/푸터 크롬 정확일치 제거."""
    kept = []
    for raw in text.split("\n"):
        line = re.sub(r"[ \t\xa0]+", " ", raw).strip()
        if not line:
            kept.append("")
            continue
        if line in NOISE_EXACT or NOISE_LINE.match(line):
            continue
        if line.startswith("## "):
            line = re.sub(r"\s*(열기|닫기)$", "", line)
            if kept and kept[-1] != "":
                kept.append("")
        kept.append(line)
    out = "\n".join(kept)
    return re.sub(r"\n{3,}", "\n\n", out).strip()


# ------------------------------------------------------------------ 메타 추출
def extract_breadcrumb(soup, page):
    """계층 경로. <title> 이 '대분류 ... 소분류' 를 담는다."""
    title = soup.title.get_text() if soup.title else ""
    parts = [p.strip() for p in re.split(r"[\n\t]+", title) if p.strip()]
    if len(parts) >= 2:
        return parts
    return [p.strip() for p in page["sub_category"].split(">")]


def extract_attachments(body, html):
    """첨부는 <a href> 가 아니라 onclick="gfn_downloadFile('경로토큰','파일명토큰')" (JS 다운로드)."""
    out = []
    for i, node in enumerate(body.select("[onclick]")):
        m = DOWNLOAD_RE.search(node.get("onclick", ""))
        if not m:
            continue
        row = node.find_parent("tr")
        label = ""
        if row:
            first = row.find(["th", "td"])
            if first:
                label = _cell(first)
        out.append({
            "idx": i,
            "label": label or _cell(node),
            "enc_path": m.group(1),
            "enc_name": m.group(2),
        })
    return out


def extract_external_links(body, base_url):
    """이용자가 '다음에 갈 곳' 링크. a[href] 뿐 아니라 onclick="gfn_openUrl(...)" 도 잡는다."""
    seen, out = set(), []

    def add(text, raw):
        url = urljoin(base_url, raw.strip())
        p = urlparse(url)
        if p.scheme not in ("http", "https") or url in seen or url in NOISE_URLS or url == base_url:
            return
        seen.add(url)
        out.append({"text": (text or "")[:80], "url": url})

    for a in body.select("a[href]"):
        href = a["href"].strip()
        if not href.startswith(("#", "javascript:", "mailto:", "tel:")):
            add(_cell(a), href)

    for node in body.select("[onclick]"):
        for raw in OPENURL_RE.findall(node.get("onclick", "")):
            add(_cell(node), raw)
    return out


def classify(body):
    """동적/로그인 페이지 플래그. 로그인 판정은 password 입력창(구조 신호)만 쓴다."""
    txt = body.get_text(" ", strip=True)
    if body.select_one("input[type=password]"):
        return "login_required"
    paginated = "다음 페이지" in txt and "마지막 페이지" in txt
    search_form = bool(body.select_one("select")) and "초기화" in txt
    if paginated and search_form:
        return "search_ui"
    return "content"


# ---------------------------------------------------------------------- 크롤
class PageGone(Exception):
    """사이트에서 페이지가 사라졌다 (삭제/이동)."""


class PageBroken(Exception):
    """페이지는 있는데 본문 컨테이너를 못 찾았다. 레이아웃 변경일 수도, 삭제일 수도 있다."""


# 이 사이트는 없는 페이지에 404 를 안 준다. HTTP 200 + '오류' 제목을 준다(soft 404, 실측).
SOFT_404_TITLE = re.compile(r"^\s*오류\s*\|")


def render(page, session):
    """페이지를 받아 (응답, soup, body, 본문텍스트) 반환. 저장은 하지 않는다."""
    selector = page.get("body_selector", "div.contents")
    r = session.get(page["url"], headers=HEADERS, timeout=30)
    if r.status_code in (404, 410):
        raise PageGone(f"{page['id']}: HTTP {r.status_code} — 페이지가 사라졌습니다")
    r.raise_for_status()
    r.encoding = "utf-8"
    soup = BeautifulSoup(r.text, "lxml")

    title = soup.title.get_text() if soup.title else ""
    if SOFT_404_TITLE.match(title):
        raise PageGone(f"{page['id']}: 오류 페이지가 반환됨 (soft 404) — 페이지가 사라졌습니다")

    body = soup.select_one(selector)
    if body is None:
        raise PageBroken(
            f"{page['id']}: 본문 컨테이너({selector}) 없음. 레이아웃이 바뀌었거나 페이지가 사라졌습니다 — "
            f"probe_structure.py {page['id']} 로 확인하세요"
        )
    return r, soup, body, collapse(node_to_text(body, page["url"]))


VARIANT_TRIES = 5      # 판본이 갈릴 때 몇 번까지 다시 받아보나


def render_stable(page, session):
    """판본이 흔들리는 페이지를 안전하게 받는다. 항상 새 세션으로 한 번 더 받아 대조한다."""
    r, soup, body, text = render(page, session)
    r2, soup2, body2, text2 = render(page, requests.Session())
    if text == text2:
        return r, soup, body, text

    seen = {text: (r, soup, body), text2: (r2, soup2, body2)}
    expect = page.get("expect")
    for _ in range(VARIANT_TRIES - 2):
        if expect and any(expect in t for t in seen):
            break
        time.sleep(DELAY_SEC)
        rn, sn, bn, tn = render(page, requests.Session())
        seen.setdefault(tn, (rn, sn, bn))

    (DATA / "variants").mkdir(parents=True, exist_ok=True)
    for t in seen:
        (DATA / "variants" / f"{page['id']}_{sha1(t)[:8]}.txt").write_text(t, encoding="utf-8")

    if not expect:
        raise RuntimeError(
            f"{page['id']}: 서버가 판본 {len(seen)}종을 서빙합니다 — 어느 쪽이 맞는지 자동으로 정할 수 없습니다.\n"
            f"  data/variants/{page['id']}_*.txt 를 열어 diff 로 비교하고, 맞는 판본에만 있는 문자열을\n"
            f"  인벤토리 항목에 \"expect\": \"...\" 로 넣어 주세요 (판정 근거는 주석으로 남기세요)."
        )
    for t, (rr, ss, bb) in seen.items():
        if expect in t:
            print(f"      판본 {len(seen)}종 관측 → expect 로 채택 ({sha1(t)[:8]})")
            return rr, ss, bb, t
    raise RuntimeError(
        f"{page['id']}: {VARIANT_TRIES}회 받았는데 expect(\"{expect}\")가 든 판본이 한 번도 안 왔습니다.\n"
        f"  원본이 실제로 바뀌었을 수 있습니다. data/variants/{page['id']}_*.txt 확인 후 expect 를 갱신하세요."
    )


def crawl(page, session, force=False):
    meta_path = DATA / "meta" / f"{page['id']}.json"
    if meta_path.exists() and not force:
        return "skip"

    r, soup, body, text = render_stable(page, session)
    html = r.text
    content_type = classify(body)
    meta = {
        "page_id": page["id"],
        "parent_doc_id": page["id"],
        "business_function": page["business"],
        "sub_category": page["sub_category"],
        "title": page["title"],
        "summary": page["summary"],
        "source_url": page["url"],
        "host": urlparse(page["url"]).netloc,
        "breadcrumb": extract_breadcrumb(soup, page),
        "required": page["required"],
        "note": page["note"],
        "content_type": content_type,
        "ingest": content_type in ("content", "search_ui"),
        "collected_at": now_iso(),
        "http_status": r.status_code,
        "raw_sha1": sha1(html),
        "content_sha1": sha1(text),
        "char_count": len(text),
        "table_count": len(body.find_all("table")),
        "image_count": len(body.find_all("img")),
        "attachments": extract_attachments(body, html),
        "external_links": extract_external_links(body, page["url"]),
    }

    (DATA / "raw_html" / f"{page['id']}.html").write_text(html, encoding="utf-8")
    (DATA / "text" / f"{page['id']}.txt").write_text(text, encoding="utf-8")
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return f"{len(text):>5}자  {content_type:<14} 첨부{len(meta['attachments']):>2}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ids", nargs="*", help="특정 page_id 만 (미지정 시 전체)")
    ap.add_argument("--force", action="store_true", help="meta 가 있어도 재수집")
    args = ap.parse_args()

    for d in ("raw_html", "text", "meta"):
        (DATA / d).mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    targets = [p for p in PAGES if not args.ids or p["id"] in args.ids]
    for p in targets:
        status = crawl(p, session, args.force)
        print(f"[{p['id']:<13}] {status}")
        if status != "skip":
            time.sleep(DELAY_SEC)


def _selftest():
    """table_to_md 회귀 검사. python3 crawler.py --selftest"""
    def md(html):
        return table_to_md(BeautifulSoup(html, "lxml").find("table"))

    shell = """<table><tr><th>회수기여도</th><th>포상금</th><th>원천징수</th><th>실지급액</th></tr>
    <tr><td>100%</td><td>0</td><td>0</td><td>0</td></tr>
    <tr><td>90%</td><td>0</td><td>0</td><td>0</td></tr></table>"""
    assert md(shell) == "", md(shell)

    merged = """<table><tr><th>구분</th><th>내용</th></tr>
    <tr><td colspan="2">1억원 이하 예금자는 계속 거래하실 수 있습니다.</td></tr></table>"""
    assert "1억원 이하 예금자는 계속 거래하실 수 있습니다." in md(merged), md(merged)

    real = """<table><tr><th>권역</th><th>신규</th><th>해산</th></tr>
    <tr><td>은행</td><td>0</td><td>1</td></tr></table>"""
    assert "| 은행 | 0 | 1 |" in md(real), md(real)

    print("selftest OK — 빈 계산기 표 버림 / colspan 병합 행 살림 / 0 인 실제 값 살림")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
        sys.exit(0)
    main()