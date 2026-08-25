"""필터 결과를 CSV 파일로 **그 요청 안에서** 만들어 돌려준다.

2026-08-25 QA 전까지 내보내기 두 곳(활동 로그 AD-011 · 대화 로그 AD-005)은 대상 건수를 센
접수증(`{export_id, status:"QUEUED", estimated_rows}`)만 돌려주고, 그 QUEUED 를 실제 파일로
바꾸는 주체가 없었다. 화면은 성공 토스트를 띄우는데 받는 파일이 없었다.

## 왜 export worker 를 안 만들었나

상태 4종(QUEUED/RUNNING/SUCCESS/FAILED)·파일 저장소·다운로드 URL·URL 만료·권한 재검증을
들이는 대신 동기 응답으로 끝낸다. 대상이 관리자 로그라 최대 수만 행이고, 그 정도는 한
요청에서 만들어 그대로 내려주는 편이 단순하고 실패도 그 자리에서 보인다. 비동기가 필요해지는
지점은 "한 번에 못 만들 만큼 커질 때"인데, 그때는 아래 상한이 먼저 400 으로 알려 준다.

## 상한을 조용히 자르지 않는다

MAX_EXPORT_ROWS 를 넘으면 앞부분만 담아 내려보내지 않고 400 으로 되돌린다. 잘린 파일은
"필터 결과 = 파일 내용"이라는 이 기능의 유일한 계약을 깨는데, 받는 쪽에서는 알 방법이 없다.

## 인코딩

UTF-8 BOM 을 붙인다. 팀에 윈도우가 섞여 있고 엑셀은 BOM 없는 UTF-8 CSV 를 cp949 로 읽어
한글을 깨뜨린다(파일 I/O 규약과 같은 이유).
"""
import csv
import io
from collections.abc import Iterable, Sequence

from fastapi import Response

from api.errors import BadRequestError

# 한 번에 내보낼 수 있는 행 수. 활동 로그는 보관 90일이라 실사용에서 이 값에 닿지 않는다.
MAX_EXPORT_ROWS = 20_000

# 엑셀이 UTF-8 로 읽게 하는 표시. 없으면 윈도우에서 한글이 깨진다.
BOM = "﻿"

# 브라우저 JS 가 파일명을 읽으려면 이 헤더가 노출돼야 한다(교차 출처라서). api/main.py 의
# CORS expose_headers 에 함께 올려 둔다 — 빠지면 파일은 받아지는데 이름이 'download' 가 된다.
EXPORT_HEADERS = ("Content-Disposition", "X-Export-Id", "X-Export-Rows")


def guard_export_size(total: int) -> None:
    """상한 초과면 400. 부르는 쪽이 파일을 만들기 **전에** 부른다."""
    if total > MAX_EXPORT_ROWS:
        raise BadRequestError(
            f"내보낼 대상이 {total:,}건입니다. 한 번에 {MAX_EXPORT_ROWS:,}건까지만 "
            "내보낼 수 있으니 기간이나 필터를 좁혀 주세요.")


def csv_response(*, filename: str, header: Sequence[str],
                 rows: Iterable[Sequence], export_id: str) -> Response:
    """CSV 본문을 만들어 첨부파일 응답으로 돌려준다.

    filename 은 ASCII 로 둔다 — 한글 파일명은 RFC 5987 인코딩이 필요한데, 받는 쪽(브라우저
    다운로드)에서 얻는 게 없다. 무엇을 받았는지는 파일 안의 헤더 행이 말한다.
    """
    buf = io.StringIO()
    buf.write(BOM)
    writer = csv.writer(buf, lineterminator="\r\n")
    writer.writerow(header)
    count = 0
    for row in rows:
        writer.writerow(row)
        count += 1
    return Response(
        content=buf.getvalue().encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Export-Id": export_id,
            "X-Export-Rows": str(count),
        },
    )
