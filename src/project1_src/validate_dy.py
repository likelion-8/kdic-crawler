# src/project1_src/validate_dy.py
"""네트워크 없이 HTML→텍스트 변환 검증.

사용법:
  python3 src/project1_src/validate_dy.py
"""
from crawler_dy import extract_attachments, html_to_text


def self_check():
    html = """<html><body><div id="contents"><h1>제목</h1>
    <script>bad()</script>
    <table><tr><th>구분</th><th>서류</th></tr><tr><td>본인</td><td>신분증</td></tr></table>
    <a href="/files/form.hwp">신청서식</a></div></body></html>"""
    t = html_to_text(html)
    assert "제목" in t and "bad()" not in t, t
    assert "구분 | 서류" in t and "본인 | 신분증" in t, t
    att = extract_attachments(html, "https://www.kdic.or.kr/x/y.do")
    assert att == [{"name": "신청서식", "url": "https://www.kdic.or.kr/files/form.hwp"}], att
    print("self-check ok")


if __name__ == "__main__":
    self_check()
