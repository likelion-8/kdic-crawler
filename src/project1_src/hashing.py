"""갱신 감지용 해시의 단일 기준.

원본 HTML이 아니라 정규화된 본문 텍스트(data/text/<doc_id>.txt)를 해시한다.
원본 사이트가 같은 페이지를 두 판본으로 서빙하고 세션 토큰·공백이 매 요청 달라지므로,
HTML 해시는 본문이 그대로여도 튄다. parse_raw_html 을 거친 텍스트만이
"본문이 실제로 바뀌었다"를 뜻한다.

실행: python3 src/project1_src/hashing.py  (자체검사)
"""
import hashlib


def content_sha256(text: str) -> str:
    """정규화 본문 텍스트의 sha256.

    줄 끝 공백·CRLF·빈 줄은 내용 변화로 치지 않는다. 빈 줄까지 무시하는 건 실측 근거가
    있다: dp_protlmts 를 재수집하니 본문 글자는 한 자도 안 바뀌었는데 빈 줄 하나가
    사라져 있었다(사이트가 판본 2종을 서빙하는 탓). 빈 줄은 내용을 담지 않으므로
    무시하는 편이 갱신 감지에 맞다.
    """
    lines = (l.rstrip() for l in text.replace("\r\n", "\n").splitlines())
    return hashlib.sha256("\n".join(l for l in lines if l).encode("utf-8")).hexdigest()


if __name__ == "__main__":
    base = "보호한도는 1억원입니다.\n예금자 1인당 적용됩니다."
    assert content_sha256(base) == content_sha256(base)
    assert content_sha256(base) == content_sha256(base.replace("\n", "\r\n"))
    assert content_sha256(base) == content_sha256("\n" + base + "  \n\n")
    assert content_sha256(base) == content_sha256(base.replace("니다.\n", "니다.   \n"))
    # 실측된 판본 지터: 문단 사이 빈 줄이 생겼다 없어졌다 한다
    assert content_sha256(base) == content_sha256(base.replace("\n", "\n\n"))
    assert content_sha256(base) != content_sha256(base.replace("1억원", "5천만원"))
    assert len(content_sha256(base)) == 64
    print("자체검사 통과")
