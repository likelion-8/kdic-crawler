"""프롬프트·가드레일(AD-008) — 초안·게시·롤백. **엔드포인트는 D 트랙 담당자가 채운다.**

빈 라우터로 자리만 잡아 둔 파일이다(사유는 admin_dashboard.py 상단과 같다).

## 만들 것 (11종)

    GET/PUT /api/admin/prompt/draft
    POST    /api/admin/prompt/draft/discard
    POST    /api/admin/prompt/evaluate
    GET     /api/admin/prompt/versions
    POST    /api/admin/prompt/versions/{v}/rollback
    POST    /api/admin/prompt/versions/emergency-rollback
    POST    /api/admin/prompt/publish
    GET/POST /api/admin/prompt/publish-requests
    POST    /api/admin/prompt/publish-requests/{id}/approve|reject|cancel
    POST    /api/admin/guardrails/masking/validate

prompt/* 와 guardrails/* 로 갈려서 prefix 를 /api/admin 까지만 잡았다.

## 대상 상수

    src/prompt_builder.py  SYSTEM_INSTRUCTION · FEW_SHOT_EXAMPLES · NO_EVIDENCE_NOTICE

rag_param_versions 와 같은 폴백 전제다 — DB 가 비어 있으면 코드 상수를 쓴다. 그래야
이 화면이 죽어도 챗봇은 산다.

## 쓸 테이블 (2026-08-12 신설, src/schema_admin.py)

    prompt_versions          게시본. 덮어쓰지 않는다 — 긴급 롤백이 직전 본문을 필요로 한다.
                             is_current 는 부분 유니크로 1개만 강제된다.
    prompt_drafts            작성 중인 초안. change_count·dirty·char_count·evaluation 을
                             **서버가 들고 있는다**(M2 — 프론트는 diff 를 계산하지 않는다).
    prompt_publish_requests  게시 요청. 요청 시점 초안 스냅샷(content)을 함께 박는다 —
                             draft_id 만 두면 승인자가 본 것과 실제 게시본이 달라진다.
    guardrail_rules          금칙어·마스킹 규칙 + 검증 상태(validated).

## 확정된 팀 결정

- 🔴 초안 상태를 **서버가 갖는다**(M2). PUT 응답에 change_count·dirty(prompt/fewshot/
  guardrail)·char_count 를 담고, 초안이 바뀌면 evaluation 을 null 로 무효화한다.
- 가드레일은 프롬프트 초안 객체 안에 함께 실려 온다(M3). guardrail_rules 표는 검증 상태를
  붙여 두는 곳이고 정본은 초안 쪽이다 — 두 곳이 어긋나지 않게 하는 건 애플리케이션 책임이다.
- 게시 응답은 {version, smoke:{passed,total}} — Smoke 30문항 결과를 함께 준다(M4).
  실패 시 현행 유지 + user_message.
- 긴급 롤백은 POST /reauth 를 **별도 호출로 먼저** 끝낸 뒤 본 요청이다(M5). 본 요청 바디에
  password 를 싣지 않는다. 서버도 재인증 유효성을 독립 검증한다(P5) — A 트랙 헬퍼를 쓸 것.
- 마스킹 검증 응답은 {passed, sample_count, message} — 정규식 문법 오류·과대 매칭을
  **서버가 판정**하고 문구를 준다(M6). 미통과 규칙이 섞인 PUT 은 400 으로 막는다.

⚠️ 미확정: 게시·승인에 비밀번호 재확인이 필요한지(M7). CM-DF-001 2.3 고위험 3종에 없어
   화면은 재인증 입력을 뺐다. 다르게 갈 거면 프론트에 먼저 알릴 것.

계약 정본: docs/frontend-handoff.md "M. 프롬프트·가드레일" 절(M1~M7) ·
web/src/routes/admin/settings/promptops/api.ts
"""
from fastapi import APIRouter, Depends

from api.deps import get_current_admin

router = APIRouter(
    prefix="/api/admin",
    tags=["admin-prompt"],
    dependencies=[Depends(get_current_admin)],
)
