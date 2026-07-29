"""운영용 intent 분류기(형태소 TF-IDF + LogisticRegression) 학습 → pickle 저장.

파이프라인 실행 중에는 호출되지 않는 '준비 단계' 스크립트다. 라벨 데이터
(testset_all.jsonl)가 갱신되면 사람이 한 번 실행해 모델을 다시 굽는다.

검증 스크립트(eval_intent_morpheme.py)는 데이터 누수 검증을 위해 80%만 학습했지만,
운영 모델은 가진 라벨 데이터 전체(in-scope 821건)로 학습해 성능을 최대화한다.

토큰화는 query_classifier.tokenize_intent()를 그대로 재사용한다 — 학습과 추론이
같은 토큰화를 쓰도록 함수 하나를 공유(어긋나면 조용히 성능이 떨어짐). TF-IDF는
공백 분리(token_pattern)만 쓰므로 커스텀 tokenizer가 pickle에 안 들어가 로드가 안전하다.

실행: python3 src/train_intent_morpheme.py
"""
import json
import pickle
import sys
from collections import Counter
from pathlib import Path

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from query_classifier import tokenize_intent  # noqa: E402  학습·추론 동일 토큰화 공유

TESTSET = ROOT / "data" / "testset" / "testset_all.jsonl"
OUT_DIR = ROOT / "data" / "intent_classifier"


def main():
    rows = [json.loads(l) for l in open(TESTSET, encoding="utf-8") if l.strip()]
    inscope = [r for r in rows if r.get("expected_sources")]  # 운영 분류기와 동일 기준
    docs = [" ".join(tokenize_intent(r["question"])) for r in inscope]
    y = [r["intent"] for r in inscope]
    print(f"학습 데이터 {len(docs)}건 (in-scope), intent 분포: {dict(Counter(y))}")

    # 공백 분리만 하는 벡터라이저(커스텀 tokenizer 없음 → pickle 안전). min_df=2로 초저빈도 토큰 제거.
    vec = TfidfVectorizer(token_pattern=r"(?u)\S+", lowercase=False, min_df=2)
    X = vec.fit_transform(docs)
    # 클래스 불균형(informational이 다수)이라 balanced 가중치 사용
    model = LogisticRegression(max_iter=1000, class_weight="balanced")
    model.fit(X, y)

    print(f"특징(형태소 토큰) 수: {len(vec.get_feature_names_out())}")
    print(f"학습셋 정확도(참고, 누수 있어 과대평가): {model.score(X, y)*100:.1f}%")
    print("  ↑ 실제 성능은 eval_intent_morpheme.py의 Leave-Page-Out 89.6% 기준")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUT_DIR / "tfidf_vectorizer.pkl", "wb") as f:
        pickle.dump(vec, f)
    with open(OUT_DIR / "logreg_model.pkl", "wb") as f:
        pickle.dump(model, f)
    print(f"저장 완료: {(OUT_DIR / 'tfidf_vectorizer.pkl').relative_to(ROOT)}")
    print(f"저장 완료: {(OUT_DIR / 'logreg_model.pkl').relative_to(ROOT)}")


if __name__ == "__main__":
    main()
