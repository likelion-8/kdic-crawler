# -*- coding: utf-8 -*-
"""Langfuse REST 추출 — 비용 감사용 원천 덤프 3개를 만든다.

  python docs/cost_audit/extract_langfuse.py [--from 2026-08-13T15:00Z] [--to 2026-08-28T15:00Z]

산출(이 파일과 같은 폴더, git 추적 안 함 — 대화 원문이 들어 있다):
  lf_obs_full.jsonl   GENERATION 관측 전부 (usageDetails · calculatedTotalCost · model · traceId · name)
  lf_traces_web.jsonl name=web_chat 트레이스 (metadata.request_id · sessionId · totalCost)
  rag_runs.json       rag_runs 행 (id · trace_id · request_id · session_id · status · observation …)

⚠️ Python SDK 의 client.api.observations.get_many() 는 usage/cost 필드를 비워서 돌려준다(2026-08-30 실측).
   그래서 REST 를 직접 부른다. 429 가 잦아 페이지 사이 1.5초 + 지수 백오프.
인증: .env 의 LANGFUSE_HOST / LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY (src/observability.py 가 load_dotenv 함)
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))
import observability  # noqa: E402,F401  — .env 로드

def _parse(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)

ap = argparse.ArgumentParser()
ap.add_argument("--from", dest="fr", default="2026-08-13T15:00Z", help="UTC ISO (기본: 08-14 00:00 KST)")
ap.add_argument("--to", dest="to", default="2026-08-28T15:00Z", help="UTC ISO (기본: 08-29 00:00 KST)")
args = ap.parse_args()
fr, to = _parse(args.fr), _parse(args.to)

host = os.environ["LANGFUSE_HOST"].rstrip("/")
auth = (os.environ["LANGFUSE_PUBLIC_KEY"], os.environ["LANGFUSE_SECRET_KEY"])

def get(path, params):
    for i in range(8):
        r = requests.get(host + path, auth=auth, params=params, timeout=60)
        if r.status_code == 429:
            time.sleep(5 * (i + 1)); continue
        r.raise_for_status()
        return r.json()
    raise RuntimeError("429 persists")

def dump(path, url_path, params):
    n = 0
    with open(HERE / path, "w", encoding="utf-8") as f:
        page = 1
        while True:
            j = get(url_path, {**params, "limit": 100, "page": page})
            for d in j["data"]:
                f.write(json.dumps(d, ensure_ascii=False) + "\n"); n += 1
            total = j["meta"].get("totalPages", 1)
            print(f"{path}: page {page}/{total}", flush=True)
            if page >= total or not j["data"]:
                break
            page += 1; time.sleep(1.5)
    print(f"{path}: {n} rows")

dump("lf_obs_full.jsonl", "/api/public/observations",
     {"type": "GENERATION", "fromStartTime": fr.isoformat(), "toStartTime": to.isoformat()})
dump("lf_traces_web.jsonl", "/api/public/traces",
     {"name": "web_chat", "fromTimestamp": fr.isoformat(), "toTimestamp": to.isoformat()})

from sqlalchemy import text  # noqa: E402
from db import get_session  # noqa: E402
with get_session() as s:
    rows = s.execute(text(
        "select id,trace_id,request_id,session_id,status,created_at,observation,question,"
        "retrieval_route,llm_model,failure_stage from rag_runs where created_at>=:f and created_at<:t"),
        {"f": fr, "t": to}).mappings().all()
json.dump([json.loads(json.dumps(dict(r), default=str)) for r in rows],
          open(HERE / "rag_runs.json", "w", encoding="utf-8"), ensure_ascii=False)
print(f"rag_runs.json: {len(rows)} rows")
