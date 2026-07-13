import os
import json
import re
import hashlib
from bs4 import BeautifulSoup, NavigableString
from inventory import pages_for

URL_INVENTORY = pages_for("hw")

# 크롤링 노이즈 정확일치 필터링 집합 (NOISE EXACT)
NOISE_EXACT = {"글자확대", "KOR", "상단으로 이동", "인쇄", "공유하기"}

def table_to_md(table_node):
    """HTML 표(table) 태그를 마크다운 파이프 양식 문자열로 변환"""
    markdown_rows = []
    rows = table_node.find_all("tr")
    
    for i, row in enumerate(rows):
        cells = row.find_all(["th", "td"])
        cell_texts = [re.sub(r'\s+', ' ', cell.get_text()).strip() for cell in cells]
        markdown_rows.append("| " + " | ".join(cell_texts) + " |")
        
        if i == 0 and row.find("th"):
            separator = "| " + " | ".join(["---"] * len(cells)) + " |"
            markdown_rows.append(separator)
            
    return "\n" + "\n".join(markdown_rows) + "\n"

def collapse(text):
    """연속 공백 정리 및 깨진 레이아웃 클래스 마커 제거"""
    text = re.sub(r'\s+', ' ', text).strip()
    text = re.sub(r'\b[a-z]+[A-Z][a-zA-Z]*\b', '', text) 
    return text

def node_to_text(container):
    """DOM 트리를 규칙 기반으로 순회하며 본문 및 복원된 표 추출"""
    extracted_chunks = []
    
    for element in container.children:
        if isinstance(element, NavigableString):
            txt = element.strip()
            if txt and txt not in NOISE_EXACT:
                extracted_chunks.append(txt)
        elif element.name == "table":
            extracted_chunks.append(table_to_md(element))
        elif element.name is not None:
            inner_text = node_to_text(element)
            if inner_text:
                extracted_chunks.append(inner_text)
                
    return "\n".join(extracted_chunks)

def main():
    print("⚙️ 2단계: 로컬 HTML 소스 파싱 및 JSONL 통합 변환 가동...")
    
    # 데이터를 한 줄씩 누적할 최종 JSONL 파일 경로
    jsonl_output_path = "parsed_results.jsonl"
    
    # 파일을 쓰기 모드(w)로 열어 둡니다.
    with open(jsonl_output_path, "w", encoding="utf-8") as f_out:
        for item in URL_INVENTORY:
            page_id = item["id"]
            html_path = f"data/raw_html/{page_id}.html"
            meta_path = f"meta/{page_id}.json"
            
            if not os.path.exists(html_path):
                print(f"  ⚠️ [{page_id}] 원본 HTML 파일이 없습니다. 1단계 크롤러를 먼저 실행하세요.")
                continue
                
            print(f"  [{page_id}] 로컬 HTML 파일 가공 중...")
            
            with open(html_path, "r", encoding="utf-8") as f_in:
                html_content = f_in.read()
                
            soup = BeautifulSoup(html_content, "html.parser")
            content_div = soup.select_one("div.contents")
            if not content_div:
                content_div = soup.body
                
            raw_parsed = node_to_text(content_div)
            final_text = collapse(raw_parsed)
            
            content_sha = hashlib.sha256(final_text.encode("utf-8")).hexdigest()
            
            # 1. JSONL에 들어갈 단일 객체 구성
            parsed_result = {
                "parent_doc_id": page_id,
                "title": item["title"],
                "business_function": item["business"],
                "sub_category": item["sub_category"],
                "url": item["url"],
                "content_sha": content_sha,
                "parsed_content": final_text
            }
            
            # JSONL 파일에 한 줄(Line)로 기록하고 줄바꿈(\n) 추가
            f_out.write(json.dumps(parsed_result, ensure_ascii=False) + "\n")
                
            # 2. 갱신 파이프라인용 개별 메타데이터 JSON 파일은 그대로 유지
            meta_data = {
                "parent_doc_id": page_id,
                "business_function": item["business"],
                "sub_category": item["sub_category"],
                "title": item["title"],
                "url": item["url"],
                "content_sha": content_sha,
                "required": item["required"]
            }
            with open(meta_path, "w", encoding="utf-8") as f_meta:
                json.dump(meta_data, f_meta, ensure_ascii=False, indent=4)
                
            print(f"  ✅ [{page_id}] 파싱 완료 -> JSONL에 한 줄 추가됨.")

    print(f"🏁 모든 파싱이 완료되었습니다! 최종 데이터는 '{jsonl_output_path}' 파일에서 확인하세요.")

if __name__ == "__main__":
    main()