"""Gate 2 참조 벡터 캐시 생성 — config/gate2_reference.json → data/gate2_cache/.

Gate 2는 도메인 판정을 **centroid(클러스터 평균 벡터)가 아니라 개별 문장 벡터**로 한다 —
클러스터 안에 길이가 다른 문장(짧은 명사 ~ 긴 문장)을 섞어도 서로 평균으로 희석되지 않고,
판정 시 전체 참조 벡터 중 최댓값(nearest neighbor)을 그대로 쓴다. 그래서 여기서는 클러스터당
벡터 하나로 뭉치지 않고, in_domain·out_of_domain 각각의 개별 sample_questions 전부를 한 문장당
한 벡터로 인코딩해 그대로 저장한다.

임베딩은 retrieval.py의 bge-m3-ko(DEFAULT_DENSE_MODEL)를 재사용한다 — 런타임 질의 인코딩
(_encode_query)과 반드시 같은 모델·같은 normalize_embeddings=True 조건이어야 내적이 코사인
유사도와 일치한다.

출력(data/gate2_cache/, 3개 파일 — 문서 임베딩 캐시(embed_corpus.py) 관례와 동일하게 npy+manifest):
  in_domain_emb.npy   (N_in  x dim) — manifest["in_domain"]과 행 순서로 대응
  out_domain_emb.npy  (N_out x dim) — manifest["out_of_domain"]과 행 순서로 대응
  manifest.json        {version, model, in_domain:[{cluster_id,business_function,question}],
                         out_of_domain:[{cluster_id,category,question}]}

실행: python3 src/crawler/build_gate2_reference.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "src"))

import numpy as np  # noqa: E402

from retrieval import DEFAULT_DENSE_MODEL, _get_model  # noqa: E402

CONFIG_PATH = ROOT / "config" / "gate2_reference.json"
CACHE_DIR = ROOT / "data" / "gate2_cache"


def _flatten(config):
    in_domain = []
    for cluster_id, c in config["in_domain"].items():
        for q in c["sample_questions"]:
            in_domain.append({"cluster_id": cluster_id, "business_function": c["business_function"],
                               "question": q})
    out_of_domain = []
    for cluster_id, c in config["out_of_domain"].items():
        for q in c["sample_questions"]:
            out_of_domain.append({"cluster_id": cluster_id, "category": c["category"], "question": q})
    return in_domain, out_of_domain


def main():
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    in_domain, out_of_domain = _flatten(config)
    if not in_domain or not out_of_domain:
        raise SystemExit("gate2_reference.json에 in_domain/out_of_domain 문항이 비어 있다.")

    model = _get_model(DEFAULT_DENSE_MODEL)
    # normalize_embeddings=True → 내적이 곧 코사인 유사도(retrieval.DenseRetriever와 동일 조건).
    in_emb = model.encode([r["question"] for r in in_domain],
                           normalize_embeddings=True, show_progress_bar=True, batch_size=8)
    out_emb = model.encode([r["question"] for r in out_of_domain],
                            normalize_embeddings=True, show_progress_bar=True, batch_size=8)

    CACHE_DIR.mkdir(exist_ok=True)
    np.save(CACHE_DIR / "in_domain_emb.npy", in_emb)
    np.save(CACHE_DIR / "out_domain_emb.npy", out_emb)
    manifest = {
        "version": config["version"],
        "model": DEFAULT_DENSE_MODEL,
        "in_domain": in_domain,
        "out_of_domain": out_of_domain,
    }
    (CACHE_DIR / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"in_domain      {len(in_domain):>4}문장 → gate2_cache/in_domain_emb.npy")
    print(f"out_of_domain  {len(out_of_domain):>4}문장 → gate2_cache/out_domain_emb.npy")
    print(f"manifest → {(CACHE_DIR / 'manifest.json').relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
