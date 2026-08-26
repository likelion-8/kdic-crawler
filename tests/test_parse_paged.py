"""뒷페이지 병합 시 1페이지 페이지네이션 UI 제거(parse_raw_html.drop_paging_cluster).

2026-08-26 사고: 1페이지 본문의 "1 2 3 4 5 다음 페이지 마지막 페이지"가 표의 1~10행과
뒷페이지에서 병합된 11행~ 사이에 남아 표를 두 블록으로 끊었고, split_table이 뒷블록의 첫
데이터 행을 헤더로 승격해 uc_bkrp_mng 청크 161개가 "11 | 상호저축은행 | 경기저축은행 …"을
헤더로 달았다. 이 테스트는 그 조건(페이징 묶음 제거 · 데이터 숫자 보존)을 고정한다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src" / "crawler"))

from parse_raw_html import drop_paging_cluster  # noqa: E402


def test_paging_cluster_between_table_rows_is_removed():
    text = "\n".join([
        "번호 | 회사명 | 진행",
        "10 | A | 진행",
        "1", "2", "3", "4", "5", "다음 페이지", "마지막 페이지",
        "11 | B | 진행",
    ])
    assert drop_paging_cluster(text).split("\n") == [
        "번호 | 회사명 | 진행", "10 | A | 진행", "11 | B | 진행",
    ]


def test_lone_numbers_that_are_data_survive():
    # dp_gudn_data "전체 / 31 / 건", ms_aply_proc 절차 번호 "01" "02" — 버튼 없이 나오는
    # 숫자 단독 라인은 데이터라 남겨야 한다.
    text = "전체\n31\n건\n01\n02\n본문"
    assert drop_paging_cluster(text) == text


def test_cluster_with_first_page_button_also_removed():
    text = "행 | 값\n첫 페이지\n이전 페이지\n3\n4\n다음 페이지\n꼬리"
    assert drop_paging_cluster(text) == "행 | 값\n꼬리"


def test_text_without_paging_is_unchanged():
    text = "안내\n1\n2\n표 | 값\n"
    assert drop_paging_cluster(text) == text
