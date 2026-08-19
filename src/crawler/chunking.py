"""검색 단위(unit) 구성 — baseline(통짜 페이지) vs 처치(FAQ QA쌍 분할)의 A/B용.

build_units(mode)는 (unit_ids, texts, unit2page)를 반환한다. 검색기는 unit 단위로 색인하고,
평가는 unit2page로 페이지 단위로 접어 채점하므로 baseline과 지표가 그대로 비교된다.

FAQ 탐지는 '질문'/'답변' 마커 규칙(하드코딩 ID 아님) — 재수집으로 새 FAQ가 와도 자동 대응.

실행(자가검증): python3 src/crawler/chunking.py
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
CORPUS = ROOT / "data" / "corpus.jsonl"


def load_records():
    # encoding 명시 필수 — 미지정 시 윈도우 기본(cp949)이 UTF-8 한글을 못 읽는다.
    with open(CORPUS, encoding="utf-8") as f:
        return [json.loads(l) for l in f]


def is_faq(text):
    """FAQ 아코디언 구조 페이지 — '질문'/'답변' 마커가 각 2회 이상 반복."""
    return text.count("질문") >= 2 and text.count("답변") >= 2


def split_faq(text):
    """'질문' 마커 경계로 QA쌍 분할. 첫 '질문' 앞 서문(페이지 안내)은 별도 청크로 유지.

    경계는 '질문'으로 시작하는 줄 앞으로 한정한다(^ 앵커). 앵커 없는 (?=질문)은 답변
    본문 속 "…라는 질문에 대해" 같은 중간 등장에서도 잘라, 문장이 두 동강 난 청크가
    색인됐다(2026-08-14 실측 3곳: dp_gudn_faq·faq_msdr_apply·faq_top10)."""
    parts = re.split(r"(?m)^(?=질문)", text)
    return [p.strip() for p in parts if p.strip()]


def is_table(text):
    """표 페이지 — 행 구분자 ' | ' 20개 이상."""
    return text.count(" | ") >= 20


def split_table(text, rows_per_chunk=3):
    """표를 '연속된 pipe-행 블록' 단위로 나누고, 블록마다 자기 헤더를 반복해 self-describing
    하게 만든다. 블록 직전의 비-표 라인(표 제목·설명)은 그 블록의 첫 청크에 붙이고, 마지막
    표 뒤 잔여 텍스트(주석·각주)는 별도 청크로 배출한다 — 어떤 라인도 색인에서 사라지지
    않는다(_selftest 불변식으로 강제).

    2026-08-14 재작성. 구버전은 페이지에 표가 하나라고 가정해 첫 pipe행을 전체 헤더로
    삼았는데, 표 페이지 12곳 중 8곳이 다중 표였다 — 뒤 표들의 행이 남의 헤더를 달고
    (컬럼 수가 다른 이종 표 3곳은 헤더-값 대응 파괴), 뒤 표의 진짜 헤더는 데이터 행으로
    매몰되고, 첫 헤더 이후 비-표 라인 82줄(ha_center 42줄 포함)이 어느 청크에도 안 들어
    갔다. Balanced Hard71 표 문항 실패의 상당수가 이 청크 품질과 연결된다.

    헤더가 같은 연속 블록(페이지네이션 이어짐, uc_bkrp_mng 등)도 병합하지 않는다 —
    같은 헤더가 한 번 더 반복될 뿐 해가 없고, 병합하면 블록 사이 텍스트의 소속이
    모호해진다. 3행/청크는 기존 실측 sweet spot 그대로 유지."""
    lines = text.split("\n")
    # 위에서 아래로 라인을 (텍스트 구간 | 연속 pipe 블록)으로 묶는다
    segs = []  # [(kind, [line, ...])], kind: "table" | "text"
    for line in lines:
        kind = "table" if " | " in line else "text"
        if segs and segs[-1][0] == kind:
            segs[-1][1].append(line)
        else:
            segs.append((kind, [line]))

    chunks = []
    pending = []  # 다음 표 블록의 제목·설명이 될 텍스트 라인들
    for kind, seg in segs:
        if kind == "text":
            pending.extend(seg)
            continue
        header, rows = seg[0], seg[1:]
        # strip("\n")만 쓴다 — .strip()은 첫 줄의 들여쓰기까지 지워 원문 라인 보존이 깨진다
        intro = "\n".join(pending).strip("\n")
        pending = []
        if not rows:  # 행 없는 홑 pipe행 — 헤더만이라도 보존
            chunks.append((intro + "\n" if intro.strip() else "") + header)
            continue
        for g in range(0, len(rows), rows_per_chunk):
            parts = ([intro] if g == 0 and intro.strip() else []) + [header] + rows[g:g + rows_per_chunk]
            chunks.append("\n".join(parts))
    tail = "\n".join(pending).strip("\n")
    if tail.strip():  # 마지막 표 뒤 주석·각주도 버리지 않는다
        chunks.append(tail)
    return chunks or [text]


def build_units(mode):
    """mode: 'page' | 'faq_atomic'(FAQ만 QA쌍) | 'table_row'(표만 행묶음) | 'all'(FAQ+표).
    반환: (unit_ids, texts, unit2page).

    2026-08-19: 모든 유닛 앞에 [page_title · business_function] 프리픽스를 붙인다
    (contextual retrieval의 결정론 버전). 제목·업무가 DB 컬럼에만 있고 색인엔 통째로
    빠져 있어("보호한도" 페이지 본문에 그 단어가 없음), 특히 본문에 주제 신호가 없는
    300자 미만 청크 161/503개가 검색에 안 걸렸다. A/B 실측(eval_prefix_embedding,
    testset_retrieval_eval_v1 66문항): 새 실패 0 · 전체 R@5 0.955→1.0 · 전 서브셋
    MRR +0.06~0.07 · link_guide 3문항 top5 진입(제목 토큰이 BM25 렉시컬 매칭에 직격).
    LLM 전달 텍스트에도 그대로 들어간다 — 색인용/전달용을 분리하지 않는 이유는 구현
    단순화 + top5에 여러 페이지가 섞일 때 생성 LLM의 출처 혼동 감소. 프리픽스는 라인
    추가가 아니라 첫 라인 앞 연장이라 _selftest의 원문 유실 불변식(부분문자열 검사)과
    충돌하지 않는다. 분할 자체는 안 건드리므로 unit_id도 불변."""
    unit_ids, texts, unit2page = [], [], {}
    for d in load_records():
        pid, text = d["page_id"], d["text"]
        prefix = f"[{d['page_title']} · {d['business_function']}] "
        if mode in ("faq_atomic", "all") and is_faq(text):
            chunks = split_faq(text)
        elif mode in ("table_row", "all") and is_table(text):
            chunks = split_table(text)
        else:
            chunks = [text]
        for i, ch in enumerate(chunks):
            uid = pid if len(chunks) == 1 else f"{pid}#{i}"
            unit_ids.append(uid)
            texts.append(prefix + _faq_format(ch))
            unit2page[uid] = pid
    return unit_ids, texts, unit2page


# ── FAQ 청크 포맷 B+C (2026-08-19, exp/faq-chunk-format-ab 실측 채택) ─────────────
# 청크에 박힌 원문 질문과 사용자 질문의 문구 대조로 패러프레이즈가 거절되는 문제
# (eval_faq_chunk_format.py 4변형 실측: B 프리펜드 + C 열기제거 결합이 가까운 패러프레이즈를
# 거절 0/4 로 반전 + 원문 유출 0. D 재라벨링은 전패 폐기). 검색 순위는 pgvector(기존 임베딩)
# 기준이라 재적재 전에는 생성 전달 텍스트에만 반영된다 — 색인까지 반영하려면 재적재
# (인덱스 게이트 통과) 필요.
# '열기'는 아코디언 크롤링 아티팩트라 지우는 것이 유실이 아니라 정제다 — _selftest 의
# 라인 보존 불변식에는 ARTIFACT_LINES 예외로 등록돼 있다(불변식 자체는 유지 — 85줄
# 유실 사고 재발 방지 장치이므로 없애지 않는다).
_FAQ_QA_RE = re.compile(r"질문\n(?:\d+\.\s*)?.+?\n열기\n답변\n", re.DOTALL)
_FAQ_FRAMING = "아래는 이 주제에 대해 자주 묻는 질문과 그 답변입니다.\n"


def _faq_format(ch):
    """FAQ 꼴 청크에 프레이밍 한 줄을 얹고(B), 아코디언 잔재 '열기'를 지운다(C)."""
    framed = (_FAQ_FRAMING + ch) if _FAQ_QA_RE.search(ch) else ch
    return framed.replace("\n열기\n", "\n")


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

    # 다중 표 구조(2026-08-14): 각 블록은 자기 헤더·직전 제목을 갖고, 표 경계를 넘는 청크가
    # 없으며, 마지막 표 뒤 텍스트도 청크로 남는다.
    sample = ("서문\nA | B\n1 | 2\n3 | 4\n5 | 6\n7 | 8\n"
              "표2 제목\nC | D | E\n9 | 10 | 11\n꼬리 주석")
    sc = split_table(sample, rows_per_chunk=3)
    t2 = [c for c in sc if "9 | 10 | 11" in c]
    assert len(t2) == 1 and "C | D | E" in t2[0] and "표2 제목" in t2[0] \
        and "A | B" not in t2[0], f"표2 청크가 자기 헤더·제목을 갖지 못함: {sc}"
    assert any(c.strip() == "꼬리 주석" for c in sc), f"표 뒤 텍스트 유실: {sc}"

    # 유실 0 불변식(2026-08-14): 어떤 모드에서도 원문의 비어있지 않은 라인은 반드시 어느
    # 청크엔가 그대로 존재한다. 구버전 split_table은 all 기준 15페이지 85줄을 색인에서
    # 잃었다(표 사이 제목·표 아래 주석 — ha_center 42줄). 이 검사가 재발을 막는다.
    #
    # 아티팩트 예외(2026-08-19): 크롤링 잔재로 확인된 라인은 '유실'이 아니라 '정제'이므로
    # 면제한다. 현재 '열기' 하나 — 아코디언 버튼 텍스트가 본문에 섞인 것으로, FAQ 청크
    # B+C 포맷(_faq_format)이 의도적으로 지운다. 예외는 정확히 아는 아티팩트만 하나씩
    # 추가한다 — 목록을 넓게 잡거나 검사를 없애면 85줄 유실 사고가 재발해도 못 잡는다.
    ARTIFACT_LINES = {"열기"}
    originals = {d["page_id"]: d["text"] for d in load_records()}
    for mode in ("page", "faq_atomic", "table_row", "all"):
        uids_m, texts_m, u2p_m = build_units(mode)
        per_page = {}
        for u, t in zip(uids_m, texts_m):
            per_page.setdefault(u2p_m[u], []).append(t)
        for pid, orig in originals.items():
            joined = "\n".join(per_page[pid])
            lost = [l for l in orig.split("\n")
                    if l.strip() and l.strip() not in ARTIFACT_LINES and l not in joined]
            assert not lost, f"[{mode}] {pid} 원문 라인 {len(lost)}줄 유실: {lost[:2]}"

    ids_a, _, _ = build_units("all")
    print(f"selftest ok — page:58 / faq_atomic:{len(ids_f)} / table_row:{len(ids_t)} "
          f"/ all:{len(ids_a)} 유닛 (faq_nramt {len(nramt)}청크, uc_bkrp_mng 표 {len(bkrp)}청크) "
          f"— 전 모드 원문 라인 유실 0 확인")


if __name__ == "__main__":
    _selftest()
