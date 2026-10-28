"""Phase 2 — ALFRED 빈티지(실시간 값) 수집: CPIAUCSL·NFCI·THREEFYTP10 (사용자 결정 2026-10-28 E·F). 재개 가능.

    .venv/bin/python scripts/phase2_collect_alfred.py      # 약 1,000 요청(평일마다 빈티지 하나, 요청당 12개)
"""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from mtscore.data.adapters.fred import alfred_download  # noqa: E402

END = "2026-10-27"
SPECS = {"CPIAUCSL": ("2007-01-01", 75), "NFCI": ("2011-05-25", 60), "THREEFYTP10": ("2016-05-27", 250)}   # 첫 빈티지(이분 탐색, 2026-10-28)

if __name__ == "__main__":
    for sid in sys.argv[1:] or SPECS:
        start, lb = SPECS[sid]
        t = time.time()
        ps = alfred_download(sid, start, END, ROOT / "data" / "raw" / "fred", lb)
        print(sid, len(ps), "files", round(time.time() - t), "s", flush=True)
