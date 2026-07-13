# crawler_pure.py
import os
import requests
from inventory_hw import URL_INVENTORY

def main():
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    
    print("🚀 1단계: 순수 웹 크롤링(HTML 원본 다운로드) 시작...")
    
    for item in URL_INVENTORY:
        page_id = item["id"]
        html_path = f"raw_html/{page_id}.html"
        
        if os.path.exists(html_path):
            print(f"  [{page_id}] 이미 HTML 소스가 로컬에 존재하여 건너뜁니다.")
            continue
            
        print(f"  [{page_id}] 웹페이지 다운로드 중: {item['title']}")
        
        try:
            response = requests.get(item["url"], headers=headers, timeout=10)
            if response.status_code == 200:
                with open(html_path, "w", encoding="utf-8") as f:
                    f.write(response.text)
                print(f"  ✅ [{page_id}] HTML 파일 저장 완료.")
            else:
                print(f"   [{page_id}] 다운로드 실패 (상태 코드: {response.status_code})")
        except Exception as e:
            print(f"   [{page_id}] 네트워크 또는 서버 에러 발생: {str(e)}")

    print("🏁 1단계 HTML 수집 프로세스가 완료되었습니다.")

if __name__ == "__main__":
    main()