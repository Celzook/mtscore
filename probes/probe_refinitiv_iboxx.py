"""Phase 0 보완 — iBoxx USD Liquid HY·IG 지수의 스프레드·듀레이션 열이 2010~ 실제로 채워져 있는지.

    cat ~/.claude/reference/refinitiv-workspace/.appkey | \
      /mnt/c/Users/infomax/AppData/Local/lsegvenv/Scripts/python.exe probes/probe_refinitiv_iboxx.py
결과: outputs/phase0/probe_refinitiv_iboxx.json. 값은 저장하지 않는다(열별 비결측 행수·시작·끝만).
"""
import json, os, sys
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")
key = sys.stdin.readline().strip()
import lseg.data as ld  # noqa: E402
from lseg.data.discovery import Views  # noqa: E402
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "outputs", "phase0", "probe_refinitiv_iboxx.json")
s = ld.session.desktop.Definition(app_key=key).get_session(); ld.session.set_default(s); s.open()
res = {}
for q in ["iBoxx USD Liquid Investment Grade Index", "iBoxx USD Liquid Investment Grade"]:
    df = ld.discovery.search(view=Views.SEARCH_ALL, query=q, top=10, select="RIC,DocumentTitle")
    rows = df.fillna("").to_dict("records") if df is not None else []
    res[f"search:{q}"] = rows
    print("SEARCH", q, json.dumps(rows, ensure_ascii=False)[:1200], flush=True)
cands = [".IBLUS0004"] + [r["RIC"] for rows in [v for k, v in res.items() if k.startswith("search")] for r in rows
                          if "Liquid Investment Grade Index" in r.get("DocumentTitle", "") and r.get("RIC")]
seen = []
for ric in cands:
    if ric in seen:
        continue
    seen.append(ric)
    try:
        d = ld.get_history(ric, start="2010-01-01", end="2026-10-23")
        cols = {}
        for c in ["TRDPRC_1", "ZSPREAD", "OAS", "AST_SWPSPD", "MOD_DURTN", "YLDTOMAT"]:
            if c in d.columns:
                x = d[c].dropna()
                cols[c] = {"rows": int(len(x)), "first": str(x.index.min().date()) if len(x) else None,
                           "last": str(x.index.max().date()) if len(x) else None}
        res[ric] = {"rows": int(len(d)), "cols": cols}
    except Exception as e:
        res[ric] = {"error": str(e)[:200]}
    print(ric, json.dumps(res[ric], ensure_ascii=False), flush=True)
json.dump(res, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("wrote", OUT); s.close()
