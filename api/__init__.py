"""FastAPI 백엔드 패키지 — src/ 를 import 가능하게 만드는 경로 설정을 여기서 한 번만 한다.

src/ 에는 __init__.py 가 없고, 내부 모듈끼리 flat import 로 서로를 부른다
(예: pipeline.py 의 `from retrieval import route_search_chunks`). 지금까지는
`streamlit run src/app.py` 로 실행해서 파이썬이 스크립트 폴더인 src/ 를 sys.path 에
자동으로 넣어줬기 때문에 이게 동작했다.

uvicorn 은 저장소 루트에서 `api.main:app` 을 띄우므로 sys.path 에 루트만 들어간다.
그 상태로 pipeline 을 import 하면 `ModuleNotFoundError: retrieval` 로 죽는다.
해결책은 두 가지였다 —

  (a) src/ 전체를 패키지로 만들고 모든 import 를 `from src.retrieval import ...` 로 수정
  (b) src/ 를 sys.path 에 넣어 지금 import 스타일을 그대로 유지

기존 코드를 최대한 건드리지 않는다는 원칙에 따라 (b) 를 택했다. api 패키지를 import 하는
순간(= api.main 이 로드되기 전) 이 파일이 먼저 실행되므로, api/ 안의 어떤 모듈이든
`from pipeline import rag_answer` 처럼 부를 수 있다.

주의: src/ 를 sys.path 앞에 넣으므로 src/ 안의 모듈 이름이 최상위 이름이 된다. 표준
라이브러리나 설치된 패키지와 겹치는 이름(예: schema.py)을 src/ 에 추가할 때 조심할 것.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
