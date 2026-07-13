"""data/raw_html/*.html → data/text/*.txt 일괄 변환 (네트워크 불필요).

이미 수집해 둔 원본 HTML을 inventory.PAGES 기준으로 전부 텍스트로 변환한다.
변환 로직은 crawler_dy.html_to_text 재사용 (결정론적, 표는 '|' 구분 행으로 보존).

실행:
  python3 src/parse_raw_html.py
"""
from pathlib import Path

from crawler_dy import html_to_text
from inventory import PAGES

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw_html"
TEXT = ROOT / "data" / "text"

# 사이트 공통 UI 노이즈 — 라인 전체가 정확히 일치할 때만 제거 (paser_hw의 NOISE_EXACT 확장판).
# kdic.or.kr 본사이트와 fins.kdic.or.kr 금융안심포털의 헤더/푸터/퀵메뉴 잔여물.
NOISE_EXACT = {
    "글자", "크기", "글자확대", "글자축소", "KOR", "ENG", "인쇄", "공유하기",
    "상단으로 이동", "창립 30주년 예금보험공사 디지털역사관 바로가기",
    "똑똑한 예보챗봇비서", "예솜이", "에게 물어보세요",
    "KDIC(예금보험공사)", "공식", "홈페이지", "KDIC(예금보험공사) 금융안심포털",
    "앱 설치", "QR 코드",
}


def strip_noise(text):
    return "\n".join(line for line in text.split("\n") if line.strip() not in NOISE_EXACT)


def read_html(path):
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:  # 일부 크롤러는 응답 바이트를 그대로 저장했다
        return path.read_text(encoding="cp949")


def run():
    TEXT.mkdir(parents=True, exist_ok=True)
    done, missing = 0, []
    for p in PAGES:
        src = RAW / f"{p['id']}.html"
        if not src.exists():
            missing.append(p["id"])
            continue
        text = strip_noise(html_to_text(read_html(src)))
        (TEXT / f"{p['id']}.txt").write_text(text, encoding="utf-8")
        done += 1
        print(f"[{p['id']}] {len(text):,}자")
    if missing:
        print(f"⚠ 원본 HTML 없음 ({len(missing)}건): {', '.join(missing)}")
    print(f"완료: {done}/{len(PAGES)}건 → data/text/")


if __name__ == "__main__":
    run()
