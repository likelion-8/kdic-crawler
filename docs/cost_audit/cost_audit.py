# -*- coding: utf-8 -*-
"""예솜24 RAG 질문당 LLM 비용 감사 — Langfuse 관측 × rag_runs 결합.

  python docs/cost_audit/extract_langfuse.py            # 먼저 원천 덤프 3개 생성
  python docs/cost_audit/cost_audit.py                   # 전체 기간(덤프 범위) · 모델 무관
  python docs/cost_audit/cost_audit.py --from 2026-08-25T15:00Z --dash-only   # 08-26~ · DASH-002 전용 (발표 수치)

정의(중요 — 결과가 여기서 갈린다):
  사용자 질문   rag_runs 웹 행(request_id IS NOT NULL). 메시지 1건 = 1행. request_id NULL 은 평가·CLI 행.
  하위질문     observation.subs[] 길이 합. 조기 종료 질문은 subs=0.
  트레이스 결합 rag_runs.trace_id → 없으면 web_chat trace.metadata.request_id == rag_runs.request_id
  종료 지점     observation.served_from (gate1/gate2/gate3/clarify/cache/guardrail). 없고 subs 있으면 '완료'.
  확인 불가     트레이스는 있는데 GENERATION 관측이 0개인 건 — 분모에서 제외. Gate1·가드레일은
               LLM 0 콜이 정상이라 예외로 남긴다.
  DASH 전용     트레이스에 model=='HCX-007' 관측이 하나라도 있으면 제외
  A            (확인 가능한 질문의 비용 합) ÷ (확인 가능한 질문 수) — Gate1 등 0원 종료 포함
  B            served_from 없음 · subs 있음 · FAILED 아님 (=생성·검증까지 간 질문)
  재생성       웹 트레이스 안의 call_hyperclova(08-28까지) / hcx_regenerate(08-29~)
  OUT_OF_SCOPE rag_runs.status — api/rag/answer.py:413 `out_of_scope = not any(used_flags)` (범위 밖 판정이 아님)
단가: 100만 토큰당 원. Luna 는 Langfuse USD(0.20/1.20)×1,385 라 정의상 Langfuse 와 일치한다.
"""
import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")   # 윈도우 기본 cp949 는 이 파일의 em-dash 를 못 찍는다

HERE = Path(__file__).resolve().parent
KRW = {"HCX-DASH-002": (250, 1000), "gpt-5.6-luna": (277, 1662), "HCX-007": (1250, 5000)}
FX = 1385.0
# 2026-08-28 14:10~14:51 KST 레드팀 배터리(인젝션·허위전제 세트, 질문마다 새 세션).
BATCH = ("2026-08-28 05:00", "2026-08-28 06:00")

ap = argparse.ArgumentParser()
ap.add_argument("--from", dest="fr", default=None, help="UTC ISO, 예: 2026-08-25T15:00Z (08-26 00:00 KST)")
ap.add_argument("--to", dest="to", default=None)
ap.add_argument("--dash-only", action="store_true", help="HCX-007 호출이 섞인 질문 제외")
ap.add_argument("--no-batch", action="store_true", help="08-28 14 시대 레드팀 배터리 제외")
args = ap.parse_args()

def _iso(s):
    return None if s is None else datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M")

W0, W1 = _iso(args.fr), _iso(args.to)

def load_jsonl(p):
    return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]

obs = load_jsonl(HERE / "lf_obs_full.jsonl")
traces = load_jsonl(HERE / "lf_traces_web.jsonl")
rr = json.load(open(HERE / "rag_runs.json", encoding="utf-8"))
web = [r for r in rr if r["request_id"]]
if W0: web = [r for r in web if r["created_at"] >= W0]
if W1: web = [r for r in web if r["created_at"] < W1]

def usage(o):
    u = o.get("usageDetails") or o.get("usage") or {}
    return int(u.get("input", u.get("promptTokens", 0)) or 0), int(u.get("output", u.get("completionTokens", 0)) or 0)

def cost_usd(o):
    c = o.get("calculatedTotalCost")
    if c is None: c = (o.get("costDetails") or {}).get("total")
    return float(c or 0)

def krw(model, i, o):
    p = KRW.get(model); return None if p is None else i * p[0] / 1e6 + o * p[1] / 1e6

# ---- 결합
req2trace = {(t.get("metadata") or {}).get("request_id"): t["id"] for t in traces if (t.get("metadata") or {}).get("request_id")}
run_trace = {}
for r in web:
    tid = r["trace_id"] or req2trace.get(r["request_id"])
    if tid: run_trace[r["id"]] = tid
obs_by_trace = defaultdict(list)
for o in obs: obs_by_trace[o["traceId"]].append(o)

def exit_of(r):
    o = r["observation"] or {}
    if o.get("served_from"): return o["served_from"]
    if r["status"] == "FAILED": return "FAILED"
    if o.get("subs"): return "완료"
    return "불명"
def objs_of(r):
    tid = run_trace.get(r["id"]); return obs_by_trace.get(tid, []) if tid else None
def cost_of(r):
    return sum(krw(o.get("model"), *usage(o)) or 0 for o in objs_of(r))
def subs(r): return (r["observation"] or {}).get("subs") or []

matched = [r for r in web if run_trace.get(r["id"])]
# Gate1·가드레일만 LLM 0 콜이 정상이다. 나머지 종료는 Triage(0-2.5)를 반드시 지나므로
# 관측 0 이면 계측이 빠진 것이지 0 원이 아니다(종전 조건은 완료·FAILED 만 걸러 Gate2·
# 캐시·되묻기의 관측 0 건을 0 원으로 집계했다).
gap = [r for r in matched if not objs_of(r) and exit_of(r) not in ("gate1", "guardrail")]
ok = [r for r in matched if r not in gap]
has007 = [r for r in ok if any(o.get("model") == "HCX-007" for o in objs_of(r))]
if args.dash_only: ok = [r for r in ok if r not in has007]
# --dash-only 는 007 관측이 붙은 질문만 뺀다. 007 은 생성 모델이라 캐시·되묻기·게이트로
# 끝난 질문에는 관측이 안 붙고, 그래서 배터리의 비싼 완료 72 건만 빠지고 싼 종료 41 건은
# 남는다. 그 시간대를 통째로 빼야 A 의 종료 구성이 안 뒤틀린다.
if args.no_batch: ok = [r for r in ok if not (BATCH[0] <= r["created_at"] < BATCH[1])]

print("=" * 72)
print(f"창 {W0 or '덤프 시작'} ~ {W1 or '덤프 끝'} UTC | dash_only={args.dash_only}")
print(f"웹 질문 {len(web)} | 트레이스 매칭 {len(matched)} | 관측0(확인 불가) {len(gap)} | 007 포함 {len(has007)}{' → 제외' if args.dash_only else ''} | 집계 대상 {len(ok)}")
print(f"세션 {len({r['session_id'] for r in ok})} | 하위질문 {sum(len(subs(r)) for r in ok)} | 판정된 하위 {sum(1 for r in ok for s in subs(r) if s.get('kind'))}")
print(f"환경: obs {Counter(o.get('environment') for o in obs)} | 트레이스 {Counter(t.get('environment') for t in traces)}")

print("=" * 72); print("A/B")
tot = sum(cost_of(r) for r in ok)
print(f"A. 조기 종료 포함: {tot:.1f}원 / {len(ok)} = {tot/max(len(ok),1):.2f}원")
full = [r for r in ok if exit_of(r) == "완료"]
single = [r for r in full if len(subs(r)) == 1]
regen = [r for r in full if any(o["name"] in ("call_hyperclova", "hcx_regenerate") for o in objs_of(r))]
nore = [r for r in single if r not in regen]
multi = [r for r in full if len(subs(r)) >= 2]
for lab, sel in (("B. 완료", full), ("  단일 하위", single), ("  단일·재생성 없음", nore), ("  재생성 포함", regen), ("  복합(2+)", multi)):
    print(f"{lab}: {len(sel)}건 → {sum(cost_of(r) for r in sel)/max(len(sel),1):.2f}원")

print("=" * 72); print("종료 지점 (건수 · 비율 · 평균 · 실제 호출 패턴)")
for k, v in Counter(exit_of(r) for r in ok).most_common():
    sel = [r for r in ok if exit_of(r) == k]
    pats = Counter(tuple(sorted(Counter(o["name"] for o in objs_of(r)).items())) for r in sel)
    print(f"  {k:8s} {v:4d} ({v/len(ok)*100:4.1f}%) {sum(cost_of(r) for r in sel)/v:.2f}원  {pats.most_common(2)}")

print("=" * 72); print("단계별 호출당")
agg = defaultdict(lambda: [0, 0, 0, 0.0])
for r in ok:
    for o in objs_of(r):
        i, ot = usage(o); k = (o["name"], o.get("model")); agg[k][0] += 1; agg[k][1] += i; agg[k][2] += ot; agg[k][3] += cost_usd(o)
for k, (n, i, ot, c) in sorted(agg.items()):
    kk = krw(k[1], i, ot)
    print(f"  {k[0]:20s} {str(k[1]):13s} n={n:4d} in {i/n:6.0f} out {ot/n:4.0f} 건당 {'확인 불가' if kk is None else f'{kk/n:.2f}원'} | 합 단가 {'-' if kk is None else f'{kk:.1f}원'} LF ${c:.4f}")
tk = sum(krw(k[1], v[1], v[2]) or 0 for k, v in agg.items()); tu = sum(v[3] for v in agg.values())
print(f"  총 단가계산 {tk:.1f}원 | Langfuse ${tu:.4f} = {tu*FX:.1f}원 | 차이 {(tk-tu*FX)/max(tk,1e-9)*100:.1f}%")
print("  임베딩(Gate2·검색·색인): 로컬 bge-m3 — API 비용 0, Langfuse 관측 없음")

print("=" * 72); print("재생성·사후검증")
rg = [o for r in ok for o in objs_of(r) if o["name"] in ("call_hyperclova", "hcx_regenerate")]
nv = sum(1 for r in ok for o in objs_of(r) if o["name"] == "validate_answer_llm"); ng = sum(1 for r in ok for o in objs_of(r) if o["name"] == "hcx_stream")
print(f"문제 판정 하위 {sum(1 for r in ok for s in subs(r) if s.get('kind') and (s.get('appropriate') is False or s.get('kind') in ('ungrounded_claims','refusal')))} | 교체 {sum(1 for r in ok for s in subs(r) if s.get('normalized'))}")
print(f"재생성 호출 {len(rg)} (질문 {len(regen)}) 비용 {sum(krw(o.get('model'),*usage(o)) or 0 for o in rg):.1f}원 | 재검증 {nv-ng} | 총비용에 포함됨")

print("=" * 72); print("OUT_OF_SCOPE")
oos = [r for r in ok if r["status"] == "OUT_OF_SCOPE"]; go = [r for r in oos if exit_of(r) == "완료"]
print(f"건수 {len(oos)} | 종료지점 {Counter(exit_of(r) for r in oos).most_common()}")
print(f"생성까지 간 OOS {len(go)} 건당 {sum(cost_of(r) for r in go)/max(len(go),1):.2f}원 | kind/normalized {Counter((s.get('kind'),s.get('normalized')) for r in go for s in subs(r)).most_common()}")
