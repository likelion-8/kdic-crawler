"""data/raw_html/*.html → data/text/*.txt 일괄 변환 (네트워크 불필요).

이미 수집해 둔 원본 HTML을 inventory.PAGES 기준으로 전부 텍스트로 변환한다.
변환 로직은 crawler_dy.html_to_text 재사용 (결정론적, 표는 '|' 구분 행으로 보존).

실행:
  python3 src/crawler/parse_raw_html.py
"""
import re
from pathlib import Path

from crawler_dy import html_to_text
from inventory import PAGES

ROOT = Path(__file__).resolve().parent.parent.parent
RAW = ROOT / "data" / "raw_html"
PAGED = RAW / "paged"
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


# 뒷페이지 병합 시 데이터가 아닌 페이징 UI 라인. 뒷페이지에서 처음 등장해도
# (예: 2페이지부터 생기는 "첫 페이지" 버튼, 범위 초과 응답의 "현재 게시물이 없습니다.")
# 새 내용으로 치지 않는다.
PAGING_CHROME = {"첫 페이지", "이전 페이지", "다음 페이지", "마지막 페이지",
                 "현재 게시물이 없습니다."}


def is_paging_chrome(line):
    return line in PAGING_CHROME or line.isdigit()  # 숫자 단독 라인 = 페이지 번호


def drop_paging_cluster(text):
    """1페이지 본문에 박힌 페이지네이션 UI 묶음("1 2 3 4 5 다음 페이지 마지막 페이지")을 지운다.

    2026-08-26 추가. merge_paged 는 뒷페이지의 페이징 라인만 걸렀고 1페이지 것은 그대로
    뒀다. 그 7줄이 표의 1~10행과 뒷페이지에서 병합된 11행~ 사이에 끼어 표를 두 블록으로
    끊었고, chunking.split_table 은 블록마다 첫 줄을 헤더로 삼으므로 뒷블록의 첫 데이터
    행("11 | 상호저축은행 | 경기저축은행 | 남성모 …")이 헤더로 승격돼 그 페이지 청크
    161개 전부에 반복됐다(uc_bkrp_mng). dp_fnst_srch(93)·dp_prdct_srch(31)·
    ms_trgt_fnst(12)·dp_gudn_data(7)도 같은 모양 — 페이지네이션 표 전부다.

    숫자 단독 라인을 무조건 지우면 안 된다 — "전체 / 31 / 건"(dp_gudn_data 건수),
    절차 단계 번호("01","02" — ms_aply_proc) 같은 데이터가 있다. 그래서 '연속된 페이징
    후보 라인 묶음 가운데 단어형 버튼("다음 페이지" 등)을 하나라도 품은 묶음'만 지운다.
    페이지 번호는 항상 버튼과 붙어 나오고, 데이터 숫자는 버튼과 붙지 않는다(실측 전 페이지).
    """
    lines = text.split("\n")
    out, run = [], []
    def flush():
        if not any(l in PAGING_CHROME for l in run):
            out.extend(run)
        run.clear()
    for line in lines:
        if is_paging_chrome(line):
            run.append(line)
        else:
            flush()
            out.append(line)
    flush()
    return "\n".join(out)


def merge_paged(doc_id, text):
    """페이지네이션 뒷페이지(raw_html/paged/, fetch_extra.py 수집분)의 새 라인만 이어 붙인다.

    뒷페이지 HTML은 검색폼·안내문 등 페이지 공통부가 통째로 반복되므로,
    1페이지 텍스트에 없는 라인(표 행·FAQ 항목)만 골라 순서대로 덧붙인다.
    1페이지 본문의 페이징 UI 묶음은 먼저 지운다(drop_paging_cluster) — 안 지우면 표가
    거기서 끊겨 뒷페이지 행들이 헤더 없는 블록이 된다.
    """
    text = drop_paging_cluster(text)
    seen = set(text.split("\n"))
    extras = []
    for f in sorted(PAGED.glob(f"{doc_id}_p*.html"),
                    key=lambda p: int(re.search(r"_p(\d+)$", p.stem).group(1))):
        for line in strip_noise(html_to_text(read_html(f))).split("\n"):
            if line in seen or is_paging_chrome(line):
                continue
            seen.add(line)
            extras.append(line)
    return text + "\n" + "\n".join(extras) if extras else text


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
        text = merge_paged(p["id"], strip_noise(html_to_text(read_html(src))))
        (TEXT / f"{p['id']}.txt").write_text(text, encoding="utf-8")
        done += 1
        print(f"[{p['id']}] {len(text):,}자")
    if missing:
        print(f"⚠ 원본 HTML 없음 ({len(missing)}건): {', '.join(missing)}")
    print(f"완료: {done}/{len(PAGES)}건 → data/text/")


if __name__ == "__main__":
    run()
