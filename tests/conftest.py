"""테스트 공용 픽스처 — 실 DB 를 쓰는 테스트가 서로의 데이터를 밟지 않게 한다.

## 왜 필요한가

팀 4명이 같은 Supabase 를 본다. 테스트가 만든 행에 표시가 없으면 남의 테스트 결과에
섞여 들어가고("실패 3건" 이 누구 것인지 알 수 없다), 정리하려다 남의 행을 지운다.
그래서 이 파일은 두 가지만 제공한다 — **고유 접두어**와 **그 접두어 행만 지우는 정리**다.

## 🔴 이 파일은 tests/ 전체에 자동 적용된다

pytest 가 conftest.py 를 자동 로드하므로 여기 있는 것은 기존 테스트 파일 전부에 영향을
준다. 그래서 규칙이 있다.

- **autouse=True 를 쓰지 않는다.** 쓰는 순간 DB 를 안 쓰는 기존 테스트까지 연결을 열고,
  .env 가 없는 CI 에서 스위트 전체가 죽는다.
- **세션/모듈 스코프를 쓰지 않는다.** 스코프가 넓으면 한 테스트가 남긴 상태가 다음
  테스트로 새고, 정리 시점이 테스트 경계와 어긋난다.
- **모듈 최상단에서 DB·앱을 임포트하지 않는다.** conftest 임포트가 실패하면 수집 단계에서
  스위트 전체가 죽는다. 아래 임포트는 전부 픽스처 안에 있다.

즉 **명시적으로 요청한 테스트만** 영향을 받는다. 현재 tests/ 의 다른 파일들은 DB 없이
돌고 있으며(SQL 컴파일 비교 · dependency_overrides 가짜 세션), 이 파일이 생겨도 그대로다.

## 쓰는 법

    def test_failed_runs_show_up_in_the_summary(db_session, test_prefix, db_cleanup):
        from schema import rag_runs
        db_cleanup(rag_runs, rag_runs.c.session_id)      # 정리 대상 등록(먼저)
        db_session.execute(rag_runs.insert(), {
            "question": "질문", "session_id": test_prefix + "sess", "status": "FAILED",
        })
        db_session.commit()
        ...

등록한 (테이블, 컬럼) 에 대해 테스트가 끝나면 `컬럼 LIKE '<접두어>%'` 인 행만 지운다.
접두어는 테스트마다 새로 만들어지므로 같은 순간 남이 돌리는 테스트의 행은 건드리지 않는다.
"""
import os
import sys
import uuid
from pathlib import Path

import pytest

# `python tests/xxx.py` 로도 실행되도록 저장소 루트를 넣는다(기존 테스트 파일과 같은 관례).
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# 테스트가 만든 행임을 사람이 눈으로 알아보는 표시. 접두어 전체는 여기에 8자리를 더한 값이라
# 같은 순간 여러 명이 돌려도 겹치지 않는다.
TEST_PREFIX = "test_"

# 추가 전용이라 정리할 수 없는 표. 감사 기록을 테스트가 지울 수 있으면 감사 기록이 아니다
# (api/routers/admin_activity.py 모듈 주석). 실수로 등록하면 조용히 넘어가지 않고 막는다 —
# 90일 남는 표라 한 번 지우면 되돌릴 방법이 없다.
APPEND_ONLY_TABLES = frozenset({"admin_activity_logs"})


@pytest.fixture
def test_prefix() -> str:
    """이 테스트가 만드는 행에 붙일 고유 접두어. 예: `test_9f2c1a04_`

    테스트마다 새로 만든다. 고정 문자열 하나를 공유하면 A 가 정리하는 순간 동시에 돌던
    B 의 행까지 지워져서, 원인을 알 수 없는 간헐적 실패가 된다.
    """
    return f"{TEST_PREFIX}{uuid.uuid4().hex[:8]}_"


@pytest.fixture
def db_session():
    """실 Supabase 세션. 이 픽스처를 요청한 테스트만 연결을 연다.

    DATABASE_URL 이 없거나 연결이 안 되면 실패가 아니라 skip 이다 — DB 자격증명 없이
    돌리는 사람(그리고 현재의 CI)에게 남의 기능이 깨진 것처럼 보이면 안 된다.

    연결 확인을 세션을 넘기기 **전에** 따로 한다. sessionmaker 는 첫 쿼리 전까지 실제로
    붙지 않아서, with 블록을 여는 것만으로는 연결 가능 여부를 알 수 없다. 또 세션을 넘긴
    뒤에 예외를 잡으면 테스트 본문의 assert 실패까지 skip 으로 둔갑한다 — 깨진 테스트가
    초록으로 보이는 것이 여기서 제일 위험한 실수다.
    """
    try:
        import api  # noqa: F401  — src/ 를 sys.path 에 올린다
        from db import get_engine, get_session
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"DB 모듈을 불러올 수 없어 건너뜀: {exc}")

    # src/db.py 가 임포트 시점에 .env 를 읽으므로 이 확인은 임포트 뒤여야 한다.
    if not os.environ.get("DATABASE_URL"):
        pytest.skip("DATABASE_URL 이 없어 건너뜀 (.env 확인)")

    from sqlalchemy import text
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"DB 에 연결할 수 없어 건너뜀: {exc}")

    # 여기부터는 예외를 삼키지 않는다. 테스트가 실패하면 get_session 이 롤백하고 그대로 올린다.
    with get_session() as session:
        yield session


@pytest.fixture
def db_cleanup(test_prefix):
    """정리 대상 등록기. `db_cleanup(테이블, 컬럼)` 로 등록하면 테스트가 끝날 때
    `컬럼 LIKE '<접두어>%'` 인 행을 지운다.

    등록을 **행을 만들기 전에** 해 두는 편이 안전하다. 테스트가 도중에 실패해도 등록된
    것은 정리되기 때문이다(픽스처 teardown 은 실패해도 돈다).

    정리는 테스트가 쓰던 세션이 아니라 새 세션으로 한다. 실패한 테스트의 세션은 롤백이
    필요한 상태로 남아 있을 수 있는데, 그 세션으로 지우려 들면 정리까지 같이 죽는다.
    """
    registry = []

    def register(table, column):
        if table.name in APPEND_ONLY_TABLES:
            raise ValueError(
                f"{table.name} 은 추가 전용이라 정리할 수 없다. 이 표를 건드리는 테스트는 "
                f"actor 등에 '{TEST_PREFIX}' 접두어를 붙여 눈으로 구분되게만 하고, "
                f"지우려 하지 마라.")
        registry.append((table, column))

    yield register

    if not registry:
        return

    from sqlalchemy import delete
    from db import get_session

    pattern = f"{test_prefix}%"
    try:
        with get_session() as session:
            # 등록 역순으로 지운다. 나중에 등록한 것이 앞의 것을 참조할 수 있다.
            for table, column in reversed(registry):
                session.execute(delete(table).where(column.like(pattern)))
    except Exception as exc:  # noqa: BLE001
        # 정리 실패로 테스트를 실패시키지는 않되(이미 검증은 끝났다) 조용히 넘기지도 않는다 —
        # 남은 행은 팀 공용 DB 에 계속 쌓인다.
        print(f"[conftest] 테스트 행 정리 실패 — 접두어 {test_prefix} 를 수동 확인할 것: {exc}")
