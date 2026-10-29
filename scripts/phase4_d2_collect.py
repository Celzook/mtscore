"""Phase 4 D-2 — KOSPI200 바텀업 CAPE 원자료 수집(민감도 필드 전용, 점수 미사용). 재개 가능: 받은 파일은 건너뛴다.

    .venv/bin/python scripts/phase4_d2_collect.py        # Refinitiv(워커 python.exe) + ECOS CPI

원자료: data/raw/phase4d2_kr/{ni,eps,mcap}/<id>.csv(Refinitiv 원응답), data/raw/phase4d2_kr/ecos/(CPI 1995~).
종목: 현재 KODEX200 보유종목(data/raw/refinitiv/holdings/kodex200.csv, Phase 2 수집분 — 읽기만).
키는 워커 stdin 으로만 넘긴다(run_jobs). END 는 Phase 2 와 같은 마지막 완결 거래일.
"""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
from mtscore.data.adapters import ecos  # noqa: E402
from mtscore.data.adapters.refinitiv import run_jobs  # noqa: E402
from phase2_collect_refinitiv import holdings  # noqa: E402

RAW = ROOT / "data" / "raw" / "phase4d2_kr"
END = "2026-10-27"
BATCH = 25
FY = {"Period": "FY0", "Frq": "FY", "SDate": "0", "EDate": "-30"}   # 최근 회계연도부터 30개 연도(1996년 무렵까지)
MCAP_CHUNKS = [("1999-01-01", "2009-12-31"), ("2010-01-01", END)]


def jobs():
    rics = holdings("kodex200")
    out = {"ni": [], "eps": [], "mcap": []}
    for i in range(0, len(rics), BATCH):
        b = rics[i:i + BATCH]
        # 지배주주 순이익(연간, Refinitiv Fundamentals) + 원 공표일. 값은 최신 수정치(가정: 최초 공표값 아님).
        out["ni"].append({"id": f"ni_{i:04d}", "kind": "gd", "rics": b, "params": FY,
                          "fields": ["TR.F.NetIncAfterMinIntr.periodenddate", "TR.F.OriginalAnnouncementDate",
                                     "TR.F.NetIncAfterMinIntr", "TR.F.NetIncAfterTax"]})
        # I/B/E/S 실적 EPS 와 그 반환 날짜(공표일 대조·결측 보완용)
        out["eps"].append({"id": f"eps_{i:04d}", "kind": "gd", "rics": b, "params": FY,
                           "fields": ["TR.EPSActValue.periodenddate", "TR.EPSActValue.date", "TR.EPSActValue"]})
        for s, e in MCAP_CHUNKS:
            out["mcap"].append({"id": f"mcap_{i:04d}_{s[:4]}", "kind": "gd", "rics": b,
                                "fields": ["TR.CompanyMarketCap.date", "TR.CompanyMarketCap"],
                                "params": {"SDate": s, "EDate": e, "Frq": "M", "Curn": "KRW"}})
    return out


if __name__ == "__main__":
    for sec, js in jobs().items():
        t = time.time()
        r = run_jobs(js, RAW / sec, log_file=RAW / "worker.log")
        print(f"{sec}: jobs={len(js)} ok={len(r['ok'])} err={len(r['err'])} {time.time() - t:.0f}s", flush=True)
        for k, v in list(r["err"].items())[:10]:
            print("  ERR", k, v[:160], flush=True)
    p = ecos.download("901Y009", "M", "199501", "202610", "0", RAW / "ecos")   # 소비자물가 총지수(2020=100)
    print("ecos cpi:", p.name, len(ecos.read_raw(p, "M")), "rows", flush=True)
