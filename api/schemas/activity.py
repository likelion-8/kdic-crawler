"""관리자 활동 로그(AD-011) 응답 스키마.

화면 계약 정본은 web/src/routes/admin/settings/activity/EventDetail.tsx 의 ActivityEventRow ·
ActivityEventDetailData 와 ActivityLog.tsx 의 Overview 다. 필드 이름을 바꾸면 화면이 조용히
빈 칸으로 뜨므로 그 세 타입과 1:1로 맞춰 둔다.

`admin_activity_logs` 는 추가 전용 원장이라 수정·삭제 스키마는 두지 않는다.
"""
from typing import Optional

from pydantic import BaseModel


class ActivityEventRow(BaseModel):
    """목록 한 행. EventDetail.tsx 의 ActivityEventRow 와 같은 모양이다."""

    id: str
    # 🔴 KST(+09:00) ISO 로 내보낸다. 화면의 formatKst 는 받은 문자열을 그대로 지역 시각으로
    # 읽으므로, UTC 로 주면 9시간 어긋난 시각이 '오늘'로 표시된다.
    occurred_at: str
    actor: str
    actor_role: str
    action: str
    target: str
    result: str
    # 거부 건에서는 화면이 같은 값을 '거부 사유'로 읽는다(AD-011 Description 4).
    reason: Optional[str] = None
    request_id: str
    ip: str


class ActivitySnapshot(BaseModel):
    """바뀐 항목만 담은 전후값. 상세 패널의 '변경 내용' 블록이 이게 있을 때만 렌더된다."""

    before: dict
    after: dict


class ActivityEventDetail(ActivityEventRow):
    """상세 = 행 + 기록 시점 스냅샷.

    approval(요청자·승인자·재인증 시각)은 화면 타입에 있지만 admin_activity_logs 에 담을 컬럼이
    없어서 내보내지 않는다. 옵셔널 필드이고 승인 절차를 거친 이벤트에만 붙는데, 지금 기록되는
    행동(로그인 계열·잡 생성)에는 승인 절차가 없다. 승인 흐름을 만들 때 컬럼과 함께 추가할 것.
    """

    snapshot: Optional[ActivitySnapshot] = None


class ActivityEventList(BaseModel):
    items: list[ActivityEventRow]
    total: int
    page: int
    size: int


class ActivityOverview(BaseModel):
    """화면 상단 '활동 로그 현황' 3값 + 필터 선택지 2개.

    행위·실행자 선택지를 상수로 박지 않고 기록된 값에서 뽑는 이유는, 어휘가 늘 때마다
    프론트를 고치지 않아도 되게 하기 위해서다(목 핸들러도 같은 방식이다).
    """

    today_count: int
    last_recorded_at: Optional[str] = None
    purge_due_this_week: int
    actions: list[str]
    actors: list[str]


class ActivityExportRequest(BaseModel):
    """내보내기 요청. 현재 필터 조건을 그대로 실어 온다(ActivityLog.tsx exporting)."""

    request_id: Optional[str] = None
    reason: Optional[str] = None
    filter: dict = {}


class ActivityExportResponse(BaseModel):
    export_id: str
    status: str
    estimated_rows: int
