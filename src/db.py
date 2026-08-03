"""Supabase Postgres(pgvector) 연결 — SQLAlchemy + psycopg3.

DATABASE_URL은 transaction pooler(:6543)를 가리킨다. pgbouncer transaction
모드는 prepared statement를 세션 간 공유하지 못하므로 psycopg3의
prepare_threshold=None으로 꺼둔다. pgbouncer가 이미 커넥션을 풀링하므로
SQLAlchemy 쪽 풀은 NullPool로 둬서 이중 풀링을 피한다.

실행: python -m src.db  (연결 확인 + pgvector 확장 버전 출력)
"""
import os
from contextlib import contextmanager
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

_state = {}


def get_engine():
    if "engine" not in _state:
        url = make_url(os.environ["DATABASE_URL"])
        if url.drivername == "postgresql":
            url = url.set(drivername="postgresql+psycopg")
        _state["engine"] = create_engine(
            url, poolclass=NullPool, connect_args={"prepare_threshold": None},
        )
    return _state["engine"]


def _session_factory():
    if "Session" not in _state:
        _state["Session"] = sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False)
    return _state["Session"]


@contextmanager
def get_session():
    """with get_session() as session: ... 형태로 사용 — 블록 끝나면 commit, 예외 시 rollback."""
    session = _session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def main():
    with get_session() as session:
        version = session.execute(text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")).scalar()
        if version is None:
            raise RuntimeError(
                "pgvector 확장이 Supabase에 활성화돼 있지 않음. "
                "Dashboard > Database > Extensions에서 vector를 켜거나 "
                "SQL Editor에서 CREATE EXTENSION IF NOT EXISTS vector; 실행 필요."
            )
        print(f"연결 성공. pgvector {version}")


if __name__ == "__main__":
    main()
