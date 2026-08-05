"""라우터가 Depends() 로 받아 쓰는 공통 자원 — 설정, DB 세션, request_id.

## Depends 를 왜 쓰나

라우터 안에서 직접 get_settings() 나 get_session() 을 부르면 동작은 한다. 그런데
Depends 로 받으면 두 가지를 얻는다.

1. 정리(cleanup)를 FastAPI가 책임진다. DB 세션은 yield 뒤 코드가 응답이 끝난 다음
   반드시 실행되므로 commit/rollback/close 를 빠뜨릴 수 없다.
2. 테스트에서 app.dependency_overrides[get_db] = ... 로 통째로 갈아끼울 수 있다.
   라우터 안에서 직접 부르면 이게 불가능하다.

## 타입 별칭(Annotated)

    def handler(db: DbSession): ...

처럼 쓰라고 아래에서 Annotated 별칭을 만들어 둔다. 매번
`db: Session = Depends(get_db)` 라고 쓰는 것보다 짧고, 의존성을 바꿀 때 한 곳만 고친다.
"""
from typing import Annotated, Optional

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from api.config import Settings, get_settings

# src/db.py 를 flat import 한다 — api/__init__.py 가 sys.path 에 src/ 를 넣어줘서
# 가능하다. src/ 쪽 import 스타일을 그대로 따르는 것이라 의도된 모양이다.
from db import get_session


def get_settings_dep() -> Settings:
    """설정 의존성.

    config.get_settings() 를 그대로 쓰지 않고 한 겹 감싸는 이유는 오직 테스트다 —
    dependency_overrides 의 키로 쓸 함수가 필요하다. 값 자체는 lru_cache 된 같은 객체다.
    """
    return get_settings()


def get_db():
    """요청 하나당 DB 세션 하나.

    src/db.py 의 get_session() 은 이미 contextmanager 라, 블록을 빠져나갈 때
    commit(정상) 또는 rollback(예외) 후 close 까지 한다. 여기서는 그 블록을
    "요청 처리 전체"로 늘리기만 한다 — yield 아래 줄은 응답이 끝난 뒤 실행되고,
    핸들러에서 예외가 나면 FastAPI 가 그 예외를 이 제너레이터 안으로 다시 던져줘서
    get_session() 의 rollback 이 정상적으로 걸린다.

    def(async def 아님)로 선언한 것도 의도적이다. SQLAlchemy 동기 세션은 블로킹이라,
    async def 로 두면 이벤트 루프를 막는다. 동기 함수로 두면 FastAPI 가 알아서
    스레드풀에서 돌린다.

    주의: 챗봇 답변 경로는 이 의존성이 필요 없다. src/rag_logger.py 가 자체적으로
    (실패해도 답변을 막지 않는 방식으로) 로깅하기 때문이다. DB 가 실제로 필요한
    관리자용 라우터에서만 쓸 것.
    """
    with get_session() as session:
        yield session


def get_request_id(request: Request) -> Optional[str]:
    """미들웨어가 scope 에 넣어둔 요청 id. 응답 본문에 request_id 를 함께 실어
    보내야 하는 라우터에서 쓴다(오류 응답은 errors.py 가 알아서 채운다)."""
    return getattr(request.state, "request_id", None)


SettingsDep = Annotated[Settings, Depends(get_settings_dep)]
DbSession = Annotated[Session, Depends(get_db)]
RequestId = Annotated[Optional[str], Depends(get_request_id)]

# 인증 의존성(get_current_user 등)은 여기 들어올 자리지만, auth 라우터를 실제로
# 만들 때 함께 추가한다 — 지금 만들면 아무도 안 쓰는 죽은 코드가 된다.
