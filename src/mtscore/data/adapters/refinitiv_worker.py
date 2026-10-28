"""Refinitiv(eikon) 수집 워커 — Windows `python.exe` 로만 실행한다(WSL 은 프록시 127.0.0.1:9000 에 닿지 못함).

    (키 한 줄 + 작업 파일 경로 한 줄을 stdin 으로)
    printf '%s\\n%s\\n' "$(cat ~/.claude/reference/refinitiv-workspace/.appkey)" jobs.json | python.exe -I refinitiv_worker.py  (-I: 같은 폴더 csv.py 가 표준 csv 를 가리지 않게)

작업 파일(JSON): {"out_dir": "<상대 또는 Windows 경로>", "jobs": [job, ...]}
  job = {"id": 파일명, "kind": "ts", "rics": [...], "fields": ["CLOSE"], "start": "YYYY-MM-DD", "end": "YYYY-MM-DD"}
      | {"id": ..., "kind": "gd", "rics": [...], "fields": [...], "params": {...}}
결과: out_dir/<id>.csv (원응답 그대로). 실패는 out_dir/<id>.err(JSON). 이미 .csv 가 있으면 건너뛴다(재개 가능).
키는 어디에도 쓰지 않는다. 이 파일은 eikon 이 없는 WSL 쪽에서 import 하지 않는다.
"""
import json
import os
import sys
import time

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")
KEY = sys.stdin.readline().strip()
JOBS = sys.stdin.readline().strip()

import pandas as pd  # noqa: E402

_orig = pd.to_numeric


def _compat(arg, errors="raise", **kw):  # pandas 3.0 이 errors="ignore" 를 지웠다 — eikon 1.1.18 호환 shim
    if errors == "ignore":
        try:
            return _orig(arg, errors="raise", **kw)
        except (ValueError, TypeError):
            return arg
    return _orig(arg, errors=errors, **kw)


pd.to_numeric = _compat
import eikon as ek  # noqa: E402  (shim 이후 import)

ek.set_app_key(KEY)


def run(job):
    kind = job["kind"]
    for k in range(3):
        try:
            if kind == "ts":
                d = ek.get_timeseries(job["rics"], fields=job.get("fields", ["CLOSE"]), start_date=job["start"],
                                      end_date=job["end"], interval=job.get("interval", "daily"))
                return d.reset_index()
            d, err = ek.get_data(job["rics"], job["fields"], job.get("params", {}))
            if d is None:
                raise RuntimeError(f"get_data None: {err}")
            return d
        except Exception as ex:  # noqa: BLE001
            msg = str(ex)
            if "No data available" in msg or "Invalid RIC" in msg or "permission" in msg.lower() or k == 2:
                raise
            time.sleep(3 * (k + 1))


def main():
    spec = json.load(open(JOBS, encoding="utf-8"))
    out = spec["out_dir"]
    os.makedirs(out, exist_ok=True)
    n_ok = n_skip = n_err = 0
    t0 = time.time()
    for i, job in enumerate(spec["jobs"]):
        p = os.path.join(out, job["id"] + ".csv")
        if os.path.exists(p):
            n_skip += 1
            continue
        try:
            d = run(job)
            tmp = p + ".tmp"
            d.to_csv(tmp, index=False)
            os.replace(tmp, p)
            ep = os.path.join(out, job["id"] + ".err")
            if os.path.exists(ep):
                os.remove(ep)
            n_ok += 1
        except Exception as ex:  # noqa: BLE001
            json.dump({"id": job["id"], "error": str(ex)[:500]}, open(os.path.join(out, job["id"] + ".err"), "w",
                                                                       encoding="utf-8"), ensure_ascii=False)
            n_err += 1
        if (i + 1) % 20 == 0:
            print(f"[{i + 1}/{len(spec['jobs'])}] ok={n_ok} skip={n_skip} err={n_err} {time.time() - t0:.0f}s", flush=True)
    print(f"done ok={n_ok} skip={n_skip} err={n_err} {time.time() - t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
