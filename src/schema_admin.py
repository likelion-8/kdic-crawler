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
  → **2026-08-12 Phase 2 착수**. 아래 "Phase 2" 절 참고.

── Phase 2 (2026-08-12) — 남은 관리자 화면 5개가 요구하는 14 테이블 ──

AD-000/010(접근 관리) · AD-006(평가) · AD-007(RAG 파라미터) · AD-008(프롬프트·가드레일) ·
AD-009(운영 정책)를 만들려면 테이블이 하나도 없다(핸드오프 §5 "없는 것" 표). 네 명이 각자
스키마 파일을 고치면 확실히 충돌하므로 **한 커밋에 몰아서** 만든다. 엔드포인트는 각 트랙 담당이다.

전부 이 파일에 둔다 — schema.py(서비스 본 스키마)는 건드리지 않는다. 평가·RAG 파라미터·
프롬프트 테이블은 파이프라인이 읽기도 하지만, **쓰는 주체가 전부 관리자 화면**이라 생성·변경
시점이 본 스키마가 아니라 이 파일을 따라간다(파일을 나눈 원래 이유 그대로다).

값의 정본은 프론트 계약이다. 코드 값을 폐집합으로 못 박지 않고 String 으로 두는 것도
기존 관례를 따른 것이다(api/schemas/change_request.py·activity.py 와 같은 방침) — 어휘가
늘 때마다 스키마를 고치지 않기 위해서다. 각 컬럼 주석에 정본 위치를 적어 둔다.

⚠️ 세부 스펙이 기획서에 없는 자리(운영 정책 항목 목록, 평가 지표 축)는 JSONB 로 열어 둔다.
   컬럼으로 못 박으면 프론트 계약이 조금 바뀔 때마다 마이그레이션이 필요하다. 대신 그
   JSONB 안의 모양이 어디에 적혀 있는지를 주석에 반드시 남긴다.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from db import get_engine  # noqa: E402

from sqlalchemy import (  # noqa: E402
    Boolean, Column, DateTime, ForeignKey, Index, Integer, MetaData, String, Table, Text,
    func, text,
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
    # 세션 토큰의 sha256 해시(64자 hex). 쿠키로 나가는 건 토큰 원문이고 여기 남는 건 해시다 —
    # 같은 값을 양쪽에 두면 DB 가 새는 순간 모든 세션이 그대로 탈취된다(api/deps.py hash_token).
    Column("id", String, primary_key=True),
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
    # 쓰기 API 마다 한 행씩 쌓이는 테이블이라 제일 빨리 큰다. 화면은 항상 시간 역순 정렬이고
    # 90일 보관 정리도 이 컬럼으로 도니 인덱스가 없으면 둘 다 풀스캔이 된다.
    Column("occurred_at", DateTime(timezone=True), nullable=False,
           server_default=func.now(), index=True),  # 발생 시각
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


# ════════════════════════════════════════════════════════════════════════════
# Phase 2 (2026-08-12) — 남은 관리자 화면 5개용 14 테이블
# ════════════════════════════════════════════════════════════════════════════

# ─────────────────────────── A. 접근 관리 (AD-000 · AD-010) ───────────────────

# ── 4. admin_login_failures — 로그인 실패 기록 + 임시 잠금 ──
# 계정 FK 를 안 건다: **없는 이메일로 시도한 것도 기록해야** 계정 탐색(enumeration) 공격이
# 보인다. 존재하지 않는 email 이면 FK 가 그 행을 통째로 거부해 버려 정작 봐야 할 시도가 안 남는다
# (admin_activity_logs 가 FK 를 안 거는 것과 같은 판단 — 기록의 완결성이 참조 무결성보다 중요하다).
#
# locked_until 을 admin_accounts 가 아니라 여기 두는 이유: 잠금은 '계정의 속성'이 아니라
# '이 실패 묶음의 결과'다. 계정 쪽에 두면 잠금이 왜 걸렸는지 되짚을 수 없고, 없는 이메일에
# 대한 잠금은 표현할 자리조차 없다. 화면(A2)이 요구하는 것도 잔여 카운트다운 하나뿐이라
# "이 email 의 가장 최근 행"만 보면 된다.
admin_login_failures = Table(
    "admin_login_failures", admin_metadata,
    _uuid_pk(),
    # 목록(GET /login-failures, A4)과 잠금 판정이 둘 다 "이 email 의 최근 N건"을 본다.
    # 두 질의 모두 이 두 컬럼으로 도니 복합 인덱스를 아래 _NEW_INDEXES 에 함께 건다.
    Column("email", String, nullable=False),                    # 시도한 로그인 ID(계정이 없을 수도 있다)
    Column("attempted_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("ip", String),                                       # 실행 IP(api/deps.py client_ip)
    Column("user_agent", String),                               # 반복 시도 식별용
    # 이 시도로 임시 잠금이 발동했으면 해제 시각. NULL = 잠금 아님.
    # 화면은 423 응답 본문의 locked_until 로 잔여 카운트다운을 그린다(A2).
    Column("locked_until", DateTime(timezone=True)),
)

# 목록·잠금 판정이 둘 다 "이 email 의 최근 N건"을 본다. 실패 기록은 공격을 받으면 빠르게
# 커지는 표라, 인덱스가 없으면 로그인 경로가 매번 풀스캔을 탄다.
Index("ix_admin_login_failures_email_attempted",
      admin_login_failures.c.email, admin_login_failures.c.attempted_at)


# ── 5. password_reset_tokens — 비밀번호 재설정 링크 ──
# admin_sessions 와 **같은 비대칭**을 쓴다: 메일로 나가는 건 토큰 원문이고 여기 남는 건
# sha256 해시다. 같은 값을 양쪽에 두면 DB 가 새는 순간 모든 재설정 링크가 그대로 탈취된다.
#
# used_at 을 따로 두는 이유는 화면이 410(만료·사용됨)과 400(비밀번호 정책 위반)을 갈라야
# 하기 때문이다(A11). 만료는 expires_at 으로, '이미 쓴 링크'는 used_at 으로 판정한다 —
# 행을 지워 버리면 둘을 구분 못 하고 전부 '없는 링크'가 된다.
password_reset_tokens = Table(
    "password_reset_tokens", admin_metadata,
    Column("id", String, primary_key=True),                     # 토큰 원문의 sha256(64자 hex)
    Column("account_id", UUID(as_uuid=True), ForeignKey("admin_accounts.id"), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("expires_at", DateTime(timezone=True), nullable=False),   # 만료 → 410
    Column("used_at", DateTime(timezone=True)),                 # 사용됨 → 410. NULL = 아직 유효
    # 재설정 요청은 계정 존재 여부와 무관하게 항상 202 를 준다(A9). 그래서 '요청 자체'의
    # 출처를 남겨 두어야 남용을 사후에 볼 수 있다.
    Column("requested_ip", String),
)


# ─────────────────────────── B. 운영 정책 (AD-009) ────────────────────────────

# ── 6. ops_policy — 운영 정책 (버전 이력) ──
# ⚠️ 정책 **항목 목록이 기획서에 없다.** 화면(O1·O5)이 요구하는 건 "부분 패치를 받고 새
# version 을 돌려줄 것"과 "burst_per_10s 는 읽기 전용"뿐이다. 그래서 항목을 컬럼으로 못 박지
# 않고 policy JSONB 로 연다 — 컬럼으로 두면 프론트가 항목 하나 늘릴 때마다 마이그레이션이 된다.
# JSONB 안의 모양 정본: web/src/routes/admin/settings/promptops/api.ts 의 OpsPolicy.
#
# 행을 덮어쓰지 않고 버전마다 새 행을 쌓는다. 활동 로그가 전후값을 남기지만 그건 텍스트라
# 되돌리기(rollback)에 못 쓴다 — 정책은 잘못 바꾸면 서비스 전체가 막히는 값이라 이력이 필요하다.
ops_policy = Table(
    "ops_policy", admin_metadata,
    _uuid_pk(),
    # 단조 증가. 가장 큰 version 이 현재 적용본이다(is_current 플래그를 따로 두면 두 곳이
    # 어긋날 수 있어 파생 가능한 값을 저장하지 않는다).
    Column("version", Integer, nullable=False, unique=True),
    Column("policy", JSONB, nullable=False),                    # 정책 전문(부분 패치를 병합한 결과)
    Column("reason", Text, nullable=False),                     # 위험 작업이라 사유 필수(C2)
    Column("updated_by", String, nullable=False),               # 관리자 email(그 시점 스냅샷)
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)


# ── 7. query_cache — 질의 응답 캐시 ──
# 멘토링(2026-08-11)의 "반복 요청 비용·latency 감소" 항목이자 화면의 cache/stats·
# cache/purge(scope=query|all) 대상이다(O1).
#
# 질문 원문이 아니라 정규화 해시를 키로 둔다 — 공백·말줄임만 다른 같은 질문이 서로 다른 캐시가
# 되면 적중률이 무너진다. 정규화 규칙 자체는 애플리케이션 몫이라 여기서는 결과만 받는다.
query_cache = Table(
    "query_cache", admin_metadata,
    Column("cache_key", String, primary_key=True),              # 정규화된 질문의 해시
    Column("question", Text, nullable=False),                   # 원문(화면에 무엇이 캐시됐는지 보여줌)
    # 답변 1건 전체(ChatResponse 모양). 출처·첨부까지 함께 돌려줘야 캐시 적중이 의미가 있다.
    Column("response", JSONB, nullable=False),
    Column("hit_count", Integer, nullable=False, server_default=text("0")),  # cache/stats 적중률
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("last_hit_at", DateTime(timezone=True)),
    # NULL 이면 만료 없음. purge 는 이 컬럼과 무관하게 즉시 지운다.
    Column("expires_at", DateTime(timezone=True)),
)


# ── 8. rate_limit_blocks — 요청 제한 차단 목록 ──
# expires_at 은 **필수**다(O4). 화면이 만료된 행의 [해제] 버튼을 비활성화하고 남은 시간을
# 확인 모달에 표시하는데, NULL 을 허용하면 '영구 차단'이 되어 그 UI 가 표현할 수 없는 상태가 된다.
rate_limit_blocks = Table(
    "rate_limit_blocks", admin_metadata,
    _uuid_pk(),
    # 차단 대상 식별자(IP 또는 세션). 어느 쪽인지는 target_kind 로 가른다 — 값만 보고는
    # IP 인지 세션 id 인지 구분할 수 없어 화면이 라벨을 못 붙인다.
    Column("target", String, nullable=False),
    Column("target_kind", String, nullable=False),              # 'ip' | 'session'
    Column("reason", Text),                                     # 차단 사유(자동 차단이면 규칙 이름)
    Column("blocked_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    # 수동 해제 기록. NULL = 아직 유효. 행을 지우지 않는 이유는 '누가 언제 풀었나'가
    # 감사 대상이어서다(활동 로그에도 남지만 목록 화면이 이 값을 직접 읽는다).
    Column("released_at", DateTime(timezone=True)),
    Column("released_by", String),
)


# ─────────────────────────── C. 평가 (AD-006) ─────────────────────────────────

# ── 9. evaluation_runs — 평가 실행 1회 ──
# schema.py 의 evaluation_dataset(골든셋)·test_set(held-out)은 **문항**이고, 이 테이블은
# 그 문항으로 돌린 **실행**이다. schema.py 상단이 "evaluation_runs/evaluation_results 는
# 운영 단계 착수 전이라 아직 안 만든다"고 적어 둔 바로 그 두 개다.
evaluation_runs = Table(
    "evaluation_runs", admin_metadata,
    _uuid_pk(),
    Column("target", String, nullable=False),                   # 무엇을 평가했나(RAG / 프롬프트 등)
    # 실행 출처 4종(수동 실행 / 프롬프트 게시 게이트 / 파이프라인 후속 / RAG 파라미터 평가).
    # 고정 코드값 사전이 아직 CM-DF-002 에 없어(E9) String 으로 두고 정본이 정해지면 맞춘다.
    Column("source", String),
    Column("testset_version", String),                          # 어떤 버전의 문항으로 쟀나(E3)
    # ⚠️ 지표를 숫자 4컬럼으로 두지 않는다. 대상별로 축이 다르다(RAG=정확도/MRR/생성,
    # 프롬프트=회귀/인용/중대 위반) — E1 이 [{label, value}] 배열을 요구하는 이유다.
    # 반올림까지 끝낸 문자열로 저장한다(서버가 표기를 확정, E1).
    Column("metrics", JSONB),
    # 게이트 판정 전문. 목록의 passed 와 상세의 기준별 판정이 어긋나면 안 되므로(E10)
    # 한 곳에 함께 담아 두 화면이 같은 값을 읽게 한다.
    # 목표값(0.92↑/0.80↑/99.5%↑/10초↓/30of30)도 여기 실어 내려보낸다 — 프론트 상수로 박으면
    # '관리자 화면에서 기준을 낮추는 우회'를 막는 설계가 무너진다(E4).
    Column("gate", JSONB),
    Column("follow_up", String),                                # '→ 11:40 반영됨' 같은 후속 표시(E3)
    Column("improved_by_composition", Boolean),                 # E3
    Column("triggered_by", String),                             # 실행자 email(자동 실행이면 NULL)
    Column("started_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("finished_at", DateTime(timezone=True)),             # NULL = 실행 중
    Column("status", String),                                   # RUNNING / DONE / FAILED
)


# ── 10. evaluation_results — 실행 1회의 문항별 결과 ──
# run 당 문항 수만큼 쌓인다. rag_retrieval_results 를 "질문 1건당 20행 부담"으로 지웠던
# 전례가 있으나(schema.py 상단) 이쪽은 성격이 다르다 — 평가는 사용자 트래픽이 아니라
# 사람이 돌리는 배치라 행이 늘어나는 속도가 비교가 안 되고, 회귀를 문항 단위로 짚는 것이
# 이 화면의 존재 이유다.
evaluation_results = Table(
    "evaluation_results", admin_metadata,
    _uuid_pk(),
    Column("run_id", UUID(as_uuid=True), ForeignKey("evaluation_runs.id"), nullable=False),
    # 문항 식별자. testset_items.id 를 가리키지만 FK 는 걸지 않는다 — 문항이 나중에 빠져도
    # 지난 실행 결과는 그대로 남아야 한다(그때 무엇으로 쟀는지가 기록의 요점이다).
    Column("item_id", String),
    Column("question", Text),                                   # 그 시점 문항 문구(스냅샷)
    Column("passed", Boolean),
    # 지표별 점수·실제 출력. 축이 대상마다 달라 runs.metrics 와 같은 이유로 JSONB 다.
    Column("detail", JSONB),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)


# ── 11. testset_items — 편집 가능한 평가 문항 + 버전 ──
# 현 evaluation_dataset/test_set 에는 버전·편집 이력 컬럼이 없어 화면의 문항 편집(E6)과
# testset_version(E3)을 표현할 수 없다. 그 두 테이블을 건드리지 않고 편집용 사본을 둔다.
#
# 반영(apply)은 **버전 증가 1회 + 재측정 1회가 한 트랜잭션**이다(E7). 여러 건을 편집해도
# 재측정은 한 번이라, 편집 낱건이 아니라 버전 단위로 행을 쌓는다.
testset_items = Table(
    "testset_items", admin_metadata,
    _uuid_pk(),
    Column("testset_version", String, nullable=False),          # 이 문항이 속한 버전
    Column("question", Text, nullable=False),
    # 기대 출처·업무 분류. 실제 testset jsonl(data/testset/*.jsonl)이 이미 두 필드를 갖고 있고
    # schema.py 의 evaluation_dataset 도 같은 이유로 들고 있다.
    Column("expected_links", JSONB),
    Column("business_function", String),
    # CM-DF-002 평가셋 라벨 2종 — AD-006 편집 폼·목록 칼럼이 이 값을 쓴다(2026-08-13 추가.
    # 종전에는 컬럼이 없어 편집 폼의 유형·성격 값이 apply 에서 조용히 버려졌다).
    Column("question_type", String),
    Column("intent", String),
    Column("reference_answer", Text),
    # 제외는 행을 지우지 않고 표시만 한다 — 왜 뺐는지가 다음 버전에서 다시 필요하다.
    # 제외에는 reason 이 필수다(E6 apply 의 excludes[{item_id, reason}]).
    Column("excluded", Boolean, nullable=False, server_default=text("false")),
    Column("exclude_reason", Text),
    Column("created_by", String),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)


# ─────────────────────────── D. RAG 파라미터 (AD-007) ─────────────────────────

# ── 12. rag_param_versions — RAG 파라미터 버전 (current 1 · draft 1 · history N) ──
# 지금 파라미터는 전부 파이썬 상수다(pipeline.K_CANDIDATES=20 · K_FINAL=5 · USE_RERANKER ·
# USE_QUERY_DECOMPOSITION · USE_SOURCE_RECHECK, query_planner.USE_QUERY_PLANNER,
# candidate_ranking.MIN_TOP1_SCORE=0.35, retrieval.HYBRID_LINEAR_ALPHA=0.4 ·
# retrieval.USE_TYPE_ROUTING=False).
#
# ⚠️ 이 테이블이 비어 있어도 파이프라인은 **오늘과 똑같이** 돌아야 한다. 읽는 쪽
# (src/runtime_config.py)이 값이 없으면 코드 상수로 떨어지는 폴백 구조라, 여기 행이 없다는 것은
# '기본값 사용'이라는 정상 상태다. 롤백도 행 하나 지우면 끝이다.
#
# 상태를 세 행 종류(current/draft/history)로 두는 대신 status 컬럼 하나로 표현하고,
# current·draft 가 각각 최대 1개임을 부분 유니크 인덱스로 DB 가 강제한다(아래 Index 참고) —
# 애플리케이션 규칙으로만 두면 동시 요청 두 개가 current 를 둘 만든다.
rag_param_versions = Table(
    "rag_param_versions", admin_metadata,
    _uuid_pk(),
    Column("version", Integer, nullable=False, unique=True),
    Column("status", String, nullable=False),                   # 'current' | 'draft' | 'history'
    # 파라미터 전문(name -> value). 항목이 늘 때마다 마이그레이션하지 않으려고 JSONB 다.
    # 메타(min/max/step·옵션·눈금)는 서버가 내려주는 값이라(R1) 코드 쪽 정의를 정본으로 삼고
    # 여기에는 실제 값만 담는다.
    Column("params", JSONB, nullable=False),
    # 평가한 초안의 지문. '평가 이후 초안을 수정하면 평가 무효화'를 판정하려면 무엇을
    # 평가했는지 서버가 알아야 한다(R2).
    Column("draft_signature", String),
    Column("evaluation_run_id", UUID(as_uuid=True)),            # 이 초안을 잰 실행(FK 안 검 — 실행이 지워져도 값은 남는다)
    Column("reason", Text),                                     # apply 는 reason 필수(R3)
    Column("updated_by", String),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("applied_at", DateTime(timezone=True)),              # current 가 된 시각
)

# current 와 draft 는 각각 최대 1행. history 는 제한 없음 → 부분 유니크로 표현한다.
Index("uq_rag_param_versions_current", rag_param_versions.c.status,
      unique=True, postgresql_where=text("status = 'current'"))
Index("uq_rag_param_versions_draft", rag_param_versions.c.status,
      unique=True, postgresql_where=text("status = 'draft'"))


# ─────────────────────── E. 프롬프트·가드레일 (AD-008) ────────────────────────

# ── 13. prompt_versions — 게시된 프롬프트 버전 ──
# 지금은 prompt_builder.SYSTEM_INSTRUCTION · FEW_SHOT_EXAMPLES · NO_EVIDENCE_NOTICE 가
# 파이썬 문자열 상수다. rag_param_versions 와 같은 폴백 전제 — 비어 있으면 코드 상수를 쓴다.
#
# 게시본은 **덮어쓰지 않는다.** 긴급 롤백(M5)이 "직전 버전으로 즉시 되돌리기"라 이전 본문이
# 그대로 남아 있어야 한다.
prompt_versions = Table(
    "prompt_versions", admin_metadata,
    _uuid_pk(),
    Column("version", Integer, nullable=False, unique=True),
    Column("is_current", Boolean, nullable=False, server_default=text("false")),
    Column("system_instruction", Text, nullable=False),
    Column("few_shot", JSONB),                                  # FEW_SHOT_EXAMPLES 와 같은 모양
    Column("no_evidence_notice", Text),
    # 금칙어·마스킹 규칙. 초안 객체 안에 함께 실려 오므로(M3) 게시본에도 함께 굳힌다 —
    # 따로 두면 "이 프롬프트가 게시될 때 어떤 가드레일이었나"를 되짚을 수 없다.
    Column("guardrails", JSONB),
    # 옛 게시 Smoke 결과. 게시 직후 Smoke 는 2026-08-24 폐지해 새 게시는 채우지 않는다 —
    # 지난 게시본의 판정 기록이 남아 있어 컬럼은 지우지 않는다(create_all 은 컬럼 삭제를
    # 못 하고, 버전 목록의 '실패' 표기가 그 값으로 옛 기록을 그대로 보여 준다).
    Column("smoke_passed", Integer),
    Column("smoke_total", Integer),
    Column("published_by", String),
    # 게시 사유. 화면(promptops PromptVersion.reason)이 버전 목록 행마다 표시한다.
    # 2026-08-12 추가 — 기존 DB 에는 main() 의 멱등 ALTER 로 반영된다.
    Column("reason", Text),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

# 게시본 중 현재 적용본은 하나뿐이다. rag_param_versions 와 같은 이유로 DB 가 강제한다.
Index("uq_prompt_versions_current", prompt_versions.c.is_current,
      unique=True, postgresql_where=text("is_current"))


# ── 14. prompt_drafts — 작성 중인 프롬프트 초안 ──
# 🔴 초안 상태를 **서버가 갖는다**(M2). PUT 응답에 change_count·dirty·char_count 를 실어야 하고,
# 초안이 바뀌면 evaluation 을 null 로 무효화하는 것도 서버 책임이다 — 프론트는 diff 를
# 계산하지 않기로 계약돼 있다.
prompt_drafts = Table(
    "prompt_drafts", admin_metadata,
    _uuid_pk(),
    # 초안 전문(system_instruction·few_shot·guardrails 를 한 덩어리로).
    # 정본 모양: web/src/routes/admin/settings/promptops/api.ts 의 PromptDraftContent.
    Column("content", JSONB, nullable=False),
    Column("change_count", Integer, nullable=False, server_default=text("0")),
    # 어느 구획이 더러운가(prompt/fewshot/guardrail). 화면이 탭마다 변경 표시를 그린다.
    Column("dirty", JSONB),
    Column("char_count", Integer),
    # 이 초안을 잰 평가 결과. 초안이 바뀌면 서버가 NULL 로 되돌린다(M2).
    Column("evaluation", JSONB),
    Column("base_version", Integer),                            # 어느 게시본에서 갈라져 나왔나
    Column("updated_by", String),
    Column("updated_at", DateTime(timezone=True), nullable=False,
           server_default=func.now(), onupdate=func.now()),
)


# ── 15. prompt_publish_requests — 게시 요청 (승인 / 반려 / 취소) ──
# 프롬프트는 답변 품질을 통째로 바꾸는 값이라 작성자와 승인자를 나눈다(M1).
prompt_publish_requests = Table(
    "prompt_publish_requests", admin_metadata,
    _uuid_pk(),
    Column("draft_id", UUID(as_uuid=True), ForeignKey("prompt_drafts.id")),
    # 요청 시점 초안 스냅샷. 초안은 계속 바뀌므로 draft_id 만 두면 승인자가 본 것과 실제로
    # 게시되는 것이 달라진다 — 승인 절차가 있는 이유 자체가 무너진다.
    Column("content", JSONB, nullable=False),
    Column("status", String, nullable=False),                   # PENDING / APPROVED / REJECTED / CANCELLED
    Column("requested_by", String, nullable=False),
    Column("requested_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("decided_by", String),                               # 승인·반려한 관리자
    Column("decided_at", DateTime(timezone=True)),
    Column("reason", Text),                                     # 반려 사유 / 취소 사유
    # 승인 시 만들어진 게시본. 활동 로그 상세의 approval 블록이 이 연결을 쓴다(L3).
    Column("published_version", Integer),
)


# ── 16. guardrail_rules — 금칙어·마스킹 규칙 ──
# 초안·게시본 안에도 JSONB 로 함께 실리지만(M3) 규칙 자체를 행으로도 둔다. 검증
# (POST /guardrails/masking/validate, M6)이 규칙 낱개를 대상으로 하고, 미통과 규칙이 섞인
# PUT 을 400 으로 막으려면 "이 규칙이 검증을 통과했는가"를 규칙 단위로 들고 있어야 한다.
#
# ⚠️ 초안 JSONB 와 이 표가 어긋나지 않게 하는 것은 애플리케이션 책임이다(M3 가 지적한 동기화
# 규칙). 정본은 초안 쪽이고 이 표는 검증 상태를 붙여 두는 곳으로 쓴다.
guardrail_rules = Table(
    "guardrail_rules", admin_metadata,
    _uuid_pk(),
    Column("kind", String, nullable=False),                     # 'blocklist' | 'masking'
    Column("pattern", Text, nullable=False),                    # 금칙어 또는 정규식
    Column("replacement", Text),                                # 마스킹 치환 문자열
    # 정규식 문법 오류·과대 매칭을 **서버가 판정**한 결과다(M6). 화면이 이 값으로
    # 저장 버튼을 막는다.
    Column("validated", Boolean, nullable=False, server_default=text("false")),
    Column("validation_message", Text),
    Column("active", Boolean, nullable=False, server_default=text("true")),
    Column("updated_by", String),
    Column("updated_at", DateTime(timezone=True), nullable=False,
           server_default=func.now(), onupdate=func.now()),
)


# ─────────────────────────── 공용 ────────────────────────────────────────────

# ── 17. admin_drafts — 화면별 입력 자동저장 (10초) ──
# 관리자 화면 여러 곳이 긴 폼을 쓰는데 세션이 유휴 30분에 끊긴다. 자동저장이 없으면 작성 중인
# 내용이 통째로 날아간다(PUT /api/admin/drafts/{screen}).
#
# 화면당 사람당 한 벌이면 충분하다 — 같은 화면을 두 탭에서 열면 나중 저장이 이기는 게
# 자연스럽다. 그래서 (screen, account_id) 를 복합 기본키로 두고 덮어쓴다. 이력은 남기지
# 않는다(자동저장은 기록이 아니라 임시 보관이다).
admin_drafts = Table(
    "admin_drafts", admin_metadata,
    Column("screen", String, primary_key=True),                 # 화면 식별자(AD-006 등)
    Column("account_id", UUID(as_uuid=True), ForeignKey("admin_accounts.id"), primary_key=True),
    Column("content", JSONB, nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False,
           server_default=func.now(), onupdate=func.now()),
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


# ── 기존 테이블에 뒤늦게 추가한 인덱스 ──
# create_all(checkfirst=True) 은 테이블이 이미 있으면 통째로 건너뛴다 — 컬럼에 index=True 를
# 나중에 붙여도 이미 만들어진 DB 에는 반영되지 않는다. 그래서 컬럼 쪽 index=True(새 DB 용)와
# 아래 멱등 CREATE INDEX(기존 DB 용)를 둘 다 둔다. 이름은 SQLAlchemy 기본 규칙(ix_<표>_<열>)과
# 같게 맞춰 두 경로가 같은 인덱스를 가리키게 한다.
_NEW_INDEXES = [
    ("ix_admin_activity_logs_occurred_at", "admin_activity_logs", "occurred_at"),
    # 업무 분류는 목록 필터의 정확 일치 조건이고, 아래 청크 수 집계는
    # document_chunks.document_id로 documents와 연결한다.
    ("ix_documents_business_function", "documents", "business_function"),
    ("ix_document_chunks_document_id", "document_chunks", "document_id"),
]


def _missing_indexes(conn):
    """Return required admin index names that are absent from the current schema."""
    missing = []
    for index_name, table_name, _ in _NEW_INDEXES:
        exists = conn.execute(
            text(
                """
                SELECT EXISTS (
                    SELECT 1
                      FROM pg_indexes
                     WHERE schemaname = current_schema()
                       AND tablename = :table_name
                       AND indexname = :index_name
                )
                """
            ),
            {"table_name": table_name, "index_name": index_name},
        ).scalar_one()
        if not exists:
            missing.append(index_name)
    return missing


def main():
    engine = get_engine()
    with engine.begin() as conn:
        # admin 3개 테이블 생성(이미 있으면 건너뜀). documents 는 이 metadata 에 없어 안 건드림.
        admin_metadata.create_all(conn, checkfirst=True)
        # documents 확장 — 기존 테이블이라 create_all 이 컬럼을 안 더하므로 멱등 ALTER.
        for name, coltype in _DOCUMENTS_NEW_COLUMNS:
            conn.execute(text(f"ALTER TABLE documents ADD COLUMN IF NOT EXISTS {name} {coltype}"))
        # prompt_versions.reason — 테이블 생성(2026-08-12 오전) 이후 추가된 컬럼이라 같은 방식.
        conn.execute(text("ALTER TABLE prompt_versions ADD COLUMN IF NOT EXISTS reason text"))
        conn.execute(text("ALTER TABLE testset_items ADD COLUMN IF NOT EXISTS question_type varchar"))
        conn.execute(text("ALTER TABLE testset_items ADD COLUMN IF NOT EXISTS intent varchar"))
        for name, table_name, cols in _NEW_INDEXES:
            conn.execute(text(f"CREATE INDEX IF NOT EXISTS {name} ON {table_name} ({cols})"))
        missing_indexes = _missing_indexes(conn)
        if missing_indexes:
            raise RuntimeError(
                "관리자 스키마 인덱스 적용 실패: " + ", ".join(missing_indexes)
            )
    print("admin 테이블 생성/확인:", ", ".join(t.name for t in admin_metadata.sorted_tables))
    print("documents 확장 컬럼:", ", ".join(n for n, _ in _DOCUMENTS_NEW_COLUMNS))
    print("인덱스 생성 및 DB 확인 완료:", ", ".join(n for n, _, _ in _NEW_INDEXES))


if __name__ == "__main__":
    main()
