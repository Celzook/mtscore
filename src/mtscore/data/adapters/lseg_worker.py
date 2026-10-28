"""lseg-data 수집 워커 — `%LOCALAPPDATA%\\lsegvenv` 의 Windows python.exe 로만 실행한다(eikon 쪽 pandas 3.0 과 분리).

    printf '%s\\n%s\\n' "<키>" jobs.json | /mnt/c/Users/infomax/AppData/Local/lsegvenv/Scripts/python.exe -I lseg_worker.py

작업 파일(JSON): {"out_dir": ..., "jobs": [{"id", "kind": "hist", "ric", "fields": [..] | null, "start", "end"}]}
결과: out_dir/<id>.csv (get_history 원응답, 날짜 index 를 Date 열로). 실패는 <id>.err. 있는 .csv 는 건너뛴다.
키는 어디에도 쓰지 않는다.
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

import lseg.data as ld  # noqa: E402


def main():
    spec = json.load(open(JOBS, encoding="utf-8"))
    out = spec["out_dir"]
    os.makedirs(out, exist_ok=True)
    s = ld.session.desktop.Definition(app_key=KEY).get_session()
    ld.session.set_default(s)
    s.open()
    try:
        for job in spec["jobs"]:
            p = os.path.join(out, job["id"] + ".csv")
            if os.path.exists(p):
                continue
            try:
                kw = {"start": job["start"], "end": job["end"]}
                if job.get("fields"):
                    kw["fields"] = job["fields"]
                for k in range(3):
                    try:
                        d = ld.get_history(job["ric"], **kw)
                        break
                    except Exception:  # noqa: BLE001
                        if k == 2:
                            raise
                        time.sleep(3)
                d = d.copy()
                d.index.name = "Date"
                d.columns = [str(c) for c in d.columns]
                d.reset_index().to_csv(p + ".tmp", index=False)
                os.replace(p + ".tmp", p)
            except Exception as ex:  # noqa: BLE001
                json.dump({"id": job["id"], "error": str(ex)[:500]},
                          open(os.path.join(out, job["id"] + ".err"), "w", encoding="utf-8"), ensure_ascii=False)
            print("done", job["id"], flush=True)
    finally:
        s.close()


if __name__ == "__main__":
    main()
