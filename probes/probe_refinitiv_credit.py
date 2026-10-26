"""Phase 0 보완 — 미국 HY·IG 크레딧 스프레드를 Refinitiv 에서 2010~ 받을 수 있는지.

lseg-data 별도 venv 로 실행(검색 API 가 eikon 에는 없음):
    cat ~/.claude/reference/refinitiv-workspace/.appkey | \
      /mnt/c/Users/infomax/AppData/Local/lsegvenv/Scripts/python.exe probes/probe_refinitiv_credit.py

1) ICE BofA 지수 RIC(.MERH0A0 HY, .MERC0A0 IG) 직접 이력
2) discovery.search 로 HY/IG 스프레드·CDX 지수 후보 검색 → 상위 후보 이력 행수
결과: outputs/phase0/probe_refinitiv_credit.json. 값은 저장하지 않는다.
"""
import json
import os
import sys

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")
key = sys.stdin.readline().strip()

import lseg.data as ld  # noqa: E402
from lseg.data.discovery import Views  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "outputs", "phase0", "probe_refinitiv_credit.json")
s = ld.session.desktop.Definition(app_key=key).get_session()
ld.session.set_default(s)
s.open()
res = {}


def hist(name, ric, fields=None):
    try:
        d = ld.get_history(ric, fields=fields, start="2010-01-01", end="2026-10-23")
        d = d.dropna(how="all")
        res[name] = {"ric": ric, "rows": int(len(d)), "first": str(d.index.min().date()) if len(d) else None,
                     "last": str(d.index.max().date()) if len(d) else None, "columns": [str(c) for c in d.columns][:12]}
    except Exception as e:
        res[name] = {"ric": ric, "rows": 0, "error": str(e)[:200]}
    print(name, json.dumps(res[name], ensure_ascii=False), flush=True)


for r in [".MERH0A0", ".MERC0A0"]:
    hist(f"ICE_{r}", r)

queries = {
    "ICE HY": "ICE BofA US High Yield Index option adjusted spread",
    "ICE IG": "ICE BofA US Corporate Index option adjusted spread",
    "CDX HY": "CDX North America High Yield 5Y",
    "CDX IG": "CDX North America Investment Grade 5Y",
    "iBoxx HY": "iBoxx USD Liquid High Yield",
}
found = {}
for qn, q in queries.items():
    for view in [Views.SEARCH_ALL, Views.INDEX_INSTRUMENTS]:
        try:
            df = ld.discovery.search(view=view, query=q, top=8, select="RIC,DocumentTitle")
            rows = df.fillna("").to_dict("records") if df is not None else []
        except Exception as e:
            rows = [{"error": str(e)[:160]}]
        found[f"{qn}|{view.name}"] = rows
        print("SEARCH", qn, view.name, json.dumps(rows, ensure_ascii=False)[:900], flush=True)
res["search"] = found

# 검색 결과 중 RIC 있는 후보를 최대 12개 이력 확인
cands = []
for rows in found.values():
    for r in rows:
        ric = str(r.get("RIC", "")).strip()
        if ric and ric not in cands:
            cands.append(ric)
for ric in cands[:12]:
    hist(f"cand_{ric}", ric)

json.dump(res, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("wrote", OUT)
s.close()
