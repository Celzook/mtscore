"""Phase 4 C0 — 장기 반전 지표용 과거 가격(2005~2009) 수집. WSL 에서 실행, 워커는 Windows python.exe(키는 stdin).

    .venv/bin/python scripts/phase4c_collect.py

원자료: data/raw/phase4c_long/refinitiv/<RIC>__2005.csv (gitignore, 재개 가능 — 받은 파일은 건너뛴다).
2010~ 구간은 Phase 2 원자료(data/raw/refinitiv/ts)를 읽기만 한다(덮어쓰지 않는다).
REER(FRED RBKRBIS)는 Phase 2 캐시가 1994-01 부터라 data/raw/phase4c_long/fred/ 로 복사만 한다.
"""
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from mtscore.data.adapters.refinitiv import run_jobs  # noqa: E402

OUT = ROOT / "data" / "raw" / "phase4c_long"
START, END = "2005-01-01", "2009-12-31"   # 사전 등록 C1: 목표 2005-01. 2010~ 은 Phase 2 원자료
RICS = ["GCc1", "GCc2", "GCc3", "GCc4", "CLc1", "CLc2", "KRTSY10Y=KQ", "US10YT=RR"]


def safe(r):
    return r.replace("=", "_").replace(".", "_").replace("#", "_")


if __name__ == "__main__":
    t = time.time()
    jobs = [{"id": f"{safe(r)}__2005", "kind": "ts", "rics": [r], "fields": ["CLOSE"], "start": START, "end": END}
            for r in RICS]
    r = run_jobs(jobs, OUT / "refinitiv", log_file=OUT / "worker.log")
    print(f"refinitiv: jobs={len(jobs)} ok={len(r['ok'])} err={len(r['err'])} {time.time() - t:.0f}s", flush=True)
    for k, v in r["err"].items():
        print("  ERR", k, v[:200], flush=True)
    (OUT / "fred").mkdir(parents=True, exist_ok=True)
    src = ROOT / "data" / "raw" / "fred" / "RBKRBIS.csv"
    dst = OUT / "fred" / "RBKRBIS.csv"
    if not dst.exists():
        shutil.copyfile(src, dst)
    print(f"fred: RBKRBIS 복사 {dst.relative_to(ROOT)}", flush=True)
