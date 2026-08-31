"""골든셋 검증 — testset_all.jsonl 을 **1-NN 참조셋으로서** 감사한다.

**무엇을 재는가.** 골든셋(evaluation_dataset)은 2026-08-19 팀 결정으로 query_classifier
QuestionTypeClassifier 의 1-NN 참조 예시 **전용**이 됐다(커밋 3159d86). 채점은 홀드아웃
계열이 맡는다. 그래서 이 스크립트는 채점 필드(must_include·reference_answer·expected_links
·must_not_include)를 보지 않는다 — 지금 아무도 안 읽는 값이라 고쳐도 동작이 안 바뀐다.
보는 것은 참조셋으로 실제 쓰이는 4개뿐이다:
    question · question_type · embedding · expected_sources(비었나 아닌가만)
expected_sources 는 페이지 목록이 맞는지가 아니라 **비었는지**만 본다 — reference_stmt()가
cardinality>0 으로 참조셋 포함 여부를 가르기 때문이다(빈 값 = out_of_scope = 참조셋 제외).

**business_function 을 안 재는 이유.** BusinessFunctionClassifier 는 2026-07-29 에
비활성화되어 주석 처리됐고(query_classifier.py), retrieval._build_engines()가
bf_classifier 를 넘기지 않아 업무 필터가 걸리지 않는다. 일치율을 재도 쓰이는 데가 없다.

**왜 link_guide 에 집중하는가.** 골든셋이 검색을 바꾸는 경로는 하나뿐이다 —
    골든셋 라벨 -> 1-NN 예측 -> link_guide 여부 -> Hybrid/Dense -> 검색 결과
(RoutedRetriever.HYBRID_ONLY_TYPES = {"link_guide"}). 5라벨 정확도는 이 경로에 거의
정보를 주지 않는다. 게다가 오분류 비용이 극단적으로 비대칭이라(아래 MRR_TABLE) 실질적으로
감사할 것은 **table_lookup 이 link_guide 로 새는가** 하나에 가깝다.

**임베딩.** DenseRetriever 를 인스턴스화하지 않고 캐시 .npy 를 직접 읽는다 — 그 생성자는
캐시가 있어도 _get_model 이 먼저 돌아 bge-m3(약 2GB)를 CPU 에 올린다. 캐시가 없을 때만
인코딩으로 떨어진다(그때는 느리다).

**DB 를 안 본다.** JSONL 이 단일 진실원천이고(index_evaluation_sets 참조), 이 감사는
"고치기 전" 상태를 재현 가능하게 재는 것이 목적이다. DB 반영 여부는 로더가 책임진다.

읽기 전용: 기존 파일 수정 없음. 결과는 results/goldenset_audit/ 에 쓴다.
실행: python3 experiments/validate_goldenset.py
"""
import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent   # experiments/ -> 리포 루트
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "src" / "crawler"))

GOLDEN = ROOT / "data" / "testset" / "testset_all.jsonl"
CORPUS = ROOT / "data" / "corpus.jsonl"
OUTDIR = ROOT / "results" / "goldenset_audit"

ALLOWED_TYPES = {"fact", "faq", "table_lookup", "link_guide", "file_download", "out_of_scope"}
HYBRID_ONLY = "link_guide"          # retrieval.RoutedRetriever.HYBRID_ONLY_TYPES
NEAR_DUP = 0.95                     # 근친 판정 코사인 임계
ISOLATED_SHOW = 20                  # 고립 문항 상위 표시 수

# 유형별 (Dense MRR, Hybrid MRR) — eval_routing_value.py 가 현재 코퍼스(503청크·프리픽스
# 임베딩)에서 2026-08-19 재측정한 값. retrieval.py:266-275 의 2026-07-28 표를 대체한다.
# link_guide 오분류 1건의 비용 = 그 유형의 (Dense - Hybrid). link_guide 자신은 부호가 반대라
# 정분류 1건의 '이득'이 된다.
#
# ⚠️ 이 가중치는 참고치다. 쌍대 부트스트랩 95% CI 에서 **0 을 벗어난 유형은 table_lookup
#    하나뿐**이었다(-0.058, CI [-0.108, -0.008]). link_guide 조차 +0.040 이지만 CI
#    [-0.033, +0.117] 로 0 을 포함한다(n=59). 따라서 아래 순손익 수치는 방향을 잡는 용도이지
#    "이만큼 이득/손해"로 읽을 값이 아니다. 확실한 것은 table_lookup 을 Hybrid 로 보내면
#    손해라는 것 하나다. 상세: results/routing_value/routing_value.json
MRR_TABLE = {"fact": (0.798, 0.820), "faq": (0.840, 0.836), "table_lookup": (0.905, 0.847),
             "link_guide": (0.692, 0.732), "file_download": (0.983, 0.948)}
# 위 CI 기준으로 통계적으로 구분 가능한 유형 — 순손익 해석 시 이것만 신뢰한다.
SIGNIFICANT_TYPES = {"table_lookup"}


def load_golden():
    with open(GOLDEN, encoding="utf-8") as f:
        return [json.loads(line) for line in f]


def integrity(rows):
    """사람 판단이 필요 없는 확정 결함만. 참조셋 역할에 닿는 것만 본다."""
    qs = [r["question"].strip() for r in rows]
    dup_q = [q for q, c in Counter(qs).items() if c > 1]
    return {
        "test_id_중복": [t for t, c in Counter(r["test_id"] for r in rows).items() if c > 1],
        "질문_원문_완전중복": dup_q,
        "빈_질문": [r["test_id"] for r in rows if not r["question"].strip()],
        "question_type_빈값": [r["test_id"] for r in rows if not r.get("question_type")],
        "허용외_question_type": sorted({r.get("question_type") for r in rows}
                                      - ALLOWED_TYPES - {None}),
        # 아래 둘은 참조셋 포함 여부를 가르는 두 신호(라벨 vs cardinality)가 어긋난 경우다.
        # 어긋나면 out_of_scope 라벨이 참조셋에 들어가 예측 가능한 라벨이 되어 버린다.
        "out_of_scope인데_기대출처_있음": [r["test_id"] for r in rows
                                          if r.get("question_type") == "out_of_scope"
                                          and r.get("expected_sources")],
        "기대출처_없는데_out_of_scope_아님": [r["test_id"] for r in rows
                                             if r.get("question_type") != "out_of_scope"
                                             and not r.get("expected_sources")],
        # 라벨 규칙(2026-08-19 골든셋 검증에서 도출): "기대 답변에 링크가 들어가면
        # link_guide(파일이면 file_download)". 실측 판별력 — expected_links 보유율이
        # link_guide 89.8%·file_download 20.7% 인 반면 fact 0.2%·faq 0%·table_lookup 0%.
        # 라벨이 흔들리는 "어디서/어디로" 질문군을 사람 판단 없이 가르는 유일한 객관 기준이라
        # 무결성 검사로 고정한다. 걸린 문항은 라벨이나 expected_links 중 하나가 틀린 것이다.
        "link_guide인데_expected_links_없음": [r["test_id"] for r in rows
                                              if r.get("question_type") == "link_guide"
                                              and not r.get("expected_links")],
        # expected_links 는 답변에 그대로 실리는 값이라 형식이 섞이면 안 된다.
        # 실제로 63개 중 1개만 'www.…' 형식이어서 이 검사가 없으면 못 잡았다.
        "expected_links_URL형식_이상": [r["test_id"] for r in rows
                                       if any(not u.startswith(("http://", "https://"))
                                              for u in (r.get("expected_links") or []))],
        "expected_links있는데_링크유형_아님": [r["test_id"] for r in rows
                                             if r.get("expected_links")
                                             and r.get("question_type") not in
                                             ("link_guide", "file_download")],
    }


def load_embeddings(questions):
    """캐시된 질문 임베딩 행렬(정규화 완료). 반환: (행렬, 캐시적중여부)."""
    from retrieval import DEFAULT_DENSE_MODEL, DenseRetriever
    cache = DenseRetriever._cache_path(questions, DEFAULT_DENSE_MODEL)
    if cache.exists():
        return np.load(cache), True
    print(f"  캐시 없음({cache.name}) — 인코딩합니다(모델 로딩, 수 분 소요)")
    return DenseRetriever(list(range(len(questions))), questions).doc_emb, False


def loo_audit(rows, emb):
    """참조셋 문항끼리 leave-one-out 1-NN. 자기 자신만 제외한다.

    자기 자신만 빼는 이유: 이 감사의 목적은 '라벨 규칙이 서로 충돌하나'를 찾는 것이라,
    같은 페이지의 형제 질문은 실서비스에서도 정당한 이웃이므로 남겨야 한다. 대신 그
    형제 누수 때문에 여기서 나온 정확도는 실제보다 후하다 — 외부 검증셋으로 따로 재야
    한다(eval_routing_value.py). 여기 수치는 '실제는 이보다 나쁘다'로만 읽을 것.
    """
    idx = [i for i, r in enumerate(rows) if r.get("expected_sources")]
    E = emb[idx]
    labels = [rows[i]["question_type"] for i in idx]
    sims = E @ E.T
    np.fill_diagonal(sims, -np.inf)
    nn = np.argmax(sims, axis=1)
    top = sims[np.arange(len(idx)), nn]
    return idx, labels, sims, nn, top


def leave_page_out(rows, idx, labels, sims):
    """같은 페이지에서 나온 형제 질문을 전부 뺀 1-NN 예측 — LOO 수치가 얼마나 부풀려졌는지
    재는 용도다.

    페이지당 질문이 10개 넘게 있고 같은 본문을 보고 만들어져 표현·라벨이 대개 같다. 자기
    자신만 빼는 LOO 는 그 형제들이 사실상 정답을 알려주는 이웃으로 남아 후하게 나온다.
    두 수치의 격차가 곧 형제 누수의 크기다. 다만 leave-page-out 은 '그 페이지 예시를 하나도
    못 쓰는' 조건이라 실서비스(코퍼스 58페이지 고정)보다 비관적이다 — 실사용 추정치는
    홀드아웃 측정이 맡는다. 여기서는 LOO 를 어느 정도 할인해 읽어야 하는지만 본다."""
    page = [(rows[i]["expected_sources"] or [""])[0] for i in idx]
    masked = sims.copy()
    for i in range(len(idx)):
        masked[i][[j for j in range(len(idx)) if page[j] == page[i]]] = -np.inf
    pred = [labels[j] for j in np.argmax(masked, axis=1)]
    return pred


def main():
    rows = load_golden()
    OUTDIR.mkdir(parents=True, exist_ok=True)

    integ = integrity(rows)
    emb, hit = load_embeddings([r["question"] for r in rows])
    idx, labels, sims, nn, top = loo_audit(rows, emb)
    pred = [labels[j] for j in nn]
    lpo_pred = leave_page_out(rows, idx, labels, sims)
    n = len(idx)

    # link_guide 이진 — 라우팅이 실제로 쓰는 유일한 구분
    tp = sum(1 for a, p in zip(labels, pred) if a == HYBRID_ONLY and p == HYBRID_ONLY)
    fn = sum(1 for a, p in zip(labels, pred) if a == HYBRID_ONLY and p != HYBRID_ONLY)
    fp = sum(1 for a, p in zip(labels, pred) if a != HYBRID_ONLY and p == HYBRID_ONLY)
    fp_by_type = Counter(a for a, p in zip(labels, pred) if a != HYBRID_ONLY and p == HYBRID_ONLY)

    # 비용 가중 손익: 맞힌 link_guide 는 이득, 오판된 나머지 유형은 유형별 손실.
    gain = tp * (MRR_TABLE[HYBRID_ONLY][1] - MRR_TABLE[HYBRID_ONLY][0])
    loss = sum(c * (MRR_TABLE[t][0] - MRR_TABLE[t][1]) for t, c in fp_by_type.items()
               if t in MRR_TABLE)
    # 통계적으로 구분 가능한 유형만 따로 — 위 순손익은 유의하지 않은 차이까지 합산한 값이라
    # 방향 참고용이고, 실제로 신뢰할 수 있는 손해는 이쪽이다.
    sig_loss = sum(c * (MRR_TABLE[t][0] - MRR_TABLE[t][1]) for t, c in fp_by_type.items()
                   if t in SIGNIFICANT_TYPES)

    with open(OUTDIR / "01_integrity.json", "w", encoding="utf-8") as f:
        json.dump({"총_문항": len(rows), **integ}, f, ensure_ascii=False, indent=2)

    pairs = [(i, j) for i in range(n) for j in range(i + 1, n) if sims[i][j] >= NEAR_DUP]
    pairs.sort(key=lambda p: -sims[p[0]][p[1]])
    with open(OUTDIR / "02_near_duplicates.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["유사도", "라벨일치", "test_id_A", "질문_A", "라벨_A",
                    "test_id_B", "질문_B", "라벨_B"])
        for i, j in pairs:
            a, b = rows[idx[i]], rows[idx[j]]
            w.writerow([f"{sims[i][j]:.4f}", "같음" if labels[i] == labels[j] else "다름",
                        a["test_id"], a["question"], labels[i],
                        b["test_id"], b["question"], labels[j]])

    conflicts = [k for k in range(n) if labels[k] != pred[k]]
    # 라우팅에 닿는 오분류(link_guide 가 끼어 있는 것)를 위로 올린다.
    conflicts.sort(key=lambda k: (HYBRID_ONLY not in (labels[k], pred[k]), -top[k]))
    routed_conflicts = sum(1 for k in conflicts if HYBRID_ONLY in (labels[k], pred[k]))
    with open(OUTDIR / "03_label_conflicts.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["라우팅영향", "유사도", "test_id", "질문", "정답라벨", "LOO예측",
                    "끌어당긴_이웃_test_id", "끌어당긴_이웃_질문", "이웃라벨"])
        for k in conflicts:
            me, other = rows[idx[k]], rows[idx[nn[k]]]
            mark = "★" if HYBRID_ONLY in (labels[k], pred[k]) else ""
            w.writerow([mark, f"{top[k]:.4f}", me["test_id"], me["question"],
                        labels[k], pred[k], other["test_id"], other["question"], labels[nn[k]]])

    by_type = defaultdict(list)
    for k in range(n):
        by_type[labels[k]].append(k)
    with open(OUTDIR / "04_coverage.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["question_type", "문항수", "LOO정확도", "최근접유사도_평균", "최근접유사도_최소"])
        for t, ks in sorted(by_type.items(), key=lambda x: -len(x[1])):
            acc = sum(1 for k in ks if pred[k] == t) / len(ks)
            w.writerow([t, len(ks), f"{acc:.4f}",
                        f"{np.mean([top[k] for k in ks]):.4f}",
                        f"{min(top[k] for k in ks):.4f}"])

    # link_guide 가 낀 충돌만 따로 — 라우팅에 닿는 유일한 구분이고, expected_links 라는
    # 객관 기준이 있어 사람이 판정할 수 있다. 나머지(fact<->faq 등)는 라우팅에 영향이 없어
    # 검토 대상이 아니다.
    #
    # 판정에 필요한 것은 세 가지다: 두 문항이 각각 링크를 가졌나, 그리고 링크가 없는 쪽의
    # 정답 페이지에 애초에 걸 링크가 있나. 페이지에 링크가 0개면 그 질문은 링크로 답할 수
    # 없으므로 라벨 차이가 정당하다(고칠 것이 없다). 링크가 있으면 expected_links 누락일
    # 수 있어 사람이 봐야 한다 — 페이지가 링크를 가졌다는 것만으로는 그 질문의 답이 링크라는
    # 뜻이 아니라서 자동 판정은 하지 않는다.
    with open(CORPUS, encoding="utf-8") as f:
        page_links = {r["page_id"]: len(r.get("links") or []) for r in map(json.loads, f)}

    def _has_link(k):
        return bool(rows[idx[k]].get("expected_links"))

    def _page_links(k):
        return page_links.get((rows[idx[k]].get("expected_sources") or [""])[0], 0)

    seen_pairs = set()
    review = []
    for k in conflicts:
        if HYBRID_ONLY not in (labels[k], pred[k]):
            continue
        j = nn[k]
        key = tuple(sorted((rows[idx[k]]["test_id"], rows[idx[j]]["test_id"])))
        if key in seen_pairs:
            continue
        seen_pairs.add(key)
        mine, theirs = _has_link(k), _has_link(j)
        # file_download 는 링크를 갖는 게 정상이라(양식·PDF 다운로드) link_guide 와 같은
        # '링크 유형'으로 본다. 둘 다 링크 유형이면 라벨이 달라도 규칙 위반이 아니다.
        link_types = {HYBRID_ONLY, "file_download"}
        both_link_type = labels[k] in link_types and labels[j] in link_types
        if mine == theirs and not both_link_type:
            verdict = "규칙위반 — 한쪽 라벨이 틀림"       # 무결성 검사에도 잡힌다
        elif mine == theirs:
            verdict = "검토 — 파일 다운로드 vs 페이지 안내"
        elif _page_links(k if not mine else j) == 0:
            verdict = "한계 — 링크로 답할 수 없음"
        else:
            verdict = "검토 — expected_links 누락 가능"
        review.append((verdict, top[k], k, j, mine, theirs))
    review.sort(key=lambda r: (r[0], -r[1]))
    with open(OUTDIR / "07_link_rule_review.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["판정", "유사도", "test_id", "질문", "라벨", "링크보유", "정답페이지_링크수",
                    "이웃_test_id", "이웃_질문", "이웃라벨", "이웃_링크보유"])
        for verdict, sim, k, j, mine, theirs in review:
            w.writerow([verdict, f"{sim:.4f}",
                        rows[idx[k]]["test_id"], rows[idx[k]]["question"], labels[k],
                        "O" if mine else "X", _page_links(k),
                        rows[idx[j]]["test_id"], rows[idx[j]]["question"], labels[j],
                        "O" if theirs else "X"])

    isolated = sorted(range(n), key=lambda k: top[k])[:ISOLATED_SHOW]
    with open(OUTDIR / "05_isolated.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["최근접유사도", "test_id", "질문", "라벨", "가장가까운_이웃", "이웃라벨"])
        for k in isolated:
            w.writerow([f"{top[k]:.4f}", rows[idx[k]]["test_id"], rows[idx[k]]["question"],
                        labels[k], rows[idx[nn[k]]]["question"], labels[nn[k]]])

    summary = {
        "골든셋_전체": len(rows), "참조셋_문항수": n, "참조셋_제외": len(rows) - n,
        "임베딩_캐시적중": hit,
        "LOO_5라벨_정확도": round(sum(1 for a, p in zip(labels, pred) if a == p) / n, 4),
        "leave_page_out_5라벨_정확도":
            round(sum(1 for a, p in zip(labels, lpo_pred) if a == p) / n, 4),
        "link_guide_이진": {
            "정답_link_guide": tp + fn, "정분류_TP": tp, "놓침_FN": fn, "오판_FP": fp,
            "재현율": round(tp / (tp + fn), 4) if tp + fn else None,
            "정밀도": round(tp / (tp + fp), 4) if tp + fp else None,
            "오판_출처_유형별": dict(fp_by_type),
        },
        "비용가중_MRR포인트": {
            "정분류_이득": round(gain, 3), "오판_손실": round(loss, 3),
            "순손익": round(gain - loss, 3),
            "유의유형_손실만": round(sig_loss, 3),
            "출처": "eval_routing_value.py 2026-08-19 재측정 — CI상 유의한 유형은 table_lookup 뿐",
        },
        "근친쌍_수": len(pairs), "라벨충돌_수": len(conflicts),
        "링크규칙_검토큐": dict(Counter(r[0] for r in review)),
        "라벨충돌_라우팅영향": routed_conflicts,
    }
    with open(OUTDIR / "06_loo_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(f"골든셋 {len(rows)}문항 -> 참조셋 {n}문항 (out_of_scope {len(rows) - n}건 제외)")
    print(f"임베딩 캐시 {'적중' if hit else '미적중(인코딩함)'}")
    print()
    print("[무결성]")
    for key, val in integ.items():
        print(f"  {key:34} {len(val)}건" + (f"  {val[:3]}" if val else ""))
    print()
    lpo_acc = summary["leave_page_out_5라벨_정확도"]
    print(f"[LOO 1-NN]  5라벨 정확도 {summary['LOO_5라벨_정확도']}  "
          f"(자기 자신만 제외 — 형제 누수 포함)")
    print(f"            leave-page-out {lpo_acc}  "
          f"(형제 전부 제외 — 누수 폭 {summary['LOO_5라벨_정확도'] - lpo_acc:+.4f})")
    b = summary["link_guide_이진"]
    print(f"  link_guide 재현율 {b['재현율']} ({tp}/{tp + fn})  "
          f"정밀도 {b['정밀도']} ({tp}/{tp + fp})")
    print(f"  오판(FP) 출처: {dict(fp_by_type) or '없음'}")
    c = summary["비용가중_MRR포인트"]
    # 유의하지 않은 유형까지 합산한 순손익은 부호가 흔들려 오해를 부른다(예: fact 는 재측정에서
    # Hybrid 가 근소하게 나아 '오판'이 이득으로 잡힌다). 유의한 것만 단정적으로 찍고,
    # 합산치는 참고 표기로 뒤에 붙인다.
    print(f"  통계적으로 유의한 손해 — table_lookup 유출 {fp_by_type.get('table_lookup', 0)}건: "
          f"{-c['유의유형_손실만']:+.3f} MRR포인트")
    print(f"  (유의하지 않은 유형까지 합산한 참고치: 순 {c['순손익']:+.3f} = "
          f"이득 {c['정분류_이득']:+.3f} / 오판 {-c['오판_손실']:+.3f})")
    print()
    print(f"[검토 큐] 근친쌍 {len(pairs)}건 · 라벨충돌 {len(conflicts)}건 "
          f"(라우팅 영향 {routed_conflicts}건)")
    for verdict, cnt in sorted(Counter(r[0] for r in review).items()):
        print(f"           {verdict:32} {cnt:3}쌍")
    print(f"결과: {OUTDIR}")


if __name__ == "__main__":
    sys.exit(main())
