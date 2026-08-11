"""신규 URL의 비영속 문서 Preview 파이프라인.

이 모듈은 URL을 받아 크롤링 -> 본문 파싱 -> 업무 분류 -> 기존 RAG 규칙 청킹을
수행하지만 파일이나 DB에는 아무것도 쓰지 않는다. 운영 반영은 별도의 변경 요청/재색인
흐름만 담당한다.
"""
from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass
from typing import Callable
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup, NavigableString

from crawler.chunking import is_faq, is_table, split_faq, split_table
from crawler.hashing import content_sha256


ALLOWED_HOSTS = frozenset({"www.kdic.or.kr", "fins.kdic.or.kr"})
MAX_REDIRECTS = 5
MAX_HTML_BYTES = 5 * 1024 * 1024
MIN_BODY_CHARS = 40
REQUEST_TIMEOUT = (5, 30)

# documents.source_url 은 길이 제한 없는 text 라 DB 가 막아 주지 않는다. 브라우저·서버가
# 실무에서 받아 주는 상한을 여기서 건다.
MAX_URL_LENGTH = 2048

# 🔴 kdic.or.kr 은 없는 주소를 두 가지로 처리한다. 실측:
#     /sp/dpstrprot/NoSuchScrn.do -> 404              (fetch_html 의 상태코드 검사로 잡힌다)
#     /no-such-page-xyz           -> 302 -> 200       (상태코드로는 못 잡는다. soft-404)
# 뒤쪽을 통과시키면 관리자는 등록에 성공했다고 믿는데, 실제로 청킹되는 본문은
# "## 연결 오류 / Page Not Found / 연결하려는 페이지에 문제가 있어서..." 다. 그대로 적재하면
# 오류 안내문이 검색 색인에 들어가 답변 근거로 쓰인다.
#
# 상태코드 말고 남은 신호는 본문뿐이라 그것을 본다. 아래 표지는 실제 오류 페이지에서 뽑았고,
# 사이트가 문구를 바꾸면 이 검사는 조용히 무력해진다(막지 못할 뿐, 정상 문서를 오탐하지는 않는다).
ERROR_PAGE_TITLE_MARKERS = ("오류", "error")
ERROR_PAGE_BODY_MARKERS = ("page not found", "연결하려는 페이지에 문제가 있어")
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; KDIC-Knowledge-Preview/1.0; "
        "+https://www.kdic.or.kr/)"
    ),
    "Accept": "text/html,application/xhtml+xml",
}

BUSINESS_FUNCTIONS = (
    "예금자보호제도",
    "예금보험금 안내",
    "고객 미수령금 신청",
    "착오송금 반환 신청",
    "채무조정 안내",
    "은닉재산 신고",
)

BUSINESS_PREFIX = {
    "예금자보호제도": "dp",
    "예금보험금 안내": "ms",
    "고객 미수령금 신청": "uc",
    "착오송금 반환 신청": "kmrs",
    "채무조정 안내": "dr",
    "은닉재산 신고": "ha",
}

# 업무명 자체와 실제 코퍼스에서 반복되는 도메인 용어만 사용한다. 일반어인 '신청',
# '안내'는 분류 신호에서 제외해 신규 페이지가 특정 업무로 쏠리지 않게 한다.
_BUSINESS_KEYWORDS = {
    "예금자보호제도": {
        "예금자보호": 8,
        "예금보호": 7,
        "보호한도": 6,
        "보호대상 금융": 5,
        "부보금융회사": 4,
        "dpstrprot": 6,
    },
    "예금보험금 안내": {
        "예금보험금": 9,
        "보험금 지급": 6,
        "보험사고": 4,
        "가지급금": 6,
        "파산배당": 5,
    },
    "고객 미수령금 신청": {
        "미수령금": 9,
        "고객 미수령": 9,
        "찾아가지 않은": 5,
        "휴면예금": 4,
    },
    "착오송금 반환 신청": {
        "착오송금": 9,
        "반환지원": 7,
        "잘못 송금": 5,
        "송금인": 3,
        "수취인": 3,
    },
    "채무조정 안내": {
        "채무조정": 9,
        "채무감면": 6,
        "상환유예": 5,
        "신용회복": 5,
        "부실차주": 4,
    },
    "은닉재산 신고": {
        "은닉재산": 9,
        "부실관련자": 6,
        "재산 신고": 5,
        "신고포상": 6,
        "포상금": 3,
    },
}


class PreviewError(Exception):
    """Preview 단계에서 예상 가능한 오류."""

    retryable = False

    def __init__(self, user_message: str):
        self.user_message = user_message
        super().__init__(user_message)


class PreviewUrlError(PreviewError):
    """URL 형식이나 수집 정책 위반."""


class PreviewFetchError(PreviewError):
    """허용 URL이지만 원격 문서를 가져오지 못함."""

    retryable = True


class PreviewParseError(PreviewError):
    """HTML에서 유효한 본문을 만들지 못함."""


@dataclass(frozen=True)
class FetchedPage:
    url: str
    html: str
    status_code: int
    content_type: str


@dataclass(frozen=True)
class ParsedDocument:
    title: str
    sub_category: str
    summary: str
    text: str
    table_count: int
    used_fallback_container: bool


def normalize_preview_url(raw_url: str) -> str:
    """허용 URL을 정규화한다.

    리다이렉트마다 같은 검사를 다시 적용하므로 허용 호스트에서 내부망/외부 호스트로
    튀는 SSRF 우회도 차단한다.
    """
    value = raw_url.strip()
    # 양끝 공백은 붙여넣기 흔적이라 위에서 잘라내고, 가운데 남은 공백류는 거른다.
    # ord < 32 만 보면 일반 공백(U+0020)과 줄바꿈 없는 공백(U+00A0)이 통과하는데, 후자는
    # 웹페이지에서 URL 을 복사할 때 실제로 섞여 들어온다. 살려 두면 인코딩 과정에서 같은
    # 주소가 다른 문자열이 되어 뒤쪽 중복 검사가 헛돈다.
    if not value or any(ord(ch) < 32 or ch.isspace() for ch in value):
        raise PreviewUrlError("올바른 URL을 입력해 주세요.")
    if len(value) > MAX_URL_LENGTH:
        raise PreviewUrlError(f"URL이 너무 깁니다. {MAX_URL_LENGTH}자 이내로 입력해 주세요.")

    try:
        parts = urlsplit(value)
        port = parts.port
        host = (parts.hostname or "").lower().rstrip(".")
    except ValueError as exc:
        raise PreviewUrlError("올바른 URL을 입력해 주세요.") from exc

    if parts.scheme.lower() != "https":
        raise PreviewUrlError("HTTPS 주소만 수집할 수 있습니다.")
    if parts.username is not None or parts.password is not None:
        raise PreviewUrlError("사용자 정보가 포함된 URL은 수집할 수 없습니다.")
    if host not in ALLOWED_HOSTS:
        raise PreviewUrlError("수집 허용 목록(kdic.or.kr)에 없는 주소입니다. 등록할 수 없습니다.")
    if port not in (None, 443):
        raise PreviewUrlError("기본 HTTPS 포트가 아닌 주소는 수집할 수 없습니다.")

    path = parts.path or "/"
    return urlunsplit(("https", host, path, parts.query, ""))


def _decode_response(body: bytes, response: requests.Response) -> str:
    encoding = response.encoding
    if not encoding or encoding.lower() == "iso-8859-1":
        # stream=True 응답은 iter_content 소비 뒤 response.apparent_encoding이 다시
        # response.content를 읽으려 할 수 있다. HTML 앞부분의 charset을 직접 보고,
        # KDIC 현행 기본인 UTF-8로 폴백한다.
        charset = re.search(br"charset\s*=\s*['\"]?([a-zA-Z0-9._-]+)", body[:4096], re.I)
        encoding = charset.group(1).decode("ascii", errors="ignore") if charset else "utf-8"
    try:
        return body.decode(encoding, errors="replace")
    except LookupError:
        return body.decode("utf-8", errors="replace")


def fetch_html(url: str, *, session: requests.Session | None = None) -> FetchedPage:
    """HTML을 크기 제한 안에서 가져오고 모든 리다이렉트 목적지를 검증한다."""
    current = normalize_preview_url(url)
    http = session or requests.Session()

    for redirect_count in range(MAX_REDIRECTS + 1):
        try:
            response = http.get(
                current,
                headers=HEADERS,
                timeout=REQUEST_TIMEOUT,
                allow_redirects=False,
                stream=True,
            )
        except requests.Timeout as exc:
            raise PreviewFetchError("원문 서버 응답이 지연되고 있습니다. 잠시 후 다시 시도해 주세요.") from exc
        except requests.RequestException as exc:
            raise PreviewFetchError("URL에 접근할 수 없습니다. 주소와 원문 서버 상태를 확인해 주세요.") from exc

        try:
            if response.status_code in (301, 302, 303, 307, 308):
                location = response.headers.get("Location")
                if not location:
                    raise PreviewFetchError("원문 서버의 이동 응답에 목적지 주소가 없습니다.")
                if redirect_count >= MAX_REDIRECTS:
                    raise PreviewFetchError("URL 이동 횟수가 너무 많아 수집을 중단했습니다.")
                current = normalize_preview_url(urljoin(current, location))
                continue

            if response.status_code in (404, 410):
                raise PreviewUrlError("존재하지 않거나 삭제된 URL입니다.")
            if response.status_code >= 400:
                raise PreviewFetchError(
                    f"원문 서버가 HTTP {response.status_code}로 응답했습니다. 잠시 후 다시 시도해 주세요."
                )

            content_type = response.headers.get("Content-Type", "").lower()
            if content_type and not any(t in content_type for t in ("text/html", "application/xhtml+xml")):
                raise PreviewUrlError("HTML 문서만 미리보기할 수 있습니다.")

            length = response.headers.get("Content-Length")
            if length:
                try:
                    if int(length) > MAX_HTML_BYTES:
                        raise PreviewUrlError("원문 HTML이 5MB를 초과해 미리보기할 수 없습니다.")
                except ValueError:
                    pass

            chunks: list[bytes] = []
            size = 0
            for block in response.iter_content(chunk_size=64 * 1024):
                if not block:
                    continue
                size += len(block)
                if size > MAX_HTML_BYTES:
                    raise PreviewUrlError("원문 HTML이 5MB를 초과해 미리보기할 수 없습니다.")
                chunks.append(block)
            body = b"".join(chunks)
            if not body:
                raise PreviewParseError("원문 응답에 내용이 없습니다.")
            return FetchedPage(
                url=current,
                html=_decode_response(body, response),
                status_code=response.status_code,
                content_type=content_type,
            )
        finally:
            response.close()

    raise PreviewFetchError("URL 이동 횟수가 너무 많아 수집을 중단했습니다.")


def _clean_line(value: str) -> str:
    return re.sub(r"[ \t\xa0]+", " ", value).strip()


def _table_to_text(table) -> str:
    rows = []
    for tr in table.find_all("tr"):
        cells = [_clean_line(cell.get_text(" ", strip=True)) for cell in tr.find_all(["th", "td"])]
        if any(cells):
            rows.append(" | ".join(cells))
    return "\n".join(rows)


def _meta_content(soup: BeautifulSoup, *selectors: str) -> str:
    for selector in selectors:
        node = soup.select_one(selector)
        if node:
            value = node.get("content")
            if isinstance(value, str) and value.strip():
                return _clean_line(value)
    return ""


def _extract_title(soup: BeautifulSoup) -> str:
    title = _meta_content(soup, 'meta[property="og:title"]', 'meta[name="twitter:title"]')
    if not title:
        # 현행 kdic.or.kr은 문서 제목을 .pageTit > h2에 두고, 첫 h1은 기관 로고다.
        heading = soup.select_one(".pageTit > h1, .pageTit > h2, .page-title > h1, .page-title > h2")
        if heading is None:
            heading = next(
                (node for node in soup.select("h1") if "logo" not in (node.get("class") or [])),
                None,
            )
        title = _clean_line(heading.get_text(" ", strip=True)) if heading else ""
    if not title and soup.title:
        title = _clean_line(soup.title.get_text(" ", strip=True))
    # 브라우저 제목의 기관명 꼬리만 제거한다. 일반 제목 안의 '-'는 보존한다.
    title = re.sub(r"\s*[|｜]\s*(KDIC\s*)?예금보험공사.*$", "", title, flags=re.I).strip()
    return title


def _extract_breadcrumb(soup: BeautifulSoup) -> str:
    # 현행 KDIC 위치표시는 각 단계의 현재값을 .ulSelectBox 직계 a에 두고, 같은 div의
    # ul에는 전체 메뉴를 넣는다. li.get_text()를 쓰면 전체 메뉴가 브레드크럼에 섞인다.
    current_location = [
        _clean_line(node.get_text(" ", strip=True))
        for node in soup.select(".location .ulSelectBox > a")
    ]
    current_location = [item for item in current_location if item and item != "제도·정책"]
    if current_location:
        return " > ".join(current_location)

    selectors = (
        "nav[aria-label*=breadcrumb]",
        ".breadcrumb",
        ".breadcrumbs",
        ".location",
        ".path",
    )
    for selector in selectors:
        node = soup.select_one(selector)
        if not node:
            continue
        items = [_clean_line(n.get_text(" ", strip=True)) for n in node.select("li")]
        if not items:
            raw = _clean_line(node.get_text(" > ", strip=True))
            items = [_clean_line(part) for part in re.split(r"\s*(?:>|›|/|≫)\s*", raw)]
        cleaned = []
        for item in items:
            item = re.sub(r"^(현재\s*위치|HOME|홈)\s*[:>]?[ ]*", "", item, flags=re.I).strip()
            if item and item not in cleaned:
                cleaned.append(item)
        if cleaned:
            return " > ".join(cleaned)
    return ""


def _collapse_text(text: str) -> str:
    lines = []
    blank = False
    for raw in text.replace("\r\n", "\n").split("\n"):
        line = _clean_line(raw)
        if not line:
            if lines and not blank:
                lines.append("")
            blank = True
            continue
        lines.append(line)
        blank = False
    return "\n".join(lines).strip()


def looks_like_error_page(title: str, text: str) -> bool:
    """200 을 받았지만 실은 오류 안내문인 페이지(soft-404)인지.

    제목만으로는 부족하다 — _extract_title() 이 "오류 | KDIC 예금보험공사"의 접미사를 떼어
    "오류"로 만들기도 하고, soft-404 쪽은 "연결 오류"라 형태가 다르다. 그래서 제목에 표지가
    있거나, 본문 앞부분에 오류 안내 문구가 있으면 오류 페이지로 본다.

    본문은 앞부분만 본다. 정상 문서에도 "오류"라는 낱말이 본문 중간에 나올 수 있어서,
    페이지 전체를 훑으면 멀쩡한 안내 문서를 오탐한다.
    """
    head = title.strip().lower()
    if any(marker in head for marker in ERROR_PAGE_TITLE_MARKERS):
        return True
    body_head = text[:200].lower()
    return any(marker in body_head for marker in ERROR_PAGE_BODY_MARKERS)


def parse_document(html: str, source_url: str) -> ParsedDocument:
    """사이트 크롬을 제거하고 표/헤딩 구조를 보존한 본문과 메타데이터를 만든다."""
    soup = BeautifulSoup(html, "html.parser")
    title = _extract_title(soup)
    sub_category = _extract_breadcrumb(soup)
    summary = _meta_content(soup, 'meta[name="description"]', 'meta[property="og:description"]')

    main = (
        soup.select_one("#contents")
        or soup.select_one("div.contents")
        or soup.select_one("main")
        or soup.select_one('[role="main"]')
        or soup.select_one("article")
    )
    used_fallback = main is None
    main = main or soup.body or soup

    for tag in list(main.select("script, style, noscript, header, footer, nav, aside")):
        tag.decompose()
    for tag in list(main.select('[aria-hidden="true"]')):
        tag.decompose()

    tables = list(main.find_all("table"))
    for table in tables:
        table_text = _table_to_text(table)
        table.replace_with(NavigableString(f"\n{table_text}\n" if table_text else ""))

    for heading in list(main.select("h1, h2, h3, h4, h5, h6, dt")):
        heading_text = _clean_line(heading.get_text(" ", strip=True))
        if heading_text:
            heading.replace_with(NavigableString(f"\n## {heading_text}\n"))

    text = _collapse_text(main.get_text("\n", strip=True))
    if len(text) < MIN_BODY_CHARS:
        raise PreviewParseError("본문을 충분히 추출하지 못했습니다. 페이지 구조나 접근 권한을 확인해 주세요.")
    if not title:
        title = next((line.removeprefix("## ") for line in text.splitlines() if line), "제목 없음")[:200]
    # HTTP 200 이어도 내용이 오류 안내문이면 수집 대상이 아니다(위 ERROR_PAGE_* 주석 참고).
    # 본문을 다 만든 뒤에 보는 이유는, 제목이 비어 첫 줄에서 채워지는 경우까지 함께 걸러야 해서다.
    if looks_like_error_page(title, text):
        raise PreviewUrlError("존재하지 않거나 이동된 URL입니다. 대상 사이트가 오류 안내 페이지를 보여 줍니다.")
    if not summary:
        summary_text = re.sub(r"\s+", " ", text.replace("## ", "")).strip()
        summary = summary_text[:240]

    return ParsedDocument(
        title=title,
        sub_category=sub_category,
        summary=summary,
        text=text,
        table_count=len(tables),
        used_fallback_container=used_fallback,
    )


def _business_scores(*, title: str, sub_category: str, text: str, url: str) -> dict[str, int]:
    prominent = f"{title}\n{sub_category}".lower()
    body = text[:12000].lower()
    address = unquote(url).lower()
    scores = {}
    for business, keywords in _BUSINESS_KEYWORDS.items():
        score = 0
        for keyword, weight in keywords.items():
            key = keyword.lower()
            score += min(prominent.count(key), 2) * weight * 3
            score += min(body.count(key), 3) * weight
            score += min(address.count(key), 2) * weight * 2
        scores[business] = score
    return scores


def decide_business_function(
    *,
    title: str,
    sub_category: str,
    text: str,
    url: str,
    requested: str | None,
) -> tuple[str, str | None]:
    """업무를 결정하고, 사람 지정값과 강한 자동 후보가 다르면 경고를 돌려준다."""
    if requested is not None and requested not in BUSINESS_FUNCTIONS:
        raise PreviewUrlError("지원하지 않는 업무 분류입니다.")

    scores = _business_scores(title=title, sub_category=sub_category, text=text, url=url)
    candidate, candidate_score = max(scores.items(), key=lambda item: item[1])
    if requested:
        requested_score = scores[requested]
        warning = None
        if candidate != requested and candidate_score >= max(18, requested_score + 8):
            warning = (
                f"선택한 업무는 '{requested}'이지만 본문 기준 자동 분류 후보는 "
                f"'{candidate}'입니다. 적재 전에 업무를 확인해 주세요."
            )
        return requested, warning
    if candidate_score < 6:
        raise PreviewParseError("본문에서 업무 분류를 결정하지 못했습니다. 업무를 직접 선택해 주세요.")
    return candidate, None


def generate_page_id(url: str, business_function: str) -> str:
    """업무 접두어 + URL 주제 토큰으로 수정 가능한 page_id 초안을 만든다."""
    parts = urlsplit(url)
    path_parts = [unquote(part) for part in parts.path.split("/") if part]
    raw_slug = "_".join(path_parts[-3:])
    raw_slug = re.sub(r"\.[a-z0-9]+$", "", raw_slug, flags=re.I)
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", raw_slug).strip("_").lower()
    if not slug or slug in {"selectscrn", "index", "main"}:
        slug = "page"
    slug = slug[:36].rstrip("_")
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:8]
    return f"{BUSINESS_PREFIX[business_function]}_{slug}_{digest}"


def _chunk_title(text: str) -> str:
    value = next((line.removeprefix("## ").strip() for line in text.splitlines() if line.strip()), "본문")
    value = re.sub(r"\s+", " ", value)
    return value if len(value) <= 60 else value[:59] + "…"


def chunk_document(page_id: str, text: str) -> tuple[list[dict[str, object]], str]:
    """운영 색인과 같은 FAQ/표 규칙으로 Preview 청크를 만든다."""
    if is_faq(text):
        texts = split_faq(text)
        split_rule = "FAQ 질문·답변 쌍으로 분할"
    elif is_table(text):
        texts = split_table(text)
        split_rule = "표 헤더를 포함한 3행 단위로 분할"
    else:
        texts = [text]
        split_rule = "본문 구조 기준으로 분할"

    chunks = []
    multiple = len(texts) > 1
    for seq, chunk_text in enumerate(texts):
        chunk_id = f"{page_id}#{seq}" if multiple else page_id
        chunks.append(
            {
                "chunk_id": chunk_id,
                "page_id": page_id,
                "seq": seq,
                "title": _chunk_title(chunk_text),
                "chars": len(chunk_text),
                # 화면은 CSS로 두 줄만 보여주지만 응답에는 전체 청크를 담아 개발자 도구나
                # 후속 UI에서 파싱 결과 전문을 검토할 수 있게 한다.
                "preview": chunk_text,
            }
        )
    return chunks, split_rule


FetchCallable = Callable[[str], FetchedPage]


def build_document_preview(
    *,
    url: str,
    business_function: str | None = None,
    page_title: str = "",
    sub_category: str = "",
    summary: str = "",
    fetcher: FetchCallable = fetch_html,
) -> dict[str, object]:
    """Preview 전 과정을 실행하고 API 응답으로 직렬화 가능한 dict를 반환한다."""
    normalized_url = normalize_preview_url(url)
    fetched = fetcher(normalized_url)
    final_url = normalize_preview_url(fetched.url)
    parsed = parse_document(fetched.html, final_url)

    effective_title = page_title.strip() or parsed.title
    effective_sub_category = sub_category.strip() or parsed.sub_category
    effective_summary = summary.strip() or parsed.summary
    selected_business, classification_warning = decide_business_function(
        title=effective_title,
        sub_category=effective_sub_category,
        text=parsed.text,
        url=final_url,
        requested=business_function,
    )
    page_id = generate_page_id(final_url, selected_business)
    chunks, split_rule = chunk_document(page_id, parsed.text)

    warnings = []
    if classification_warning:
        warnings.append(classification_warning)
    if not effective_sub_category:
        warnings.append("본문에서 하위분류를 추출하지 못했습니다. 적재 전에 직접 입력해 주세요.")
    if parsed.table_count:
        warnings.append(f"본문에서 표를 {parsed.table_count}개 발견했습니다. 청킹 결과를 확인해 주세요.")
    if parsed.used_fallback_container:
        warnings.append("전용 본문 영역을 찾지 못해 페이지 전체에서 본문을 추출했습니다.")

    return {
        "preview_id": f"pv_{uuid.uuid4().hex}",
        "url": final_url,
        "extracted": {
            "page_id": page_id,
            "page_title": effective_title,
            "business_function": selected_business,
            "sub_category": effective_sub_category,
            "summary": effective_summary,
            "content_sha256": content_sha256(parsed.text),
        },
        "split_rule": split_rule,
        "chunks": chunks,
        "warnings": warnings,
        "sub_category_extraction_failed": not bool(effective_sub_category),
    }
