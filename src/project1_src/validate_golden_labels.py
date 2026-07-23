"""골든 라벨(테스트셋) 자체의 품질 자동 검증 — must_include가 실제 expected_sources 페이지에
있는지, expected_sources/expected_links가 corpus.jsonl에 실제 존재하는지 대조한다.

evaluate_pipeline.py는 "우리 챗봇이 골든 라벨 기준으로 잘 답하는지"를 보는 도구이고,
이 스크립트는 반대로 "골든 라벨 자체가 맞는지"를 본다 — 챗봇 답변은 전혀 안 만든다(HCX 호출 없음,
빠름). must_include 표기가 실제 정답 페이지와 정말 일치하는지 확인해, 튜닝 실험의 기준이 되는
골든셋 자체의 결함(오타·잘못된 page_id·깨진 링크)을 먼저 걸러낸다.

첫 버전은 text/source_url만 봐서 오탐이 많았다(2026-07-23) — must_include·expected_links가
실제로는 links[].url, videos, attachments/form_attachments, page_title에 들어있는 경우가
많은데 그걸 안 봐서였다(예: ha_center_q3·dr_info_aply_q1·kmrs_itrd_q7·mtrs_rel_law_q9는
전부 links[]/videos에 정확히 있었는데 "깨짐"으로 오판됨). 그래서 페이지당 검색 가능한 모든
필드를 모은 haystack으로 확장했다.

정규화(_normalize)는 evaluate_pipeline.py 것을 그대로 재사용한다 — 공백·날짜 표기차이로 인한
오탐을 같은 기준으로 걸러야 두 도구의 결과가 어긋나지 않는다.

실행: python3 src/project1_src/validate_golden_labels.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
TESTSET = ROOT / "data" / "testset" / "testset_all.jsonl"
CORPUS = ROOT / "data" / "corpus.jsonl"


def load_corpus():
    pages = {}
    with open(CORPUS, encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            pages[d["page_id"]] = d
    return pages


def load_testset():
    with open(TESTSET, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def page_haystack(p):
    """must_include 검색 대상 - 본문뿐 아니라 사람이 실제로 읽을 수 있는 모든 텍스트/URL을 합친다
    (제목·링크 텍스트/URL·첨부파일 라벨·영상 URL). 근거가 이 중 어디에 있어도 '진짜 있음'으로 친다."""
    parts = [p.get("text", ""), p.get("page_title", "")]
    for l in p.get("links", []):
        parts += [l.get("text", ""), l.get("url", "")]
    for a in p.get("attachments", []):
        parts += [a.get("text", ""), a.get("url", "")]
    for fa in p.get("form_attachments", []):
        parts += [fa.get("label", ""), fa.get("page_url", ""), fa.get("resolved_url", "")]
    parts += p.get("videos", [])
    return "\n".join(str(x) for x in parts if x)


def page_urls(p):
    """expected_links 검증 대상 - 이 페이지 자신의 주소뿐 아니라 페이지 안에 실제로 걸린
    모든 링크(링크·첨부·영상)까지 '이 페이지가 정당하게 가리킬 수 있는 URL'로 인정한다."""
    urls = {p["source_url"]}
    urls |= {l.get("url") for l in p.get("links", []) if l.get("url")}
    urls |= {a.get("url") for a in p.get("attachments", []) if a.get("url")}
    for fa in p.get("form_attachments", []):
        urls |= {fa.get("page_url"), fa.get("resolved_url")}
    urls |= set(p.get("videos", []))
    return {u for u in urls if u}


def main():
    sys.path.insert(0, str(ROOT / "src"))
    from evaluate_pipeline import _normalize

    pages = load_corpus()
    rows = load_testset()

    # corpus 전체에서 어떤 URL이 어느 page_id에 "정당하게" 속하는지(자기 주소든 페이지 내
    # 링크든) - expected_links가 "다른 진짜 페이지"를 가리키는 건지 아예 없는 건지 구분용.
    url2page = {}
    for pid, p in pages.items():
        for u in page_urls(p):
            url2page.setdefault(u, pid)

    missing_page_ids = []      # expected_sources가 가리키는 page_id가 corpus에 없음(오타 등)
    must_include_misses = []   # must_include 문구가 expected_sources 어디에도(본문·링크·첨부) 없음
    link_broken = []           # expected_links가 corpus 어디에도 없는 URL(진짜 깨진/오타 링크)
    link_other_page = []       # expected_links가 corpus엔 있지만 expected_sources와 다른 page_id

    for d in rows:
        sources = d.get("expected_sources") or []
        must = d.get("must_include") or []
        links = d.get("expected_links") or []

        found_pages = []
        for pid in sources:
            if pid in pages:
                found_pages.append(pages[pid])
            else:
                missing_page_ids.append({"test_id": d["test_id"], "page_id": pid})

        if must and found_pages:
            ctx = _normalize("\n".join(page_haystack(p) for p in found_pages))
            missed = [m for m in must if _normalize(m) not in ctx]
            if missed:
                must_include_misses.append({
                    "test_id": d["test_id"], "question": d["question"],
                    "missed": missed, "expected_sources": sources,
                })

        if links:
            real_urls = set()
            for p in found_pages:
                real_urls |= page_urls(p)
            for l in links:
                if l in real_urls:
                    continue
                if l in url2page:
                    link_other_page.append({
                        "test_id": d["test_id"], "link": l,
                        "actual_page_id": url2page[l], "expected_sources": sources,
                    })
                else:
                    link_broken.append({"test_id": d["test_id"], "link": l})

    n = len(rows)
    print(f"검증 대상 {n}문항 (corpus 페이지 {len(pages)}개)")

    print(f"\n[1] expected_sources page_id가 corpus에 없음: {len(missing_page_ids)}건")
    for m in missing_page_ids[:30]:
        print(f"  {m['test_id']}: '{m['page_id']}' 없음")

    print(f"\n[2] must_include가 expected_sources 어디에도 없음(본문/제목/링크/첨부/영상 통틀어): "
          f"{len(must_include_misses)}건")
    for m in must_include_misses[:30]:
        print(f"  {m['test_id']} | 누락: {m['missed']} | 질문: {m['question']}")

    print(f"\n[3a] expected_links가 corpus 어디에도 없음(진짜 깨진/오타 링크): {len(link_broken)}건")
    for m in link_broken[:30]:
        print(f"  {m['test_id']} | {m['link']}")

    print(f"\n[3b] expected_links가 corpus엔 있지만 expected_sources와 다른 page_id: "
          f"{len(link_other_page)}건 (오류 아닐 수 있음 - 관련 페이지로 안내하는 케이스)")
    for m in link_other_page[:30]:
        print(f"  {m['test_id']} | {m['link']} -> 실제 page_id={m['actual_page_id']} "
              f"(expected_sources={m['expected_sources']})")

    print(f"\n요약: page_id 오류 {len(missing_page_ids)}건 · "
          f"must_include 불일치 {len(must_include_misses)}건 · "
          f"link 완전히 깨짐 {len(link_broken)}건 · "
          f"link 다른페이지 {len(link_other_page)}건 (총 {n}문항 중)")


if __name__ == "__main__":
    main()
