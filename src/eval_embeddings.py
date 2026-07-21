"""임베딩 모델 후보 비교 — 동일 코퍼스·테스트셋으로 Recall@k·MRR·인코딩 속도 측정.

팀원 전원이 이 스크립트를 동일 모델 ID로 돌려 결과를 맞대고 한 모델을 고른다. 그래서
색인 단위·평가 산식은 프로젝트1 것을 그대로 재사용한다(build_units('all') 494청크,
페이지 단위 Recall@k·MRR). 검색은 순수 dense(업무 필터 없음) — 모델 자체의 검색력만 격리한다.

공유 프로덕션 캐시(retrieval.DenseRetriever)는 건드리지 않는다. 그 캐시는 텍스트 해시로만
키를 잡아 모델이 달라도 같은 파일을 재사용하므로(모델 충돌), 비교용으로는 부적합하다.
여기서는 모델마다 문서를 새로 인코딩한다(494청크는 GPU에서 초 단위라 캐시 불필요).

실행(Colab GPU 권장): python3 src/eval_embeddings.py
자가검증(모델 로드 불필요):   python3 src/eval_embeddings.py --selftest
"""
import json
import os
import sys
import time
from pathlib import Path

# torch import(어느 함수든) 이전에 설정해야 효과 있음 — CUDA 단편화로 인한 가짜 OOM 완화.
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

sys.path.insert(0, str(Path(__file__).resolve().parent))
from chunking import build_units
from eval_retrieval import KS, ROOT, evaluate, load_testset
from retrieval import PageRanked

# 후보 모델 — 팀원과 동일해야 비교 가능. 추천 기본값으로 시작(2026-07-21 합의 전 잠정).
# batch_size는 메모리 안전용(모델별 상이). Nemotron은 오픈웨이트 ID·구동방식 확정 후 주석 해제.
MODELS = [
    {"key": "bge-m3",     "id": "BAAI/bge-m3",               "query_prompt": None, "batch_size": 16},
    {"key": "qwen3-0.6b", "id": "Qwen/Qwen3-Embedding-0.6B", "batch_size": 4,
     "query_prompt": "Instruct: Given a web search query, retrieve relevant passages that answer the query\nQuery:"},
    {"key": "bge-m3-ko",  "id": "dragonkue/bge-m3-ko",       "query_prompt": None, "batch_size": 16},
    {"key": "nv-embed-v2", "id": "nvidia/NV-Embed-v2", "batch_size": 2,
     "trust_remote_code": True, "fp16": True, "padding_side": "right",  # 7B — A100서 fp16, ST 예제가 padding_side=right 요구
     "query_prompt": "Instruct: Given a web search query, retrieve relevant passages that answer the query\nQuery:"},
]

INDEX_MODE = "all"  # 제품과 동일한 색인 단위(494청크)
MAX_SEQ = 8192  # 시퀀스 길이 캡 — bge-m3는 원래 8192(baseline 불변), Qwen3의 32k 기본값 폭주 방지


def _device():
    import torch
    return "cuda" if torch.cuda.is_available() else "cpu"


def load_model(cfg):
    from sentence_transformers import SentenceTransformer
    kw = {"device": _device()}
    if cfg.get("trust_remote_code"):
        kw["trust_remote_code"] = True
    if cfg.get("fp16"):
        kw["model_kwargs"] = {"torch_dtype": "float16"}  # 7B급을 40GB에 올리려면 필수
    model = SentenceTransformer(cfg["id"], **kw)
    cur = getattr(model, "max_seq_length", None) or MAX_SEQ
    model.max_seq_length = min(cur, MAX_SEQ)  # 긴 문서 하나가 배치 전체를 폭주시키는 것 방지
    if cfg.get("padding_side"):
        model.tokenizer.padding_side = cfg["padding_side"]  # NV-Embed ST 예제 요구사항
    return model


class DenseModelRetriever:
    """모델 하나로 문서 임베딩을 받아 유닛 단위 [(unit_id, score)]를 반환. 질문 임베딩은 메모이즈."""

    def __init__(self, model, cfg, unit_ids, doc_emb):
        self.model, self.cfg = model, cfg
        self.unit_ids, self.doc_emb = unit_ids, doc_emb
        self._qcache = {}

    def _encode_query(self, q):
        if q not in self._qcache:
            kw = {"normalize_embeddings": True}
            if self.cfg.get("query_prompt"):
                kw["prompt"] = self.cfg["query_prompt"]  # ST가 질문 앞에 붙임(비대칭 검색 모델용)
            self._qcache[q] = self.model.encode([q], **kw)[0]
        return self._qcache[q]

    def search(self, query, k):
        scores = self.doc_emb @ self._encode_query(query)
        ranked = sorted(zip(self.unit_ids, scores.tolist()), key=lambda x: x[1], reverse=True)
        return ranked[:k]


def encode_docs(model, texts, batch_size):
    """문서 임베딩 + 소요시간(초). normalize → 내적이 코사인."""
    t0 = time.time()
    emb = model.encode(texts, normalize_embeddings=True, batch_size=batch_size, show_progress_bar=True)
    return emb, time.time() - t0


def _free_vram():
    try:
        import gc
        import torch
        gc.collect()
        torch.cuda.empty_cache()
    except Exception:
        pass


def eval_one(cfg, uids, texts, u2p, questions):
    """모델 하나 로딩→인코딩→평가 후 지표 dict 반환. 함수 스코프라 리턴 즉시 model·doc_emb·ret
    참조가 사라진다 — 이후 _free_vram()이 GPU를 실제로 비울 수 있다(리트리버가 모델을 붙들던 leak 해결)."""
    import numpy as np
    model = load_model(cfg)
    doc_emb, sec = encode_docs(model, texts, cfg.get("batch_size", 16))
    doc_emb = np.asarray(doc_emb, dtype=np.float32)
    ret = PageRanked(DenseModelRetriever(model, cfg, uids, doc_emb), u2p)
    m = evaluate(ret, questions)
    return m | {"key": cfg["key"], "id": cfg["id"], "dim": int(doc_emb.shape[1]), "encode_s": round(sec, 1)}


def run():
    import traceback
    uids, texts, u2p = build_units(INDEX_MODE)
    questions = load_testset()
    print(f"코퍼스 {len(uids)}청크({INDEX_MODE}) · 평가 {len(questions)}건 · device={_device()}\n", flush=True)

    outdir = ROOT / "data" / "embedding_eval"
    outdir.mkdir(exist_ok=True)
    out = outdir / "dy.json"  # 팀원별 파일(dy/yj/jy/hw)로 합쳐 비교
    rows = []

    def save():  # 매 모델 후 저장 — 뒤 모델이 죽어도 앞 결과는 남는다
        out.write_text(json.dumps({"owner": "dy", "device": _device(), "index_mode": INDEX_MODE,
                                   "n_questions": len(questions), "results": rows},
                                  ensure_ascii=False, indent=2), encoding="utf-8")

    for cfg in MODELS:
        print(f"[{cfg['key']}] {cfg['id']} 로딩·인코딩…", flush=True)
        try:
            m = eval_one(cfg, uids, texts, u2p, questions)
            rows.append(m)
            print(f"  → MRR {m['MRR']:.3f} · Recall@5 {m['Recall@5']:.3f} · dim {m['dim']} · {m['encode_s']}s\n", flush=True)
        except Exception as e:
            # 한 모델 실패가 전체를 죽이지 않도록. 이유를 남겨 어떤 모델이 왜 실패했는지 보이게.
            rows.append({"key": cfg["key"], "id": cfg["id"], "error": f"{type(e).__name__}: {e}"})
            print(f"  ✗ 실패: {type(e).__name__}: {e}\n{traceback.format_exc()}", flush=True)
        _free_vram()  # eval_one 리턴으로 참조가 사라진 뒤라야 실제로 비워짐
        save()

    ok = [m for m in rows if "error" not in m]
    cols = [f"Recall@{k}" for k in KS] + ["MRR"]
    print(f"=== 임베딩 모델 비교 ({INDEX_MODE} {len(uids)}청크 · 순수 dense · 필터 없음 · 평가 {len(questions)}건) ===")
    print("model".ljust(13) + "".join(c.rjust(11) for c in cols) + "dim".rjust(7) + "enc(s)".rjust(9))
    for m in ok:
        print(m["key"].ljust(13) + "".join(f"{m[c]:>11.3f}" for c in cols) + f"{m['dim']:>7}{m['encode_s']:>9}")
    for m in rows:
        if "error" in m:
            print(f"{m['key'].ljust(13)}✗ {m['error']}")
    print(f"\n결과 저장 → {out.relative_to(ROOT)}")
    return 0


def _selftest():
    """검색기 배선 검증 — 가짜 문서 임베딩으로 PageRanked+evaluate 경로를 못 박는다(모델 불필요)."""
    import numpy as np
    # 유닛 3개, 페이지 2개(u1,u2→pA / u3→pB). 질문이 u2와 정렬되게 임베딩 구성.
    uids = ["u1", "u2", "u3"]
    u2p = {"u1": "pA", "u2": "pA", "u3": "pB"}
    doc_emb = np.array([[1, 0], [0, 1], [-1, 0]], dtype=np.float32)

    class FakeModel:
        def encode(self, xs, **kw):
            return np.array([[0, 1]], dtype=np.float32)  # 질문 = u2 방향 → pA가 1위

    ret = PageRanked(DenseModelRetriever(FakeModel(), {}, uids, doc_emb), u2p)
    got = ret.search("q", 2)
    assert got[0][0] == "pA", got  # 최근접 유닛 u2 → 페이지 pA
    r = evaluate(ret, [("q", {"pA"})], ks=[1])
    assert r["Recall@1"] == 1.0 and r["MRR"] == 1.0, r
    print("selftest ok")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
    else:
        sys.exit(run())
