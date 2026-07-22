"""
채무조정 관련 8개 페이지의 원본 HTML을 저장합니다.

실행:
    python crawl_debt_adjustment_raw_html.py

출력:
    data/raw_html/DEBT-001.html
    ...
    data/raw_html/DEBT-008.html

    data/responses/debt_adjustment/DEBT-001.json
    ...
    data/manifests/debt_adjustment_fetch_manifest.csv

주의:
- HTML 응답 바이트를 그대로 저장합니다.
- 본문 파싱, 텍스트 변환, 청킹은 하지 않습니다.
"""

from __future__ import annotations

import csv
import hashlib
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

RAW_HTML_DIR = PROJECT_ROOT / "data" / "raw_html"
RESPONSE_DIR = PROJECT_ROOT / "data" / "responses" / "debt_adjustment"
MANIFEST_PATH = (
    PROJECT_ROOT
    / "data"
    / "manifests"
    / "debt_adjustment_fetch_manifest.csv"
)

REQUEST_TIMEOUT_SECONDS = 30
REQUEST_DELAY_SECONDS = 1.5

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/150.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}

PAGES = [
    {
        "doc_id": "DEBT-001",
        "title": "채무조정제도",
        "business_function": "채무조정 안내",
        "sub_category": "채무조정제도",
        "url": (
            "https://www.kdic.or.kr/rb/lbltajmt/"
            "LbltAjmtSprtLbltAjmtSyst/selectScrn.do"
        ),
    },
    {
        "doc_id": "DEBT-002",
        "title": "채무정보 조회 ＆ 상담신청",
        "business_function": "채무조정 안내",
        "sub_category": "채무정보 조회 및 상담신청",
        "url": (
            "https://www.kdic.or.kr/rb/lbltajmt/"
            "LbltAjmtSprtLbltInfoInqDscsnAply/selectScrn.do"
        ),
    },
    {
        "doc_id": "DEBT-003",
        "title": "채무조정",
        "business_function": "채무조정 안내",
        "sub_category": "KR&C 채무조정",
        "url": (
            "https://www.kdic.or.kr/di/relsite/"
            "PbcrKrncLblarb/selectScrn.do"
        ),
    },
    {
        "doc_id": "DEBT-004",
        "title": "신용회복 지원",
        "business_function": "채무조정 안내",
        "sub_category": "신용회복 지원",
        "url": (
            "https://www.kdic.or.kr/rb/lbltajmt/"
            "LbltAjmtSprtCredRcvrySprt/selectScrn.do"
        ),
    },
    {
        "doc_id": "DEBT-005",
        "title": "파산면책",
        "business_function": "채무조정 안내",
        "sub_category": "파산면책",
        "url": (
            "https://www.kdic.or.kr/rb/lbltajmt/"
            "LbltAjmtSprtPsnBr/selectScrn.do"
        ),
    },
    {
        "doc_id": "DEBT-006",
        "title": "개인회생",
        "business_function": "채무조정 안내",
        "sub_category": "개인회생",
        "url": (
            "https://www.kdic.or.kr/rb/lbltajmt/"
            "LbltAjmtSprtPsnRg/selectScrn.do"
        ),
    },
    {
        "doc_id": "DEBT-007",
        "title": "부채증명원/금융거래정보신청",
        "business_function": "채무조정 안내",
        "sub_category": "부채증명원 및 금융거래정보신청",
        "url": (
            "https://www.kdic.or.kr/sp/sprtfund/"
            "SprtFndDebtDlngAplyGudn/selectScrn.do"
        ),
    },
    {
        "doc_id": "DEBT-008",
        "title": "채무정보조회 FAQ",
        "business_function": "채무조정 안내",
        "sub_category": "채무정보조회 FAQ",
        "url": "https://fins.kdic.or.kr/cm/bbs/selectFaqLbltInfoInq.do",
    },
]


def build_session() -> requests.Session:
    retry = Retry(
        total=3,
        connect=3,
        read=3,
        status=3,
        backoff_factor=1.0,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET",),
        raise_on_status=False,
    )

    adapter = HTTPAdapter(max_retries=retry)

    session = requests.Session()
    session.headers.update(HEADERS)
    session.mount("https://", adapter)
    session.mount("http://", adapter)

    return session


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def detect_content_status(content: bytes) -> str:
    if not content:
        return "EMPTY"

    preview = content[:200_000].decode("utf-8", errors="ignore")

    block_phrases = (
        "서비스 접속이 차단 되었습니다",
        "현재 접속하신 아이피에서는 접속이 불가능합니다",
        "Access Denied",
        "Request blocked",
    )

    if any(phrase in preview for phrase in block_phrases):
        return "BLOCK_PAGE"

    return "HTML_SAVED"


def response_headers_to_dict(response: requests.Response) -> dict[str, str]:
    return {str(key): str(value) for key, value in response.headers.items()}


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def main() -> int:
    RAW_HTML_DIR.mkdir(parents=True, exist_ok=True)
    RESPONSE_DIR.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)

    session = build_session()
    rows: list[dict[str, Any]] = []

    success_count = 0
    warning_count = 0
    failed_count = 0

    print(f"수집 대상: {len(PAGES)}건")
    print(f"HTML 저장: {RAW_HTML_DIR}")
    print()

    for index, page in enumerate(PAGES, start=1):
        doc_id = page["doc_id"]
        url = page["url"]

        html_path = RAW_HTML_DIR / f"{doc_id}.html"
        response_path = RESPONSE_DIR / f"{doc_id}.json"
        fetched_at = datetime.now().astimezone().isoformat(timespec="seconds")

        print(f"[{index}/{len(PAGES)}] {doc_id} - {page['title']}")

        row: dict[str, Any] = {
            "doc_id": doc_id,
            "title": page["title"],
            "business_function": page["business_function"],
            "sub_category": page["sub_category"],
            "requested_url": url,
            "final_url": "",
            "http_status": "",
            "request_success": False,
            "content_status": "",
            "content_type": "",
            "encoding": "",
            "byte_size": 0,
            "sha256": "",
            "fetched_at": fetched_at,
            "raw_html_path": str(html_path.relative_to(PROJECT_ROOT)),
            "response_metadata_path": str(
                response_path.relative_to(PROJECT_ROOT)
            ),
            "error_type": "",
            "error_message": "",
        }

        try:
            response = session.get(
                url,
                timeout=REQUEST_TIMEOUT_SECONDS,
                allow_redirects=True,
            )

            raw_bytes = response.content
            content_status = detect_content_status(raw_bytes)

            # HTTP 응답 원본 바이트를 수정하지 않고 저장합니다.
            html_path.write_bytes(raw_bytes)

            row.update(
                {
                    "final_url": response.url,
                    "http_status": response.status_code,
                    "request_success": response.ok and bool(raw_bytes),
                    "content_status": content_status,
                    "content_type": response.headers.get(
                        "Content-Type", ""
                    ),
                    "encoding": (
                        response.encoding
                        or response.apparent_encoding
                        or ""
                    ),
                    "byte_size": len(raw_bytes),
                    "sha256": sha256_bytes(raw_bytes),
                }
            )

            metadata = {
                **row,
                "response_headers": response_headers_to_dict(response),
                "redirect_history": [
                    {
                        "status_code": history.status_code,
                        "url": history.url,
                        "location": history.headers.get("Location"),
                    }
                    for history in response.history
                ],
            }
            write_json(response_path, metadata)

            if row["request_success"] and content_status == "HTML_SAVED":
                success_count += 1
                print(
                    f"  저장 완료: {len(raw_bytes):,} bytes, "
                    f"HTTP {response.status_code}"
                )
            else:
                warning_count += 1
                print(
                    f"  경고: HTTP {response.status_code}, "
                    f"content_status={content_status}"
                )

        except Exception as exc:
            failed_count += 1
            row.update(
                {
                    "content_status": "FAILED",
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                }
            )
            write_json(response_path, row)
            print(f"  실패: {type(exc).__name__}: {exc}")

        rows.append(row)

        if index < len(PAGES):
            time.sleep(REQUEST_DELAY_SECONDS)

    fieldnames = [
        "doc_id",
        "title",
        "business_function",
        "sub_category",
        "requested_url",
        "final_url",
        "http_status",
        "request_success",
        "content_status",
        "content_type",
        "encoding",
        "byte_size",
        "sha256",
        "fetched_at",
        "raw_html_path",
        "response_metadata_path",
        "error_type",
        "error_message",
    ]

    with MANIFEST_PATH.open(
        "w",
        encoding="utf-8-sig",
        newline="",
    ) as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print()
    print(
        f"완료: 정상 {success_count}, 경고 {warning_count}, "
        f"실패 {failed_count}"
    )
    print(f"Manifest: {MANIFEST_PATH}")

    return 0 if failed_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
