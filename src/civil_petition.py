"""민원 처리(신청) 의도 질문에 대한 3단계 응답 조립 — 절차 안내·서류 안내·페이지 연결.

intent=civil_petition으로 판별된 질문에서만 쓴다(informational은 근거 청크로 바로
답변하면 되고 이 3단계 조립이 필요 없다). 새로 검색하지 않는다 — 호출부(pipeline._answer_one
또는 api/rag/answer.prepare_sub)가 route_search_chunks → top_k_cut으로 이미 뽑아둔 근거
청크를 그대로 받아 용도별로 재가공만 한다. (그 사이에 rerank가 낄 수 있으나 현재
USE_RERANKER=False라 호출되지 않는다.)
"""
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
_page_docs = {}


def _load_page_docs():
    """page_id -> {attachments, form_attachments, business_function, page_title}. corpus.jsonl에서 한 번만 로드.

    이 필드들은 chunks_all.jsonl엔 없다(검색 색인에 불필요해 청크 단계에서 뺀 필드 —
    citation.py의 sub_category와 같은 이유). page_id로 corpus.jsonl을 되짚어 조회한다.
    """
    if not _page_docs:
        with open(ROOT / "data" / "corpus.jsonl", encoding="utf-8") as f:
            for line in f:
                d = json.loads(line)
                _page_docs[d["page_id"]] = {
                    "attachments": d.get("attachments", []),
                    "form_attachments": d.get("form_attachments", []),
                    "business_function": d.get("business_function"),
                    # 같은 URL 로 접힌 서류 묶음의 대표 이름으로 쓴다(build_document_section).
                    "page_title": d.get("page_title"),
                }
    return _page_docs


def _unique_page_ids(chunks):
    """chunks: [(chunk_id, score, text), ...]. page_id를 첫 등장 순서(=관련도 순)로 중복 제거."""
    seen = []
    for cid, _, _ in chunks:
        page_id = cid.split("#")[0]
        if page_id not in seen:
            seen.append(page_id)
    return seen


def _top_business(chunks):
    """top-1 페이지의 업무(business_function). **서류와 신청 링크가 같은 기준을 보게 하는
    단일 출처**다 — 종전에는 링크만 top-1 업무를 보고 서류는 top-k 전 페이지를 훑어서,
    한쪽은 착오송금인데 다른 쪽은 예금자보호 자료가 붙는 어긋남이 났다."""
    if not chunks:
        return None
    return _load_page_docs().get(chunks[0][0].split("#")[0], {}).get("business_function")


def build_procedure_section(chunks):
    """절차 안내(신청 대상·기한·단계). 근거 청크 본문을 그대로 이어붙인다 — 절차 정보는
    corpus에 별도 구조화 필드가 아니라 본문 텍스트 안에 이미 서술돼 있고(예: "1. 착오송금인은
    예금보험공사..."), 넘어온 청크가 이미 관련도순 상위 K_FINAL개이기 때문이다.
    (원래는 리랭커가 절차 청크를 상위로 올려준다는 전제였으나 현재 리랭커는 Off다.)"""
    return "\n\n".join(text for _, _, text in chunks)


def build_document_section(chunks):
    """서류 안내. 근거 청크가 속한 페이지들의 첨부·서식 다운로드 링크를 모은다.

    (label, url) 기준으로 중복을 제거한다 — corpus.jsonl의 form_attachments 자체에
    같은 서식이 중복 추출된 경우가 있어서(크롤러가 같은 JS 다운로드 버튼을 두 번 잡음,
    예: sender_docs 페이지 28건 중 16건 중복), 원본을 그대로 노출하면 같은 다운로드
    링크가 응답에 반복돼 보인다.

    2026-08-25: 그 위에 **URL 로 한 번 더 묶는다.** 아래 form_attachments 주석대로 서식
    링크를 page_url 로 대체하다 보니 한 페이지의 서식이 전부 같은 URL 이 되는데, 중복 제거
    키가 (label, url) 이라 라벨이 다르면 안 걸러졌다 — 화면에 같은 링크로 가는 카드가
    수십 장 쌓였다(실측: dp_gudn_data 29장, sender_docs 12장).

    다만 라벨을 버리지는 않는다. 이 섹션의 존재 이유가 "어떤 서류를 준비해야 하는지"를
    알려주는 것이라, 라벨이 실제 구비서류명인 페이지에서 그것을 페이지 제목으로 갈아치우면
    정보가 통째로 사라진다(sender_docs: 신청서양식 · 금융거래정보 제공 요구(동의)서 ·
    본인 신청서 샘플 …). 2건 이상이 묶일 때만 대표 이름을 page_title 로 두고 개별 서류명은
    labels 로 함께 넘긴다 — 호출부(웹 카드 부제 · CLI 한 줄)가 그것을 그린다.
    1건이면 종전과 똑같이 label 하나만 넘어간다(labels 없음).

    2026-08-26: **top-1 페이지의 업무에 속한 페이지만 본다**(_top_business). 검색 top5 에는
    다른 업무 페이지가 자주 섞이는데(testset intent=civil_petition 80건 실측 58.8%),
    종전에는 그 페이지의 서류까지 전부 걷어 왔다. 실물 두 가지 —
      · "예금보험금 위임장 양식은 어디서 다운로드 받나요?" → 안내자료 다운로드(예금자보호
        게시판) 공지 첨부 29건이 붙어 카드 부제가 1307자가 됐다.
      · "대리인이 예금보험금을 대신 수령하려면 어떤 서류가 필요한가요?" → 착오송금인
        구비서류 12건이 붙었다(길이 문제가 아니라 오답이다).
    80건 중 23건(28.7%)의 서류 섹션이 달라지고, 달라지는 방향은 전부 '다른 업무 서류가
    떨어져 나가는' 쪽이다. 적용 후 부제 최대 길이는 1307자 → 47자.
    (라벨 개수 상한은 두지 않았다 — 임의 임계값 없이 이 규칙만으로 길이가 정리된다.)"""
    docs = _load_page_docs()
    top_bf = _top_business(chunks)
    groups, order, seen = {}, [], set()

    def _collect(page_id, page_title, label, url):
        key = (label, url)
        if key in seen:
            return
        seen.add(key)
        if url not in groups:
            groups[url] = {"page_id": page_id, "page_title": page_title, "labels": []}
            order.append(url)
        groups[url]["labels"].append(label)

    for page_id in _unique_page_ids(chunks):
        d = docs.get(page_id, {})
        # top_bf 가 None 이면(메타 결손) 거르지 않는다 — 그 경우 신청 링크도 비어
        # build_civil_petition_answer 가 서류 섹션을 통째로 생략한다.
        if top_bf is not None and d.get("business_function") != top_bf:
            continue
        title = d.get("page_title")
        for a in d.get("attachments", []):
            _collect(page_id, title, a.get("text"), a.get("url"))
        for fa in d.get("form_attachments", []):
            # resolved_url은 실제 파일 링크가 아니라 자바스크립트 다운로드 버튼이 공통으로
            # 쓰는 POST 전용 서블릿 주소다(코퍼스 전체 103건이 단 3개 URL로 겹침 - 실제
            # 파일 식별은 암호화된 download_params를 POST 본문으로 같이 보내야 되는데
            # 여기선 그 값을 안 보낸다). 그대로 노출하면 클릭해도 다운로드가 안 되는 깨진
            # 링크가 되므로, 다운로드 버튼이 실제로 있는 페이지(page_url)를 안내한다.
            _collect(page_id, title, fa.get("label"), fa.get("page_url"))

    items = []
    for url in order:
        g = groups[url]
        base = {"page_id": g["page_id"], "url": url}
        if len(g["labels"]) == 1:
            items.append({**base, "label": g["labels"][0]})
        else:
            # page_title 이 없으면 첫 라벨을 대표로 쓴다 — 묶음이 이름을 잃지는 않게.
            items.append({**base, "label": g["page_title"] or g["labels"][0],
                          "labels": g["labels"]})
    return items


# 업무별 공식 신청 진입점 — 기획서 CB-003 마커 3 "실제 공식 신청 URL만 CTA로 제공" 구현.
# 종전에는 검색된 top 페이지 전부를 신청 페이지로 내보내 FAQ·유의사항까지 CTA 버튼이 되고
# 참고 출처와 중복됐다(2026-08-10 보고: 버튼 5개). 신청 진입점은 업무당 하나뿐이므로 corpus의
# 해당 페이지 URL로 고정한다. 예금자보호제도는 신청 개념이 없어 매핑하지 않는다(섹션 생략).
OFFICIAL_APPLY_LINKS = {
    "착오송금 반환 신청": {  # mtrs_stut_chc — kmrs_apply_mthd 본문의 '온라인 신청 사이트'
        "title": "착오송금 반환지원 온라인 신청",
        "url": "https://fins.kdic.or.kr/ir/aplygudn/MtrsStutChc/selectScrn.do",
        "breadcrumb": "소개와 방법안내 > 상황선택",
    },
    "고객 미수령금 신청": {  # uc_itgr_aply
        "title": "미수령금 통합신청",
        "url": "https://fins.kdic.or.kr/ua/aplygudn/NramtItgrAplyItrdMthdGudn/selectScrn.do",
        "breadcrumb": "미수령금통합신청 > 소개와 신청방법 안내",
    },
    "예금보험금 안내": {  # ms_aply_proc
        "title": "예금보험금 신청절차",
        "url": "https://www.kdic.or.kr/sp/dpstrprot/DpsmIbamtAplyProc/selectScrn.do",
        "breadcrumb": "예금보험금 신청 절차",
    },
    "채무조정 안내": {  # dr_info_aply
        "title": "채무정보 조회·상담신청",
        "url": "https://www.kdic.or.kr/rb/lbltajmt/LbltAjmtSprtLbltInfoInqDscsnAply/selectScrn.do",
        "breadcrumb": "채무정보 조회 및 상담신청",
    },
    "은닉재산 신고": {  # ha_center
        "title": "은닉재산 신고센터",
        "url": "https://www.kdic.or.kr/sp/sprtfund/SprtFndCncmDclrGudn/selectScrn.do",
        "breadcrumb": "금융부실관련자 은닉재산신고",
    },
}


def build_link_section(chunks):
    """신청 페이지 CTA — 가장 관련도 높은(top-1) 페이지의 업무에 해당하는 공식 신청 진입점
    **하나만** 돌려준다. 종전처럼 근거 페이지 전부를 CTA로 내보내지 않는다 — 근거 페이지
    목록은 참고 출처(sources)가 이미 보여준다."""
    link = OFFICIAL_APPLY_LINKS.get(_top_business(chunks))
    return [dict(link)] if link else []


def build_civil_petition_answer(chunks):
    """절차 -> 서류 -> 페이지 연결 3단계를 순서대로 조립한다.
    최종 문자열 포맷(마크다운 등)은 prompt_builder.py 책임으로 남긴다.

    2026-08-25: **신청 진입점이 없는 업무는 서류 섹션도 비운다.** OFFICIAL_APPLY_LINKS 에
    매핑이 없다는 것은 신청 개념 자체가 없다는 뜻이고(현재 그런 업무는 예금자보호제도
    하나뿐 — 한도 내 자동 보호라 신청 절차가 없다, src/clarify.py), 그런 질문에 구비서류가
    붙으면 본문("별도 절차 없이 자동으로 적용됩니다")과 정면으로 모순된다.

    실물: "예금자보호제도 신청은 어떻게 하나요?" 에 안내자료 다운로드 게시판(dp_gudn_data)
    의 공지 첨부 29건이 '필요 서류'로 붙었다 — 금융회사 실무자용 조사 통보·서식 변경
    공지였고 구비서류가 아니었다. links 가 비어 있다는 것이 이미 그 신호였다."""
    links = build_link_section(chunks)
    return {
        "procedure": build_procedure_section(chunks),
        "documents": build_document_section(chunks) if links else [],
        "links": links,
    }
