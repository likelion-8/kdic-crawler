"""착오송금(Mistaken Remittance) 도메인 원본 HTML 크롤러.

예금보험공사(KDIC) RAG 챗봇 데이터 파이프라인의 1단계 스크립트.
PAGES에 등록된 각 URL의 원본 HTML을 data/raw_html/{id}.html 로 저장하고,
챗봇이 사용자에게 "위치"를 안내해줄 수 있도록 아래 항목을 data/media_summary_jh.json 으로 별도 추출한다.
  - videos: 페이지 내 안내영상 URL
  - attachments: 정적 <a href> 로 걸린 첨부파일(.hwp/.pdf/.doc/.xls/.zip) 링크
  - external_links: 국가법령정보센터(law.go.kr) 등 kdic.or.kr 외부로 나가는 링크
  - form_attachments: JS 버튼(gfn_downloadFile 등)으로 다운로드되는 첨부. 라벨과
    함께 재현 가능한 다운로드 레시피(엔드포인트 + POST 인자)를 남긴다.
  - embedded_documents: 레이어 팝업(fn_layer)으로 페이지 안에 숨겨진 규정 전문 등

각 항목은 사이트 공통 헤더/푸터/전체메뉴(모든 페이지에 반복되는 노이즈)를 피하기 위해
페이지 본문 영역(class="contents")으로 범위를 한정해서 추출한다.

본문 텍스트 파싱(청킹용)은 이 스크립트의 범위가 아니며 다음 단계 스크립트에서 처리한다.
텍스트 추출/가공에는 LLM을 사용하지 않고 BeautifulSoup 규칙 기반으로만 처리한다.
"""

import json
import re
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

# 크롤 대상 페이지 목록은 코드가 아니라 팀 통합 inventory.py에서 관리한다.
# 페이지를 추가/제외할 때 이 파일을 건드리지 않고 inventory.py만 편집하면 된다.
from inventory import pages_for

PAGES = pages_for("jh")

RAW_HTML_DIR = Path("data/raw_html")
MEDIA_SUMMARY_PATH = Path("data/media_summary_jh.json")

REQUEST_DELAY_SECONDS = 1
REQUEST_TIMEOUT_SECONDS = 15

HEADERS = {
    "User-Agent": (
        "KDIC-RAG-Crawler/1.0 (Educational Project; "
        "https://github.com/; contact: gx0929@gmail.com)"
    )
}

MEDIA_LINK_EXTENSIONS = (".mp4",)
ATTACHMENT_EXTENSIONS = (".hwp", ".pdf", ".doc", ".xls", ".zip")

# 본문 영역을 감싸는 컨테이너. 이 범위 밖(전체메뉴/푸터 등)은 모든 페이지에 반복되는
# 사이트 공통 요소라 노이즈이므로 링크/버튼 추출 대상에서 제외한다.
CONTENT_CONTAINER_SELECTOR = ".contents"

# 사이트 자체 도메인. 이 도메인으로 가는 링크는 "외부 링크"로 취급하지 않는다.
SITE_DOMAIN = "kdic.or.kr"
# 콘텐츠상 의미 없는 보일러플레이트 외부 링크(뷰어 안내, 사이트 전역 홍보 배너 등)는
# external_links에서 제외한다. kdic30th.kr은 kmrs_* 4개 페이지에 동일하게 박혀있는
# 창립 30주년 홍보 배너로, 착오송금 본문 내용과 무관해 제외 대상에 추가함.
EXTERNAL_LINK_EXCLUDE_DOMAINS = ("acrobat.adobe.com", "kdic30th.kr")

# 신청서/동의서 등 첨부파일이 JS 버튼(예: gfn_downloadFile)으로 다운로드되는 경우,
# onclick 속성에 이 키워드가 포함되어 있으면 "다운로드 버튼"으로 인식한다.
DOWNLOAD_ONCLICK_KEYWORD = "downloadFile"

# gfn_downloadFile(암호화 경로, 암호화 파일명)의 실제 다운로드 엔드포인트.
# 사이트 공통 JS(dev_pjm.js)가 이 URL로 두 인자를 JSON body에 담아 POST 한다.
# 인자는 암호화돼 있지만 HTML에 정적으로 박혀 있고 세션과 무관하게 유효하다(실측:
# 저장해 둔 HTML의 토큰으로 부채증명원 발급신청서.hwp 다운로드 성공, 2026-07-14).
DOWNLOAD_FILE_ENDPOINT = "/cm/file/downloadFile.do"
DOWNLOAD_FILE_ARGS_PATTERN = re.compile(
    r"gfn_downloadFile\(\s*'([^']+)'\s*,\s*'([^']+)'\s*\)"
)

# 엑셀표 등 동적 생성 파일 버튼: onclick="excelDown()" 류의 페이지 로컬 함수가
# gfn_downloadCustom("<엔드포인트>", {}, "<메서드>") 를 호출한다. 인라인 <script>에서
# 함수명 → (엔드포인트, 메서드) 매핑을 복원한다.
DOWNLOAD_CUSTOM_FN_PATTERN = re.compile(
    r"function\s+(\w+)\s*\([^)]*\)\s*\{[^{}]*?"
    r"gfn_downloadCustom\(\s*[\"']([^\"']+)[\"']\s*,\s*\{\}\s*,\s*[\"'](\w+)[\"']",
    re.S,
)
LOCAL_FN_CALL_PATTERN = re.compile(r"(?:javascript:)?\s*(\w+)\(\)")

# 레이어 팝업(예: 관련법령 및 규정 페이지의 규정 전문)을 여는 onclick 패턴.
LAYER_TRIGGER_PATTERN = re.compile(r"fn_layer\(\s*['\"]([^'\"]+)['\"]")

# 로그인/본인인증 수단 선택 버튼(금융인증서, 간편인증-카카오톡/KB국민은행/통신사패스/
# 삼성패스, 공동인증서 등)에 공통으로 붙는 클래스. 실제 인증 URL은 이니텍/간편인증
# SDK가 클릭 시점에 JS로 만들어내므로 정적 HTML에는 없고, 라벨만 존재한다.
LOGIN_OPTION_CLASSES = ("btnLoginSubmit", "simpleBtn")


def fetch_html(url: str) -> str:
    """주어진 URL의 원본 HTML 텍스트를 가져온다. 실패 시 예외를 그대로 전파한다.

    KDIC 사이트는 모든 페이지가 <meta charset="UTF-8">을 명시하는데, apparent_encoding
    (chardet 휴리스틱)이 이를 오판해 mojibake를 낸 사례가 있어 utf-8을 직접 지정한다.
    """
    response = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT_SECONDS)
    response.raise_for_status()
    response.encoding = "utf-8"
    return response.text


def save_raw_html(page_id: str, html: str) -> Path:
    RAW_HTML_DIR.mkdir(parents=True, exist_ok=True)
    output_path = RAW_HTML_DIR / f"{page_id}.html"
    output_path.write_text(html, encoding="utf-8")
    return output_path


def get_main_content(soup: BeautifulSoup, page_id: str):
    """사이트 공통 전체메뉴/푸터 노이즈를 피하기 위한 본문 영역을 반환한다.

    본문 컨테이너를 찾지 못하면 문서 전체를 대상으로 삼되, 그 사실을 콘솔에 경고로 남긴다
    (수천 개의 사이트 공통 링크가 섞여 들어갈 수 있음을 사용자가 알 수 있도록).
    """
    content = soup.select_one(CONTENT_CONTAINER_SELECTOR)
    if content is None:
        print(
            f"  [WARN] {page_id}: 본문 영역({CONTENT_CONTAINER_SELECTOR})을 찾지 못해 "
            "문서 전체를 대상으로 추출합니다 (사이트 공통 메뉴 노이즈가 섞일 수 있음)"
        )
        return soup
    return content


def extract_videos(content: BeautifulSoup, base_url: str) -> list:
    """<video>, <source> 태그 및 .mp4로 끝나는 <a> 링크에서 영상 URL을 추출한다."""
    video_urls = []

    for tag in content.find_all(["video", "source"]):
        src = tag.get("src")
        if src:
            video_urls.append(urljoin(base_url, src))

    for tag in content.find_all("a", href=True):
        href = tag["href"]
        if href.lower().split("?")[0].endswith(MEDIA_LINK_EXTENSIONS):
            video_urls.append(urljoin(base_url, href))

    seen = set()
    unique_video_urls = []
    for url in video_urls:
        if url not in seen:
            seen.add(url)
            unique_video_urls.append(url)

    return unique_video_urls


def extract_attachments(content: BeautifulSoup, base_url: str) -> list:
    """.hwp/.pdf/.doc/.xls/.zip 로 끝나는 <a> 링크와 링크 텍스트를 추출한다."""
    attachments = []
    seen = set()

    for tag in content.find_all("a", href=True):
        href = tag["href"]
        if href.lower().split("?")[0].endswith(ATTACHMENT_EXTENSIONS):
            absolute_url = urljoin(base_url, href)
            if absolute_url in seen:
                continue
            seen.add(absolute_url)
            attachments.append(
                {
                    "url": absolute_url,
                    "text": tag.get_text(strip=True),
                }
            )

    return attachments


def _find_nearby_heading(tag, max_depth: int = 4):
    """링크 주변 <strong> 텍스트를 찾아 "이 링크가 무엇에 대한 것인지" 문맥을 보강한다."""
    parent = tag.parent
    depth = 0
    while parent is not None and depth < max_depth:
        strong = parent.find("strong")
        if strong:
            text = strong.get_text(strip=True)
            if text:
                return text
        parent = parent.parent
        depth += 1
    return None


def extract_external_links(content: BeautifulSoup, base_url: str) -> list:
    """kdic.or.kr 이외 도메인으로 나가는 <a href> 링크(국가법령정보센터 등)를 추출한다."""
    links = []
    seen = set()

    for tag in content.find_all("a", href=True):
        href = tag["href"]
        if not href.startswith("http"):
            continue

        netloc = urlparse(href).netloc.lower()
        if SITE_DOMAIN in netloc:
            continue
        if any(excluded in netloc for excluded in EXTERNAL_LINK_EXCLUDE_DOMAINS):
            continue
        if href in seen:
            continue
        seen.add(href)

        links.append(
            {
                "url": href,
                "text": tag.get_text(strip=True),
                "context": _find_nearby_heading(tag),
            }
        )

    return links


def extract_form_attachments(content: BeautifulSoup, page_url: str) -> list:
    """JS 다운로드 버튼(gfn_downloadFile / gfn_downloadCustom 경유)을 추출한다.

    onclick 인자가 암호화돼 있어도 다운로드는 재현 가능하다: 공통 JS가
    DOWNLOAD_FILE_ENDPOINT 로 두 인자를 JSON body에 담아 POST 할 뿐이다.
    그 레시피(resolved_url + download_method + download_params)를 함께 남겨서
    챗봇이 페이지 안내는 물론 파일 위치까지 제공할 수 있게 한다.
    엑셀표 같은 동적 생성 파일 버튼(excelDown() → gfn_downloadCustom)도 같은
    방식으로 엔드포인트를 복원한다.
    """
    results = []

    # 인라인 <script>의 로컬 함수명 → (엔드포인트, 메서드) 매핑 (엑셀 다운로드 등)
    custom_downloads = {}
    for script in content.find_all("script"):
        for m in DOWNLOAD_CUSTOM_FN_PATTERN.finditer(script.get_text()):
            custom_downloads[m.group(1)] = (m.group(2), m.group(3))

    # 다운로드 호출은 <button onclick> 또는 <a href="javascript:gfn_downloadFile(...)">
    # (게시판 상세 페이지) 양쪽에 나타난다.
    for button in content.find_all(["button", "a"]):
        onclick = " ".join(
            v for v in (button.get("onclick"), button.get("href")) if v
        )
        resolved_url = None
        download_method = None
        download_params = None

        args = DOWNLOAD_FILE_ARGS_PATTERN.search(onclick)
        local_call = LOCAL_FN_CALL_PATTERN.fullmatch(onclick.strip().rstrip(";") if onclick else "")
        if args:
            resolved_url = urljoin(page_url, DOWNLOAD_FILE_ENDPOINT)
            download_method = "POST"
            download_params = {
                "encAtchFilePathNm": args.group(1),
                "encOrgnlFileNm": args.group(2),
            }
        elif local_call and local_call.group(1) in custom_downloads:
            endpoint, method = custom_downloads[local_call.group(1)]
            resolved_url = urljoin(page_url, endpoint)
            download_method = method
            download_params = {}
        elif DOWNLOAD_ONCLICK_KEYWORD not in onclick:
            continue

        # 버튼 안에 "HWP"/"PDF" 아이콘용 <span>과 숨김 설명 <span class="hide">가 섞여
        # 있는 경우가 많아, 버튼 전체 텍스트를 모아서 앞의 아이콘 라벨만 제거한다.
        # (예: "HWP 신청서양식 다운로드" → "신청서양식 다운로드",
        #      "본인 신청서 샘플 다운로드"처럼 hide 스팬이 여러 개인 경우도 온전히 보존)
        label = button.get_text(separator=" ", strip=True)
        label = re.sub(r"^(HWP|PDF|DOC|XLS|ZIP)\s+", "", label, flags=re.IGNORECASE)

        file_type = None
        for class_name in button.get("class", []):
            lowered = class_name.lower()
            if lowered.startswith("ico") and lowered != "icon":
                file_type = lowered[3:]
                break

        entry = {
            "label": label,
            "file_type": file_type,
            "page_url": page_url,
            "resolved_url": resolved_url,
        }
        if resolved_url:
            entry["download_method"] = download_method
            entry["download_params"] = download_params
        results.append(entry)

    return results


def extract_login_options(content: BeautifulSoup, page_url: str) -> list:
    """금융인증서/간편인증/공동인증서 등 로그인 수단 선택 버튼을 추출한다.

    카카오톡·KB국민은행·통신사PASS·삼성패스 같은 간편인증 수단과 공동인증서/금융인증서는
    href가 전부 "javascript:void(0)"이고 실제 인증 URL은 이니텍/간편인증 SDK가 클릭
    시점에 만들어내므로 정적 HTML로는 복원할 수 없다. 대신 "이 페이지(page_url)에 이런
    로그인 수단이 있다"는 라벨 목록을 남겨서, 챗봇이 최소한 어느 페이지로 안내해야
    하는지는 알 수 있게 한다.
    """
    results = []
    seen = set()

    for tag in content.find_all("a", href=True):
        href = tag["href"].strip()
        if not href.startswith("javascript:void(0)"):
            continue

        classes = tag.get("class", [])
        if not any(cls in LOGIN_OPTION_CLASSES for cls in classes):
            continue

        label = tag.get_text(strip=True)
        if not label or label in seen:
            continue
        seen.add(label)

        results.append(
            {
                "label": label,
                "provider": tag.get("data-logingubun"),
                "page_url": page_url,
                "resolved_url": None,
            }
        )

    return results


def extract_embedded_documents(soup: BeautifulSoup, content: BeautifulSoup) -> list:
    """레이어 팝업(fn_layer)으로 페이지 안에 숨겨진 문서 전문(규정 등)을 추출한다.

    "바로가기"가 외부 URL이 아니라 같은 HTML 안의 숨김 레이어를 여는 경우(착오송금
    반환지원 규정/시행세칙 등), 그 레이어 안의 제목과 전체 텍스트를 그대로 보존한다.
    """
    documents = []
    seen_ids = set()

    for tag in content.find_all(attrs={"onclick": True}):
        match = LAYER_TRIGGER_PATTERN.search(tag["onclick"])
        if not match:
            continue

        layer_id = match.group(1)
        if layer_id in seen_ids:
            continue
        seen_ids.add(layer_id)

        layer_div = soup.find(id=layer_id)
        if layer_div is None:
            continue

        title_tag = layer_div.find(class_="tit")
        title = title_tag.get_text(strip=True) if title_tag else layer_id

        documents.append(
            {
                "id": layer_id,
                "title": title,
                "text": layer_div.get_text(separator=" ", strip=True),
            }
        )

    return documents


def crawl_page(page: dict) -> dict:
    """단일 페이지를 크롤링한다. 성공 시 추출 결과를, 실패 시 예외를 발생시킨다."""
    html = fetch_html(page["url"])
    save_raw_html(page["id"], html)

    soup = BeautifulSoup(html, "html.parser")
    content = get_main_content(soup, page["id"])

    return {
        "videos": extract_videos(content, page["url"]),
        "attachments": extract_attachments(content, page["url"]),
        "external_links": extract_external_links(content, page["url"]),
        "form_attachments": extract_form_attachments(content, page["url"]),
        "login_options": extract_login_options(content, page["url"]),
        "embedded_documents": extract_embedded_documents(soup, content),
    }


def main() -> None:
    pages_to_process = []
    skipped_pages = []

    for page in PAGES:
        if page.get("url"):
            pages_to_process.append(page)
        else:
            skipped_pages.append(page)

    if skipped_pages:
        print(f"[SKIP] url이 비어있어 건너뛴 항목 {len(skipped_pages)}개:")
        for page in skipped_pages:
            print(f"  - {page.get('id', '(no id)')}: {page.get('title', '(no title)')}")

    media_summary = {}
    success_count = 0
    fail_count = 0
    total = len(pages_to_process)

    for index, page in enumerate(pages_to_process, start=1):
        page_id = page["id"]
        print(f"[{index}/{total}] 처리 중: {page_id} ({page['url']})")

        try:
            result = crawl_page(page)
            media_summary[page_id] = result
            success_count += 1
            print(
                f"[{index}/{total}] 완료: {page_id} "
                f"(videos={len(result['videos'])}, attachments={len(result['attachments'])}, "
                f"external_links={len(result['external_links'])}, "
                f"form_attachments={len(result['form_attachments'])}, "
                f"login_options={len(result['login_options'])}, "
                f"embedded_documents={len(result['embedded_documents'])})"
            )
        except Exception as error:
            fail_count += 1
            print(f"[{index}/{total}] 실패: {page_id} - {error}")
        finally:
            time.sleep(REQUEST_DELAY_SECONDS)

    MEDIA_SUMMARY_PATH.write_text(
        json.dumps(media_summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("\n===== 크롤링 요약 =====")
    print(f"성공: {success_count}건 / 실패: {fail_count}건 / 건너뜀(url 없음): {len(skipped_pages)}건")
    print(f"원본 HTML 저장 위치: {RAW_HTML_DIR}/")
    print(f"미디어 요약 저장 위치: {MEDIA_SUMMARY_PATH}")


if __name__ == "__main__":
    main()
