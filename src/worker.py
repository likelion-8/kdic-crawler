"""파이프라인 워커 — pipeline_jobs 의 QUEUED 잡을 집어 실제로 실행한다.

지금까지 관리자 화면(AD-004)이 만든 잡은 QUEUED 에서 영원히 움직이지 않았다(실행 주체가
없었다). 이 프로세스가 그 실행 주체다.

실행:
    .venv/Scripts/python.exe src/worker.py          # 상주(3초 폴링)
    .venv/Scripts/python.exe src/worker.py --once   # 대기 중인 잡 하나만 처리하고 종료

## 왜 Redis·ARQ 가 아니라 DB 폴링인가

큐 인프라를 새로 들이면 배포가 한 조각 늘고, 이 서비스의 잡 빈도는 사람이 가끔 누르는
수준이라 3초 폴링이면 충분하다. 잡 상태의 정본이 이미 pipeline_jobs 테이블이므로
(프론트가 3초 폴링으로 같은 행을 읽는다 — P1) 큐를 따로 두면 상태가 두 곳이 된다.
클레임은 `UPDATE ... WHERE status='QUEUED' ... FOR UPDATE SKIP LOCKED` 라 워커를 여러 개
띄워도 같은 잡을 두 번 집지 않는다.

## 잡 타입별 실행 범위 — 정직하게 갈랐다

| 타입 | 실행 | 내용 |
|---|---|---|
| FULL_RECRAWL · SELECTED_RECRAWL | ✅ 실제 실행 | 수집(inventory.PAGES 기준 실제 재크롤, expect 판본 검증 + 재시도) -> 변환(파싱 + 코퍼스 재조립, **content_sha256 비교로 바뀐 페이지만 갱신 집계**) -> 이하 재적재와 동일 |
| REINDEX · RECHUNK · REEMBED | ✅ 실제 실행 | 코퍼스(data/corpus.jsonl) -> 청킹 -> 검증 -> **게이트(홀드아웃 평가, 경고만)** -> 색인(UPSERT) -> 버전 기록. 게이트 미달이어도 색인은 진행하고 판정은 경고로만 남긴다(2026-08-19 정책, src/index_gate.py) |
| 롤백 잡(rollback_of 있음)   | ✅ 실제 실행 | search_index_versions 의 직전 스냅샷으로 corpus.jsonl 을 되돌린 뒤 위와 동일 재적재. **게이트는 SKIPPED** — 직전에 통과했던 스냅샷이라 다시 재는 의미가 없고, 장애 복구를 게이트가 막으면 안 된다 |
| SMOKE_EVAL                  | ✅ 실제 실행 | admin_evaluations.run_evaluation 위임(문항 수만큼 OpenAI·HCX — 수 분). **평가셋 반영(AD-006 [반영])이 evaluation_runs 행을 먼저 만들고 targets[0]=run_id 로 실어 인큐하는 경로 하나뿐이다** — 이 잡을 손으로 만들 수는 없다(POST /jobs 가 받지 않는다) |
| CHANGE_DETECT               | ✅ 실제 실행 | change_detect.run — 정적 페이지 재수집 후 본문 해시 대조, 바뀐 것만 index_status=PENDING 표시(저장·색인 안 함). AD-004 [지금 확인]·주기 배치가 만든다(2026-08-18, 미구현 ② 해소) |

## 재수집(수집 단계)이 하는 일 — 기존 크롤 파이프라인을 그대로 자동화

담당자별 크롤러가 나눠 하던 일을 한 흐름으로 잇는다. 새 로직은 없다:

  1. 정적 페이지: crawler_dy.fetch(HEADERS 포함) 로 원본 HTML 재수집.
     inventory 의 `expect` 문자열로 판본을 검증한다 — 서버가 옛 판본을 번갈아 주는 것이
     실측됐고(dp_protlmts 12회 중 3회), 불일치면 재시도한다. 요청 간 0.5초 간격.
  2. 동적 표(dyn_table)·페이지네이션·게시판 상세: fetch_dyntable.py · fetch_extra.py 를
     서브프로세스로 실행(각각 검증된 독립 스크립트 — import 로 엮으면 argv·전역 상태가 꼬인다).
  3. 변환: parse_raw_html.run() -> build_corpus.build(). **해시 비교는 build_corpus 가 한다**
     (hashing.content_sha256 — 본문이 같으면 collected_at 을 승계해 '변경 없음'이 기록에
     남는다). 워커는 재조립 전후의 page_id->해시를 대조해 바뀐 페이지 수를 변환 단계
     count 로 채운다.

⚠️ data/raw_html·data/text·data/corpus.jsonl 은 git 추적 파일이다. 재수집이 이 파일들을
갱신하므로 실행 후 git diff 로 무엇이 바뀌었는지 사람이 검토할 수 있다(의도된 동작 —
코퍼스 변경은 리뷰 가능한 커밋으로 남기는 것이 팀 방식이다).

## 7단계(수집·변환·청킹·검증·게이트·색인·반영)와 그동안 못 채우던 값

단계 이름 정본은 constants.ts PIPELINE_STEPS. 재적재 계열은 수집이 없으므로 SKIPPED 로
표시한다(JobStep.status 어휘에 SKIPPED 가 있다 — api/schemas/pipeline.py). 각 단계가 끝날
때마다 steps JSONB 를 통째로 갱신하므로 프론트 3초 폴링이 진행바를 실시간으로 그린다.

- JobStep.count      단계별 처리 건수(변환=페이지 수, 청킹=청크 수, 색인=업서트 청크 수)
- JobStep.elapsed_ms 단계별 소요
- index_impact       실패 시점 기준으로 워커가 판정해 채운다:
                       색인 도달 전 실패  -> "색인 변경 없음(반영 전 실패)"
                       색인 중 실패      -> "부분 반영 가능성 — 재실행 필요"
                     (성공 잡은 NULL — '영향'은 실패의 속성이다)

## 취소(cancel)와의 계약

cancel 엔드포인트는 QUEUED/RUNNING 잡을 CANCELLED 로 바꾼다. 단계 사이마다 상태를 다시
읽어, 취소됐으면 나머지 단계를 SKIPPED 로 두고 즉시 멈춘다. 단계 하나가 도는 중간에는
멈추지 못한다(색인 UPSERT 는 한 트랜잭션이라 중간 취소가 더 위험하다).

## ⚠️ BM25 재시작 필요

색인은 pgvector(document_chunks)에 즉시 반영되지만, BM25 는 API 프로세스가 기동 시
data/*.jsonl 로 조립한 싱글턴이다(retrieval._build_engines). 재적재 후 BM25 까지 새
코퍼스를 보려면 API 프로세스를 재시작해야 한다 — 완료 로그에 이를 경고로 남긴다.
"""
import argparse
import gzip
import json
import logging
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for p in (str(ROOT), str(ROOT / "src")):
    if p not in sys.path:
        sys.path.insert(0, p)

from sqlalchemy import select, text, update  # noqa: E402

import housekeeping  # noqa: E402
from db import get_engine, get_session  # noqa: E402
from schema import pipeline_jobs, search_index_versions  # noqa: E402

logger = logging.getLogger("worker")

POLL_INTERVAL_S = 3
STEPS = ("수집", "변환", "청킹", "검증", "게이트", "색인", "반영")
CORPUS = ROOT / "data" / "corpus.jsonl"

# 재적재 계열(수집 없음). 셋을 같은 경로로 돌리는 이유: 청킹·임베딩·색인이 한 스크립트
# (index_document_chunks)의 단계들이고, 지금은 청킹 파라미터·임베딩 모델이 코드 고정이라
# 세 타입의 실행 내용이 같다. 파라미터가 관리자 노브가 되면(P3) 여기서 갈라진다.
REINDEX_FAMILY = frozenset({"REINDEX", "RECHUNK", "REEMBED"})
CRAWL_TYPES = frozenset({"FULL_RECRAWL", "SELECTED_RECRAWL"})


# ──────────────────────────────── 잡 상태 갱신 ────────────────────────────────

class JobCancelled(Exception):
    """cancel 엔드포인트가 잡을 CANCELLED 로 바꿨다 — 남은 단계를 접고 즉시 멈춘다."""


class _GateSkipped(Exception):
    """게이트를 재는 것이 의미 없는 잡(롤백) — 실패가 아니라 SKIPPED 로 기록한다."""


class StageFailed(Exception):
    def __init__(self, stage: str, detail: str):
        self.stage = stage
        self.detail = detail
        super().__init__(f"{stage}: {detail}")


def _load_steps(session, job_id) -> list:
    row = session.execute(
        select(pipeline_jobs.c.steps, pipeline_jobs.c.status)
        .where(pipeline_jobs.c.id == job_id)
    ).first()
    if row.status == "CANCELLED":
        raise JobCancelled()
    return list(row.steps or [])


def _write_steps(session, job_id, steps: list) -> None:
    session.execute(update(pipeline_jobs).where(pipeline_jobs.c.id == job_id)
                    .values(steps=steps))
    session.commit()


def _set_step(session, job_id, name: str, status: str, *,
              elapsed_ms: int = None, count: int = None, detail: dict = None) -> None:
    """단계 하나의 상태를 바꿔 통째로 저장한다 — 프론트 3초 폴링이 이 값으로 진행바를 그린다.

    detail 은 단계가 화면에 남길 구조화 정보다(2026-08-18). 게이트가 판정 요약(통과 여부·
    지표·미달 항목·run_id)을 여기 실어, 관리자가 판정을 보러 화면을 옮기지 않아도 된다."""
    steps = _load_steps(session, job_id)
    for s in steps:
        if s.get("name") == name:
            s["status"] = status
            if elapsed_ms is not None:
                s["elapsed_ms"] = elapsed_ms
            if count is not None:
                s["count"] = count
            if detail is not None:
                s["detail"] = detail
    _write_steps(session, job_id, steps)


def _set_progress(session, job_id, name: str, done: int, total: int) -> None:
    """진행 중인 단계의 처리 건수 — 화면이 이 값으로 %를 그린다(3초 폴링).

    단계 상태는 건드리지 않는다. 단계가 7개뿐이라 상태만으로는 변경 감지(1단계)·수집처럼
    '한 단계 안에서 오래 도는' 작업의 진행이 0%에서 100%로 튄다.
    ponytail: 항목마다 UPDATE 1회. 항목당 1초 넘게 걸리는 루프에만 붙이므로 부담이 없다."""
    steps = _load_steps(session, job_id)   # 취소됐으면 여기서 JobCancelled 가 올라간다
    for s in steps:
        if s.get("name") == name:
            s["progress"] = {"done": done, "total": total}
    _write_steps(session, job_id, steps)


def _finish(session, job_id, status: str, *, error: dict = None,
            index_impact: str = None, skip_remaining: bool = False) -> None:
    if skip_remaining:
        try:
            steps = _load_steps(session, job_id)
        except JobCancelled:
            steps = list(session.execute(
                select(pipeline_jobs.c.steps).where(pipeline_jobs.c.id == job_id)
            ).scalar_one() or [])
        for s in steps:
            if s.get("status") in ("QUEUED", "RUNNING"):
                s["status"] = "SKIPPED"
        _write_steps(session, job_id, steps)
    values = {"status": status}
    if error is not None:
        values["error"] = error
    if index_impact is not None:
        values["index_impact"] = index_impact
    session.execute(update(pipeline_jobs).where(pipeline_jobs.c.id == job_id).values(**values))
    session.commit()


def _run_stage(session, job_id, name: str, fn):
    """단계 하나 실행: RUNNING 표시 -> fn() -> SUCCESS(+건수·소요). 실패는 StageFailed 로
    감싸 올린다 — 상위에서 잡 전체를 FAILED 로 마감하고 index_impact 를 판정한다."""
    _set_step(session, job_id, name, "RUNNING")
    started = time.monotonic()
    try:
        count = fn()
    except JobCancelled:
        raise
    except StageFailed:
        # 단계 함수가 직접 던진 실패(검증의 chunk_id 중복 등) — 단계를 FAILED 로 박고 올린다.
        _set_step(session, job_id, name, "FAILED",
                  elapsed_ms=int((time.monotonic() - started) * 1000))
        raise
    except Exception as exc:  # noqa: BLE001 — 어떤 단계 실패든 잡 실패로 수렴시킨다
        _set_step(session, job_id, name, "FAILED",
                  elapsed_ms=int((time.monotonic() - started) * 1000))
        raise StageFailed(name, f"{type(exc).__name__}: {exc}") from exc
    _set_step(session, job_id, name, "SUCCESS",
              elapsed_ms=int((time.monotonic() - started) * 1000),
              count=count if isinstance(count, int) else None)
    return count


# ──────────────────────────────── 수집(재크롤) ────────────────────────────────

def _corpus_hashes() -> dict:
    """corpus.jsonl 의 page_id -> content_sha256. 변환 단계의 '바뀐 페이지 수' 집계용."""
    hashes = {}
    if CORPUS.exists():
        with CORPUS.open(encoding="utf-8") as f:
            for line in f:
                r = json.loads(line)
                hashes[r["page_id"]] = r.get("content_sha256")
    return hashes


def _fetch_stage(job, on_progress=None) -> int:
    """수집: inventory.PAGES 를 실제로 재크롤한다(모듈 주석의 1·2번). 반환 = 수집한 페이지 수.

    SELECTED_RECRAWL 은 job.targets(page_id 배열)만, FULL_RECRAWL 은 전체를 돈다.
    expect 불일치·요청 실패는 페이지당 4회 재시도하고, 그래도 실패한 페이지가 있으면
    단계 실패다 — 일부만 수집된 코퍼스로 조용히 색인하면 '최신처럼 보이는 옛 문서'가 남는다.
    """
    import subprocess
    import requests as _requests  # noqa: F401 — crawler_dy.fetch 가 쓰는 의존성 확인용

    sys.path.insert(0, str(ROOT / "src" / "crawler"))
    from crawler_dy import fetch
    from inventory import PAGES

    targets = {t for t in (job.targets or []) if t}
    pages = [p for p in PAGES if not targets or p["id"] in targets]
    if targets:
        unknown = targets - {p["id"] for p in pages}
        if unknown:
            raise StageFailed("수집", f"inventory 에 없는 page_id: {', '.join(sorted(unknown))}")
    if not pages:
        raise StageFailed("수집", "수집 대상이 없습니다.")

    raw_dir = ROOT / "data" / "raw_html"
    raw_dir.mkdir(parents=True, exist_ok=True)
    failures = []
    static_pages = [p for p in pages if not p.get("dyn_table")]
    for done, p in enumerate(static_pages, 1):
        last = ""
        for _attempt in range(4):
            try:
                html = fetch(p["url"])
            except Exception as exc:  # noqa: BLE001 — 페이지 단위 재시도로 수렴
                last = f"{type(exc).__name__}: {exc}"
                time.sleep(1.0)
                continue
            if p.get("expect") and p["expect"] not in html:
                # 서버가 옛 판본을 준 것(실측: 판본 2종 혼재) — 사람이 inventory 에 못박은
                # 문자열이 든 판본만 채택한다.
                last = "expect 판본 불일치(옛 판본 수신)"
                time.sleep(1.0)
                continue
            (raw_dir / f"{p['id']}.html").write_text(html, encoding="utf-8")
            break
        else:
            failures.append(f"{p['id']}({last})")
        if on_progress:
            # ponytail: 정적 페이지만 센다. 뒤따르는 동적 표·페이지네이션 스크립트는
            # 서브프로세스라 안에서 몇 건을 처리했는지 알 수 없다 — 그 구간은 100%에서 멈춘다.
            on_progress(done, len(static_pages))
        time.sleep(0.5)   # 예의 있는 수집 간격 — 원 크롤러들과 같은 태도

    # 동적 표·페이지네이션·게시판 상세는 검증된 독립 스크립트를 그대로 서브프로세스로.
    dyn_ids = [p["id"] for p in pages if p.get("dyn_table")]
    if dyn_ids:
        r = subprocess.run([sys.executable, str(ROOT / "src" / "crawler" / "fetch_dyntable.py"),
                            *dyn_ids], capture_output=True, text=True, timeout=1800)
        if r.returncode != 0:
            failures.append(f"동적 표({', '.join(dyn_ids)}): {(r.stderr or r.stdout)[-300:]}")
    extra = subprocess.run([sys.executable, str(ROOT / "src" / "crawler" / "fetch_extra.py"),
                            *sorted(targets)] if targets else
                           [sys.executable, str(ROOT / "src" / "crawler" / "fetch_extra.py")],
                           capture_output=True, text=True, timeout=1800)
    if extra.returncode != 0:
        failures.append(f"페이지네이션/상세: {(extra.stderr or extra.stdout)[-300:]}")

    if failures:
        raise StageFailed("수집", f"{len(failures)}건 수집 실패 — " + " · ".join(failures[:5]))
    return len(pages)


def _rebuild_corpus_stage() -> int:
    """변환: 파싱 + 코퍼스 재조립. 반환 = **본문이 실제로 바뀐 페이지 수**(해시 대조).

    해시 비교의 본체는 build_corpus 다(content_sha256 이 같으면 collected_at 승계 —
    '변경 없음'이 기록에 남는다). 워커는 재조립 전후를 대조해 화면에 보일 숫자만 만든다.
    """
    sys.path.insert(0, str(ROOT / "src" / "crawler"))
    import parse_raw_html
    import build_corpus

    before = _corpus_hashes()
    parse_raw_html.run()
    build_corpus.build()
    after = _corpus_hashes()
    changed = sum(1 for pid, h in after.items() if before.get(pid) != h)
    logger.info("변환 완료: 페이지 %d건 중 본문 변경 %d건", len(after), changed)
    return changed


# ──────────────────────────────── 재적재 계열 ────────────────────────────────

def _restore_snapshot_for_rollback(session, rollback_of: str) -> int:
    """롤백 잡의 수집 단계: 원본 잡이 만든 버전의 **직전** 스냅샷으로 corpus.jsonl 을 되돌린다.

    스냅샷은 search_index_versions.source_snapshot(gzip, 보관 2개)이다. 덮어쓰기 전에
    corpus.jsonl.bak 으로 지금 것을 비켜 둔다 — 롤백의 롤백이 필요해질 수 있다.
    """
    made = session.execute(
        select(search_index_versions.c.created_at)
        .where(search_index_versions.c.created_by_job_id == str(rollback_of))
        .order_by(search_index_versions.c.created_at.desc())
    ).first()
    query = select(search_index_versions).where(search_index_versions.c.source_snapshot.isnot(None))
    if made:
        query = query.where(search_index_versions.c.created_at < made.created_at)
    previous = session.execute(
        query.order_by(search_index_versions.c.created_at.desc())
    ).first()
    if previous is None or not previous.source_snapshot:
        raise StageFailed("수집", "되돌릴 스냅샷이 없습니다(search_index_versions 에 "
                                "source_snapshot 보관본 없음). 스냅샷은 활성+직전 2개만 보관된다.")
    backup = CORPUS.with_suffix(".jsonl.bak")
    backup.write_bytes(CORPUS.read_bytes())
    restored = gzip.decompress(previous.source_snapshot)
    CORPUS.write_bytes(restored)
    logger.info("스냅샷 복원: corpus.jsonl <- 버전 %s (%d bytes, 이전 본은 %s)",
                previous.id, len(restored), backup.name)
    return restored.count(b"\n")


def _run_reindex(session, job, *, recrawl: bool = False) -> None:
    """변환 -> 청킹 -> 검증 -> 색인 -> 반영. index_document_chunks.py 의 정식 경로를 그대로
    쓴다(UPSERT — 관리자 소유 컬럼 보존). 각 단계는 실제 그 일을 한다:

      변환   corpus.jsonl 적재(페이지 수)
      청킹   build_units("all") (청크 수)
      검증   업무분류 검증 + chunk_id 중복 검사(발견한 문제 수 — 0 이어야 통과)
      색인   index_document_chunks.main() — 문서·청크 UPSERT + 옛 경계 청크 삭제 +
             is_active 재동기화. 임베딩은 dense_cache 적중분은 재사용, 새 청크만 인코딩
      반영   search_index_versions 에 ACTIVE 버전이 기록됐는지 확인(main() 안에서 기록됨)
    """
    sys.path.insert(0, str(ROOT / "src" / "crawler"))
    from chunking import build_units, load_records
    import index_document_chunks as idx

    state = {}

    def _transform():
        # 재수집이면 파싱+코퍼스 재조립까지 하고 count 는 '본문이 바뀐 페이지 수'다 —
        # 재적재는 기존 코퍼스 그대로라 count 가 '페이지 수'다. 의미가 다름을 화면이
        # 단계명(변환)만으로는 못 가르니, 숫자의 정의는 여기와 모듈 주석이 정본이다.
        if recrawl:
            changed = _rebuild_corpus_stage()
            state["records"] = load_records()
            return changed
        state["records"] = load_records()
        return len(state["records"])

    # 적재 파라미터(2026-08-18) — 잡에 실린 chunk_mode 를 쓴다. 없으면 운영 기본 "all".
    # 종전에는 여기가 "all" 고정이라 재색인·재청킹·재임베딩 세 버튼이 같은 동작이었다.
    chunk_mode = ((getattr(job, "params", None) or {}).get("chunk_mode")) or "all"

    def _chunk():
        uids, texts, u2p = build_units(chunk_mode)
        state["uids"], state["texts"] = uids, texts   # texts 는 게이트가 메모리 인덱스를 만들 때 쓴다
        logger.info("청킹: mode=%s → %d청크", chunk_mode, len(uids))
        return len(uids)

    def _validate():
        # load_chunk_meta 는 chunking 이 아니라 index_qdrant 에 있다(index_document_chunks 의
        # import 와 동일 — Qdrant 시절 파일이지만 청크 메타 로더는 여기 남아 있다).
        from index_qdrant import load_chunk_meta
        meta = load_chunk_meta()
        idx.validate_business_functions(meta)
        dupes = len(state["uids"]) - len(set(state["uids"]))
        if dupes:
            raise StageFailed("검증", f"chunk_id 중복 {dupes}건")
        empty = sum(1 for r in state["records"] if not (r.get("text") or "").strip())
        if empty:
            raise StageFailed("검증", f"본문이 빈 페이지 {empty}건")
        return 0   # 발견한 문제 수 — 0 이 정상이다

    def _gate():
        """새 청크를 메모리 인덱스로 올려 홀드아웃으로 채점한다. 판정은 **차단이 아니라
        경고다**(2026-08-19 정책 변경) — 미달이어도 색인은 진행하고, 관리자는 단계 detail 의
        판정·수치로 회귀 여부를 인지한다.

        임시 색인을 만들지 않는 이유와 홀드아웃을 쓰는 이유는 src/index_gate.py 참고.
        롤백 잡은 게이트를 건너뛴다 — 직전에 통과했던 스냅샷으로 되돌리는 것이라 다시 재는
        것이 의미가 없고, 장애 복구를 게이트가 막으면 안 된다."""
        import index_gate
        import pipeline

        if job.rollback_of:
            raise _GateSkipped("롤백은 직전 통과 스냅샷으로 되돌리는 것이라 게이트를 건너뛴다")

        # 2026-08-19 전환: 문항 정본은 평가메뉴 현행 버전(testset_items)이다 — 화면의
        # 추가·수정·제외가 게이트에 그대로 반영된다(씨딩 원천은 test_set 홀드아웃 89).
        from api.routers.admin_evaluations import holdout_rows
        rows = holdout_rows(session)
        result = index_gate.evaluate(state["uids"], state["texts"], rows,
                                     k_candidates=pipeline.K_CANDIDATES)
        state["gate"] = result
        # 판정을 단계 객체에 남긴다 — 화면(AD-004 R3)이 카드 안에서 요약·미달 항목을 그린다.
        _set_step(session, job.id, "게이트", "RUNNING", detail={
            "passed": result["passed"], "metrics": result["metrics"],
            "targets": result["targets"], "failures": result["failures"],
            "summary": index_gate.describe(result)})
        # 2026-08-19 정책 변경: 게이트는 차단하지 않는다 — 미달이어도 경고만 남기고
        # 색인을 진행한다(판정·수치는 detail 로 남아 화면이 경고를 그린다).
        if not result["passed"]:
            logger.warning("게이트 미달(경고, 색인은 진행): %s", index_gate.describe(result))
        else:
            logger.info("게이트 통과: %s", index_gate.describe(result))
        return result["metrics"]["n"]

    def _index():
        # 정식 적재 경로 그대로. 재적재의 본체라 이 단계가 제일 오래 걸린다(새 청크가 있으면
        # 임베딩 인코딩 — 첫 실행 시 bge-m3 ~2GB 다운로드까지). chunk_mode 를 넘겨 청킹 단계와
        # 같은 청크가 색인되고, 버전 기록(build_params)에도 그 값이 남는다.
        idx.main(chunk_mode=chunk_mode)
        with get_session() as s:
            return s.execute(text("select count(*) from document_chunks")).scalar_one()

    def _activate():
        active = session.execute(
            select(search_index_versions.c.id)
            .where(search_index_versions.c.status == "ACTIVE")
        ).first()
        if active is None:
            raise StageFailed("반영", "색인은 끝났는데 ACTIVE 버전 기록이 없다 — "
                                    "index_document_chunks._record_active_version 확인 필요")
        # 변경 감지 표시(PENDING) 해제 — 이 잡이 다시 읽어 색인한 페이지는 이제 '최신'이다.
        # 색인기는 관리자 소유 컬럼(index_status)을 보존하는 UPSERT 라 여기서 지운다(2026-08-18).
        # 안 지우면 재수집 뒤에도 "바뀐 페이지 7건"이 그대로 남아 관리자가 반영 여부를 의심한다.
        # 대상: 선택 재수집은 그 targets, 전체 재수집·재적재는 전부(코퍼스 전체를 다시 읽었으므로).
        from schema import documents as _docs
        clear = _docs.update().where(_docs.c.index_status == "PENDING").values(index_status=None)
        if job.targets:
            clear = clear.where(_docs.c.page_id.in_(list(job.targets)))
        cleared = session.execute(clear).rowcount
        session.commit()
        if cleared:
            logger.info("반영: 변경 감지 표시 %d건 해제", cleared)
        return 1

    if job.rollback_of:
        _run_stage(session, job.id, "수집",
                   lambda: _restore_snapshot_for_rollback(session, job.rollback_of))
    elif recrawl:
        _run_stage(session, job.id, "수집", lambda: _fetch_stage(
            job, lambda done, total: _set_progress(session, job.id, "수집", done, total)))
    else:
        _set_step(session, job.id, "수집", "SKIPPED")   # 재적재는 기존 코퍼스를 쓴다

    _run_stage(session, job.id, "변환", _transform)
    _run_stage(session, job.id, "청킹", _chunk)
    _run_stage(session, job.id, "검증", _validate)
    try:
        _run_stage(session, job.id, "게이트", _gate)
    except _GateSkipped as skip:
        _set_step(session, job.id, "게이트", "SKIPPED")
        logger.info("게이트 건너뜀: %s", skip)
    _run_stage(session, job.id, "색인", _index)
    _run_stage(session, job.id, "반영", _activate)
    logger.warning("⚠️ BM25 는 프로세스 기동 시 조립되는 싱글턴이다 — API 재시작 전까지 "
                   "BM25 축은 이전 코퍼스로 검색된다(pgvector 는 즉시 반영됨).")


# ──────────────────────────────── SMOKE_EVAL ────────────────────────────────

def _run_smoke_eval(session, job) -> None:
    """평가 실행을 admin_evaluations.run_evaluation 에 위임한다(그 함수의 docstring 이
    말하는 '워커' 가 바로 여기다). 문항 수만큼 OpenAI·HCX 를 부르는 수 분짜리 작업."""
    from api.routers.admin_evaluations import run_evaluation
    from schema_admin import evaluation_runs

    for name in ("수집", "변환", "청킹", "검증"):
        _set_step(session, job.id, name, "SKIPPED")   # 평가에는 색인 단계가 없다

    def _measure_stage():
        # apply(AD-006)가 run 을 만들어 targets[0] 에 실어 보낸다 — 그 run 을 마감한다.
        # (새 run 을 만들면 원 run 이 영구 RUNNING 으로 남는다.)
        # 🔴 자체 생성은 없앴다(2026-08-24). 종전에는 targets 가 비면 여기서 run 을 만들었는데
        #    target='RAG' · source='파이프라인 후속' 로 넣어 AD-006 이력이 거짓을 보였다 —
        #    측정 대상은 운영 설정이고 유발한 곳은 파이프라인 후속이 아니었다. 이 잡을 만드는
        #    경로는 apply 하나뿐이므로(POST /jobs 는 이 타입을 받지 않는다) 없는 상황이다.
        run_id = (job.targets or [None])[0]
        if not run_id:
            raise RuntimeError(
                "SMOKE_EVAL 잡에 평가 실행 id(targets[0])가 없습니다 — 이 잡은 "
                "평가셋 반영(AD-006)이 run 을 만들어 실어 보내는 경로로만 만들어집니다.")
        try:
            result = run_evaluation(session, str(run_id))
        except Exception:
            # 측정 실패·워커 예외 시 run 을 FAILED 로 마감한다 — 잡만 실패로 남기면
            # AD-006 이력에 영구 RUNNING 이 남는다(apply 원자성 해체의 대가, 2026-08-14 리뷰 #4).
            session.rollback()
            from datetime import datetime as _dt, timezone as _tz
            session.execute(update(evaluation_runs)
                            .where(evaluation_runs.c.id == run_id)
                            .values(status="FAILED", finished_at=_dt.now(_tz.utc)))
            session.commit()
            raise
        state["gate_passed"] = result["gate_passed"]
        state["run_id"] = str(run_id)
        return None

    def _record():
        session.execute(update(pipeline_jobs).where(pipeline_jobs.c.id == job.id)
                        .values(metrics={"evaluation_run_id": state["run_id"],
                                         "gate_passed": state["gate_passed"]}))
        session.commit()
        return 1

    state = {}
    _run_stage(session, job.id, "색인", _measure_stage)   # 화면 단계명 제약상 '색인' 칸에 측정을 싣는다
    _run_stage(session, job.id, "반영", _record)


# ──────────────────────────────── 디스패치 ────────────────────────────────

def claim_next(session):
    """QUEUED 잡 하나를 원자적으로 RUNNING 으로 바꿔 가져온다. SKIP LOCKED 라 워커 여러 개가
    같은 잡을 집지 않고, cancel 과의 경합도 status='QUEUED' 조건이 걸러 준다."""
    row = session.execute(text("""
        UPDATE pipeline_jobs SET status = 'RUNNING'
         WHERE id = (SELECT id FROM pipeline_jobs WHERE status = 'QUEUED'
                     ORDER BY created_at LIMIT 1 FOR UPDATE SKIP LOCKED)
        RETURNING id
    """)).first()
    session.commit()
    if row is None:
        return None
    return session.execute(
        select(pipeline_jobs).where(pipeline_jobs.c.id == row.id)
    ).first()


def _run_change_detect(session, job) -> None:
    """변경 감지 — 단계 그림에서는 '수집'만 쓰고 나머지는 SKIPPED. 저장·색인은 하지 않는다."""
    import change_detect

    for name in STEPS[1:]:
        # 감지가 끝난 뒤가 아니라 **시작 전에** 건너뛴 단계를 박는다 — 화면 진행률의 분모가
        # '건너뛰지 않은 단계'라, 나중에 박으면 도는 내내 1/7(14%)에서 멈춰 보인다.
        _set_step(session, job.id, name, "SKIPPED")

    def _detect():
        result = change_detect.run(
            session, on_progress=lambda done, total: _set_progress(
                session, job.id, "수집", done, total))
        _set_step(session, job.id, "수집", "RUNNING", detail={
            "changed": result["changed"], "failed": result["failed"],
            "unchanged": len(result["unchanged"]), "skipped": len(result["skipped"]),
            "summary": (f"변경 {len(result['changed'])}건 · 동일 {len(result['unchanged'])}건"
                        + (f" · 확인 실패 {len(result['failed'])}건" if result["failed"] else ""))})
        return len(result["changed"])

    _run_stage(session, job.id, "수집", _detect)
    _finish(session, job.id, "SUCCESS", index_impact="색인 변경 없음(감지만 수행)")


def run_job(session, job) -> None:
    logger.info("잡 시작: %s %s (rollback_of=%s, 대상 %s)",
                job.id, job.type, job.rollback_of, job.target_summary or "전체")
    try:
        if job.type == "SMOKE_EVAL":
            _run_smoke_eval(session, job)
        elif job.type == "CHANGE_DETECT":
            _run_change_detect(session, job)
        else:
            # 재수집 계열은 수집(실제 크롤)·변환(파싱+해시 대조)까지 하고, 이후 단계는
            # 재적재와 완전히 같다. 롤백 잡은 타입과 무관하게 스냅샷 복원 경로를 탄다.
            _run_reindex(session, job,
                         recrawl=job.type in CRAWL_TYPES and not job.rollback_of)
    except JobCancelled:
        logger.info("잡 취소됨: %s — 남은 단계를 접는다", job.id)
        _finish(session, job.id, "CANCELLED", skip_remaining=True)
        return
    except StageFailed as exc:
        reached_index = exc.stage in ("색인", "반영")
        _finish(
            session, job.id, "FAILED", skip_remaining=True,
            error={"code": "STAGE_FAILED", "stage": exc.stage, "detail": exc.detail},
            index_impact=("부분 반영 가능성 — 재실행 필요" if reached_index
                          else "색인 변경 없음(반영 전 실패)"),
        )
        logger.error("잡 실패: %s @%s — %s", job.id, exc.stage, exc.detail)
        return
    except Exception as exc:  # noqa: BLE001
        # 단계 **밖**에서 터진 것(DB 끊김, _finish 직전 예외 등). _run_stage 가 감싸는 범위가
        # 아니라 여기까지 그냥 올라오는데, 그대로 두면 잡이 RUNNING 에 영원히 남는다 —
        # 화면에는 '실행 중'으로 보이고 워커는 다음 잡으로 넘어가 버린다(2026-08-25 QA
        # 'QUEUED 고착'의 이웃 증상). 실패로 마감해 사람이 재시도할 수 있게 한다.
        stage = _running_stage(session, job.id)
        _finish(session, job.id, "FAILED", skip_remaining=True,
                error={"code": "INTERNAL", "stage": stage,
                       "detail": f"{type(exc).__name__}: {exc}"})
        logger.exception("잡 실패(단계 밖 예외): %s", job.id)
        return
    _finish(session, job.id, "SUCCESS")
    logger.info("잡 완료: %s", job.id)


def _running_stage(session, job_id) -> str:
    """지금 RUNNING 인 단계 이름 — 단계 밖 예외의 실패 지점을 화면에 남기기 위한 최선의 추정."""
    try:
        steps = list(session.execute(
            select(pipeline_jobs.c.steps).where(pipeline_jobs.c.id == job_id)
        ).scalar_one() or [])
    except Exception:  # noqa: BLE001 — 세션까지 망가진 경우
        return ""
    return next((s.get("name", "") for s in steps if s.get("status") == "RUNNING"), "")


# 기동 시 '고아 RUNNING' 으로 볼 나이. 잡은 길어야 수 분이라 1시간이면 넉넉하다.
# 시간을 두는 이유: 워커를 두 개 띄웠을 때(API 안 스레드 + 손으로 띄운 프로세스) 방금 시작한
# 남의 잡을 뺏지 않기 위해서다. created_at 기준이라 그 창 안의 잡은 건드리지 않는다.
STALE_RUNNING_H = 1


def reclaim_stale_jobs(session) -> int:
    """워커가 집은 뒤 죽어 RUNNING 에 박힌 잡을 실패로 마감한다. 마감한 건수를 돌려준다.

    실제로 있었던 일(2026-08-25 QA): CHANGE_DETECT 잡이 `수집:RUNNING` 인 채로 하루 넘게
    남아 있었다. 동시 실행 1개 규칙(admin_pipeline ACTIVE_STATUSES)이 QUEUED 와 RUNNING 을
    같이 보므로, 이 한 행이 이후의 모든 작업 생성을 409 로 막는다 — 화면에는 '실행 중'으로
    보여서 무엇이 막고 있는지도 알기 어렵다.

    run_job 의 단계 밖 예외 핸들러로는 못 잡는다. 예외가 아니라 프로세스가 사라진 것이라
    아무 코드도 실행되지 않는다. 그래서 **다음 워커가 기동할 때** 치운다.

    CANCELLED 로 두지 않고 FAILED 로 두는 이유: 사람이 취소한 게 아니고, 실패로 둬야
    화면에 [재시도] 와 실패 상세가 뜬다.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=STALE_RUNNING_H)
    rows = session.execute(
        select(pipeline_jobs.c.id, pipeline_jobs.c.steps)
        .where(pipeline_jobs.c.status == "RUNNING",
               pipeline_jobs.c.created_at < cutoff)).all()
    for row in rows:
        stage = next((s.get("name", "") for s in (row.steps or [])
                      if s.get("status") == "RUNNING"), "")
        _finish(session, row.id, "FAILED", skip_remaining=True,
                error={"code": "INTERNAL", "stage": stage,
                       "detail": "워커가 중단돼 진행이 끊겼습니다. 다시 시도해 주세요."},
                index_impact=("부분 반영 가능성 — 재실행 필요" if stage in ("색인", "반영")
                              else "색인 변경 없음(반영 전 중단)"))
        logger.warning("고아 잡 마감: %s @%s — 워커 중단 추정", row.id, stage or "?")
    return len(rows)


def poll_once() -> bool:
    """대기 중인 잡을 하나 집어 처리한다. 집을 잡이 없으면 False."""
    with get_session() as session:
        job = claim_next(session)
        if job is None:
            return False
        run_job(session, job)
        return True


def poll_forever(stop=None, interval: float = POLL_INTERVAL_S) -> None:
    """상주 루프. `stop`(threading.Event)이 서면 다음 폴링을 기다리다 빠져나온다.

    API 프로세스 안에서도 이 함수를 쓴다(api/main.py lifespan) — 워커를 따로 띄우는 걸
    잊으면 잡이 QUEUED 에서 영원히 안 움직였다(2026-08-25 QA). claim_next 가
    FOR UPDATE SKIP LOCKED 라 상주 워커를 별도로 함께 띄워도 같은 잡을 두 번 집지 않는다.

    루프는 어떤 예외로도 죽지 않는다 — 죽으면 그때부터 조용히 아무것도 안 하는 상태가 되고,
    그게 정확히 이번 QA 가 잡아낸 모양이다."""
    try:
        with get_session() as session:
            reclaim_stale_jobs(session)
    except Exception:  # noqa: BLE001 — 정리 실패가 기동을 막지는 않는다
        logger.exception("고아 잡 정리 실패 — 잡이 남아 있으면 새 작업이 409 로 막힌다")

    while stop is None or not stop.is_set():
        try:
            poll_once()
            # 보관기간 파기(AD-009 auto_purge). 하루 한 번만 실제로 돈다 — 상주 프로세스가
            # 이미 여기 하나 있어서 크론을 새로 들이지 않았다(src/housekeeping.py 주석)
            housekeeping.tick()
        except Exception:  # noqa: BLE001
            logger.exception("워커 폴링 예외 — 다음 주기에 계속한다")
        if stop is None:
            time.sleep(interval)
        elif stop.wait(interval):
            return


def main() -> None:
    parser = argparse.ArgumentParser(description="pipeline_jobs 워커")
    parser.add_argument("--once", action="store_true", help="대기 중인 잡 하나만 처리하고 종료")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s | %(message)s")
    get_engine()   # 기동 시 접속 검증 — DB 가 없으면 여기서 바로 죽는 게 조용히 도는 것보다 낫다
    logger.info("워커 기동 (폴링 %ds, %s)", POLL_INTERVAL_S, "1회 모드" if args.once else "상주")

    if args.once:
        poll_once()
    else:
        poll_forever()


if __name__ == "__main__":
    main()
