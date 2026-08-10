"""관리자(admin) 스키마 — 로그인/세션/활동로그 3개 테이블 + documents 확장 컬럼.

src/schema.py(서비스 본 스키마)와 파일을 나눈 이유: 관리자 기능은 별도 배치라 본 스키마와
생성/변경 시점이 다르고, 팀원이 이 파일만 돌려 관리자 테이블을 반영할 수 있게 하기 위함이다.
schema.py 는 건드리지 않는다.

self-contained: 아래 admin_metadata 에는 관리자 3개 테이블만 담는다 — main() 의
create_all(checkfirst=True) 이 이 3개만 만들고, documents 같은 기존 테이블은 절대 안 건드린다.
documents 확장은 기존 테이블(데이터 있음)이라 create_all 이 아니라 ALTER TABLE ADD COLUMN
IF NOT EXISTS 로 멱등하게 더한다(schema.py main() 이 evaluation_dataset·rag_runs 에 쓰는 방식과 동일).

실행: python src/schema_admin.py   (Supabase DATABASE_URL 에 반영. 여러 번 돌려도 안전)

── 설계 근거(2026-08 프론트 계약·핸드오프 대조) ──
- admin_activity_logs 의 실행자 컬럼은 executor 가 아니라 actor 다(프론트 목/화면이 actor 를 씀).
  "추가 전용·조인 금지·상세는 이 레코드 하나로 렌더"(CM-DF-003 §04)라, 화면이 top-level 로 그리는
  occurred_at·actor_role·ip·request_id 를 컬럼으로 둔다.
- documents 는 프론트에서 실제 쓰이거나(owner·collection_status·index_status·split_rule) 핸드오프
  §6 이 요구하는(collection_note K11 · link_check·first_indexed_at K2) 7개만 더한다.
  pending_action 은 뺐다 — '적용 대기'는 change_requests 조인으로 나오는 값이라 컬럼으로 두면
  비정규화(두 곳이 어긋남)다.
- 로그인 잠금(admin_login_failures)·비밀번호 재설정(password_reset_tokens)은 Phase 2 로 미룬다.
  지금 로그인을 돌리는 데는 이 3개면 충분하고, 첫 계정은 시드 스크립트로 넣는다.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from db import get_engine  # noqa: E402

from sqlalchemy import (  # noqa: E402
    Column, DateTime, ForeignKey, MetaData, String, Table, Text, func, text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID  # noqa: E402

admin_metadata = MetaData()


def _uuid_pk():
    # schema.py 와 동일 관례 — Postgres 가 UUID 를 생성(gen_random_uuid()).
    return Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=text("gen_random_uuid()"))


# ── 1. admin_accounts — 관리자 계정 ──
# role enum:   ADMIN / EDITOR / OPERATOR / VIEWER   (프론트 actor_role 과 동일)
# status enum: 활성 / 비활성 / 초대됨 / 잠김        (A5, 계정 상태와 세션 상태는 분리)
admin_accounts = Table(
    "admin_accounts", admin_metadata,
    _uuid_pk(),
    Column("email", String, unique=True, nullable=False),       # 로그인 ID
    Column("name", String, nullable=False),                     # 화면 표시용 이름
    Column("password_hash", String, nullable=False),            # 비번 해시(평문 저장 금지)
    Column("role", String, nullable=False),                     # 권한(RBAC)
    Column("status", String, nullable=False, server_default=text("'활성'")),  # 계정 상태
    Column("last_login_at", DateTime(timezone=True)),           # 마지막 로그인(계정 목록 표시)
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)


# ── 2. admin_sessions — 로그인 세션 (세션 3-타이머: 절대 8h / 유휴 30분 / 재인증 30분) ──
admin_sessions = Table(
    "admin_sessions", admin_metadata,
    Column("id", String, primary_key=True),                     # 세션 토큰(httpOnly 쿠키 값)
    Column("account_id", UUID(as_uuid=True), ForeignKey("admin_accounts.id"), nullable=False),
    Column("session_started_at", DateTime(timezone=True), nullable=False, server_default=func.now()),  # 절대 만료 8h 기준
    Column("last_activity_at", DateTime(timezone=True), nullable=False, server_default=func.now()),     # 유휴 만료 30분 기준
    Column("last_auth_at", DateTime(timezone=True), nullable=False, server_default=func.now()),         # 위험작업 재인증 30분 기준(A8)
    Column("revoked_at", DateTime(timezone=True)),              # 로그아웃·강제종료 시각. NULL=유효(A7)
)


# ── 3. admin_activity_logs — 활동 로그 (추가 전용·90일 보관·조인 금지) ──
# 계정 FK 를 일부러 안 건다: 실행자 email/역할을 쓰는 시점 값으로 박아 계정이 나중에 바뀌거나
# 삭제돼도 로그가 그대로 남고, 상세를 이 한 행으로만 렌더한다(조인 금지, CM-DF-003 §04).
admin_activity_logs = Table(
    "admin_activity_logs", admin_metadata,
    _uuid_pk(),
    Column("occurred_at", DateTime(timezone=True), nullable=False, server_default=func.now()),  # 발생 시각
    Column("actor", String, nullable=False),                    # 실행자 email
    Column("actor_role", String),                               # 실행자 역할(그 시점 스냅샷)
    Column("action", String, nullable=False),                   # 작업(예: 로그인, 변경 요청 승인)
    Column("target", String),                                   # 대상(예: page_id, cr_003)
    Column("result", String),                                   # 결과(성공/실패/거부됨)
    Column("reason", Text),                                     # 사유(위험작업 reason)
    Column("before_value", Text),                               # 변경 전 값(§04 전후값)
    Column("after_value", Text),                                # 변경 후 값
    Column("request_id", String),                              # 멱등키/추적
    Column("ip", String),                                       # 실행 IP
    Column("detail", JSONB),                                    # 부가 상세(§04 detail)
)


# ── documents 확장 컬럼 (기존 테이블 → ALTER, 전부 NULL 허용) ──
# (컬럼명, Postgres 타입). 근거는 파일 상단 참고. pending_action 은 의도적으로 제외.
_DOCUMENTS_NEW_COLUMNS = [
    ("owner", "text"),               # 담당자 (프론트 사용, K2·K3·K8)
    ("collection_status", "text"),   # 수집 상태 CANDIDATE/LOADED/ROBOTS_BLOCKED/SKIPPED/FAILED (K3)
    ("index_status", "text"),        # 색인 상태 (K1, state 3상태 연계)
    ("split_rule", "text"),          # 청크 분할 방식 (K3·K4)
    ("collection_note", "text"),     # 수집/협의 사유 텍스트 (K11)
    ("link_check", "text"),          # 링크 점검 결과/상태 (K2)
    ("first_indexed_at", "timestamptz"),  # 최초 색인 시각 (K2)
]


def main():
    engine = get_engine()
    with engine.begin() as conn:
        # admin 3개 테이블 생성(이미 있으면 건너뜀). documents 는 이 metadata 에 없어 안 건드림.
        admin_metadata.create_all(conn, checkfirst=True)
        # documents 확장 — 기존 테이블이라 create_all 이 컬럼을 안 더하므로 멱등 ALTER.
        for name, coltype in _DOCUMENTS_NEW_COLUMNS:
            conn.execute(text(f"ALTER TABLE documents ADD COLUMN IF NOT EXISTS {name} {coltype}"))
    print("admin 테이블 생성/확인:", ", ".join(t.name for t in admin_metadata.sorted_tables))
    print("documents 확장 컬럼:", ", ".join(n for n, _ in _DOCUMENTS_NEW_COLUMNS))


if __name__ == "__main__":
    main()
