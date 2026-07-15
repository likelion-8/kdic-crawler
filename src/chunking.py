"""검색 단위(unit) 구성 — baseline(통짜 페이지) vs 처치(FAQ QA쌍 분할)의 A/B용.

build_units(mode)는 (unit_ids, texts, unit2page)를 반환한다. 검색기는 unit 단위로 색인하고,
평가는 unit2page로 페이지 단위로 접어 채점하므로 baseline과 지표가 그대로 비교된다.

FAQ 탐지는 '질문'/'답변' 마커 규칙(하드코딩 ID 아님) — 재수집으로 새 FAQ가 와도 자동 대응.

실행(자가검증): python3 src/chunking.py
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "data" / "corpus.jsonl"


def load_records():
    return [json.loads(l) for l in open(CORPUS)]


def is_faq(text):
    """FAQ 아코디언 구조 페이지 — '질문'/'답변' 마커가 각 2회 이상 반복."""
    return text.count("질문") >= 2 and text.count("답변") >= 2


def split_faq(text):
    """'질문' 마커 경계로 QA쌍 분할. 첫 '질문' 앞 서문(페이지 안내)은 별도 청크로 유지."""
    parts = re.split(r"(?=질문)", text)
    return [p.strip() for p in parts if p.strip()]


def is_table(text):
    """표 페이지 — 행 구분자 ' | ' 20개 이상."""
    return text.count(" | ") >= 20


def split_table(text, rows_per_chunk=3):
    """표를 행묶음 청크로 분할. 각 청크에 컬럼 헤더를 반복해 self-describing 하게 만든다.
    3행/청크는 실측 sweet spot — 꼬리 표 질문 AnswerRecall 1.0 달성하면서 유닛 폭증은 억제."""
    lines = text.split("\n")
    pipe_idx = [i for i, l in enumerate(lines) if " | " in l]
    if not pipe_idx:
        return [text]
    header_i = pipe_idx[0]
    header = lines[header_i]
    intro = "\n".join(lines[:header_i]).strip()
    rows = [lines[i] for i in pipe_idx[1:]]  # 데이터 행(헤더 제외)
    chunks = []
    for g in range(0, len(rows), rows_per_chunk):
        parts = ([intro] if g == 0 and intro else []) + [header] + rows[g:g + rows_per_chunk]
        chunks.append("\n".join(parts))
    return chunks or [text]


def build_units(mode):
    """mode: 'page' | 'faq_atomic'(FAQ만 QA쌍) | 'table_row'(표만 행묶음) | 'all'(FAQ+표).
    반환: (unit_ids, texts, unit2page)."""
    unit_ids, texts, unit2page = [], [], {}
    for d in load_records():
        pid, text = d["page_id"], d["text"]
        if mode in ("faq_atomic", "all") and is_faq(text):
            chunks = split_faq(text)
        elif mode in ("table_row", "all") and is_table(text):
            chunks = split_table(text)
        else:
            chunks = [text]
        for i, ch in enumerate(chunks):
            uid = pid if len(chunks) == 1 else f"{pid}#{i}"
            unit_ids.append(uid)
            texts.append(ch)
            unit2page[uid] = pid
    return unit_ids, texts, unit2page


def _selftest():
    ids_p, txt_p, u2p_p = build_units("page")
    assert len(ids_p) == 58 and all(u == p for u, p in u2p_p.items()), "page 모드는 페이지=유닛"

    ids_f, txt_f, u2p_f = build_units("faq_atomic")
    # faq_nramt(질문 10개)는 서문 없이 10 QA쌍으로 쪼개져야 한다
    nramt = [u for u in ids_f if u2p_f[u] == "faq_nramt"]
    assert len(nramt) == 10, f"faq_nramt 청크 {len(nramt)}개 (기대 10)"
    # 비FAQ 페이지는 통짜 유지 (분할 안 됨)
    assert sum(1 for u in ids_f if u2p_f[u] == "dp_protlmts") == 1, "비FAQ는 통짜"
    assert len(ids_f) > 58, f"유닛 {len(ids_f)}개 (58보다 커야)"

    ids_t, _, u2p_t = build_units("table_row")
    # 파산재단 표(493행)는 여러 청크로, 각 청크에 헤더 반복
    bkrp = [u for u in ids_t if u2p_t[u] == "uc_bkrp_mng"]
    assert len(bkrp) > 5, f"uc_bkrp_mng 표청크 {len(bkrp)}개 (여러 개여야)"

    ids_a, _, _ = build_units("all")
    print(f"selftest ok — page:58 / faq_atomic:{len(ids_f)} / table_row:{len(ids_t)} "
          f"/ all:{len(ids_a)} 유닛 (faq_nramt {len(nramt)}청크, uc_bkrp_mng 표 {len(bkrp)}청크)")


if __name__ == "__main__":
    _selftest()
