"""Refinitiv(eikon) 어댑터 — WSL 에서 Windows `python.exe` 워커(refinitiv_worker.py)를 subprocess 로 부른다.

- 키: 파일(`REFINITIV_APPKEY_FILE`, 기본 ~/.claude/reference/refinitiv-workspace/.appkey)에서 읽어 워커 stdin 으로만 넘긴다.
  출력·로그·파일에 남기지 않는다.
- 원응답은 `data/raw/refinitiv/<id>.csv` 에 캐시한다(재개 가능: 있는 파일은 다시 받지 않는다).
- 파싱(원응답 → 4-1 패널)은 네트워크 없는 순수 함수로 두어 녹화 fixture 로 테스트한다.

as_of 규칙
- 일별 가격·금리(get_timeseries CLOSE, get_data TR.PriceClose Frq=D): as_of = date(그 시장 마감 뒤 알려짐).
- 월별 컨센서스(TR.EPSMean 등 Frq=M): as_of = date = 표본일(행의 날짜 열 중 가장 늦은 날 — 월말·스냅숏일).
  반환 날짜는 '마지막 변경일'이라 다음 달에도 같은 날짜로 다른 값이 온다(NTM 혼합). 사용자 승인 2026-10-28 D.
  다필드 응답은 data.build.bottomup_rows 가 표본일을 만든다. TR.PtoEPSMeanEst 는 반환 날짜가 곧 월말 표본일이다.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd

from .base import BaseAdapter

WORKER = Path(__file__).with_name("refinitiv_worker.py")
LSEG_WORKER = Path(__file__).with_name("lseg_worker.py")
DEFAULT_KEY_FILE = Path.home() / ".claude/reference/refinitiv-workspace/.appkey"
WIN_PYTHON = "python.exe"
LSEG_PYTHON = "/mnt/c/Users/infomax/AppData/Local/lsegvenv/Scripts/python.exe"


def _winpath(p: Path) -> str:
    return subprocess.run(["wslpath", "-w", str(p)], capture_output=True, text=True, check=True).stdout.strip()


def _key() -> str:
    p = Path(os.environ.get("REFINITIV_APPKEY_FILE", DEFAULT_KEY_FILE))
    return p.read_text().strip()


def run_jobs(jobs: list[dict], out_dir: Path, python: str = WIN_PYTHON, worker: Path = WORKER,
             timeout: int | None = None, log_file: Path | None = None) -> dict:
    """작업 목록을 워커로 실행한다. 이미 받은 작업(<id>.csv)은 워커가 건너뛴다.

    Returns: {"ok": [...], "err": {id: message}} — 실행 후 디스크 상태 기준.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    todo = [j for j in jobs if not (out_dir / f"{j['id']}.csv").exists()]
    if todo:
        spec = out_dir / f"_jobs_{os.getpid()}.json"
        spec.write_text(json.dumps({"out_dir": _winpath(out_dir), "jobs": todo}, ensure_ascii=False), encoding="utf-8")
        stdin = f"{_key()}\n{_winpath(spec)}\n"
        log = open(log_file, "a", encoding="utf-8") if log_file else subprocess.DEVNULL
        try:
            subprocess.run([python, "-I", _winpath(worker)], input=stdin, text=True, stdout=log, stderr=subprocess.STDOUT,
                           timeout=timeout, check=False)
        finally:
            if log_file:
                log.close()
            spec.unlink(missing_ok=True)
    ok = [j["id"] for j in jobs if (out_dir / f"{j['id']}.csv").exists()]
    err = {}
    for j in jobs:
        ep = out_dir / f"{j['id']}.err"
        if j["id"] not in ok and ep.exists():
            err[j["id"]] = json.loads(ep.read_text(encoding="utf-8")).get("error", "")
    return {"ok": ok, "err": err}


# ---- 순수 파싱 (네트워크 없음)
def parse_timeseries(raw: pd.DataFrame, drop_after: str | None = None) -> pd.DataFrame:
    """get_timeseries 원응답(reset_index: Date + RIC 열들, 또는 Date + CLOSE) → long (date, ric, value).

    단일 RIC 요청은 열 이름이 필드명(CLOSE)이므로 호출자가 ric 열을 바꿔 줘야 한다 — parse_timeseries_single 사용.
    drop_after: 이 날짜보다 늦은 행 제거(장중 미완성 봉 방지).
    """
    d = raw.rename(columns={raw.columns[0]: "date"})
    d["date"] = pd.to_datetime(d["date"]).dt.normalize()
    long = d.melt(id_vars="date", var_name="ric", value_name="value")
    long["value"] = pd.to_numeric(long["value"], errors="coerce")
    long = long.dropna(subset=["value"])
    if drop_after is not None:
        long = long[long["date"] <= pd.Timestamp(drop_after)]
    return long.drop_duplicates(["date", "ric"], keep="last").sort_values(["ric", "date"]).reset_index(drop=True)


def parse_timeseries_single(raw: pd.DataFrame, ric: str, drop_after: str | None = None) -> pd.DataFrame:
    """단일 RIC get_timeseries 원응답(Date, CLOSE) → long (date, ric, value)."""
    d = raw.iloc[:, :2].copy()
    d.columns = ["date", ric]
    return parse_timeseries(d, drop_after)


def parse_get_data(raw: pd.DataFrame, value_name: str = "value") -> pd.DataFrame:
    """get_data(ric 들, [F.date, F], Frq=…) 원응답 → long (ric, date, value). 빈 값·날짜 없는 행은 버린다.

    같은 (ric, date) 가 여러 번 오면(휴장일에 직전 거래일 값이 그 날짜로 다시 오는 경우) 마지막을 남긴다.
    """
    d = raw.iloc[:, :3].copy()
    d.columns = ["ric", "date", value_name]
    d[value_name] = pd.to_numeric(d[value_name], errors="coerce")
    d["date"] = pd.to_datetime(d["date"], errors="coerce", utc=True).dt.tz_localize(None).dt.normalize()
    d = d.dropna(subset=["date", value_name])
    return d.drop_duplicates(["ric", "date"], keep="last").sort_values(["ric", "date"]).reset_index(drop=True)


def to_panel(long: pd.DataFrame, asset_id: str, field: str, source: str, as_of_lag_days: int = 0) -> pd.DataFrame:
    """(date, value) long → 4-1 패널. as_of = date + as_of_lag_days(달력일)."""
    out = pd.DataFrame({"date": long["date"].values, "asset_id": asset_id, "field": field,
                        "value": long["value"].astype(float).values})
    out["as_of"] = out["date"] + pd.Timedelta(days=as_of_lag_days)
    out["source"] = source
    return out


class RefinitivAdapter(BaseAdapter):
    """캐시된 원응답에서 (asset, field) 패널을 만든다. 수집은 scripts/phase2_collect.py 가 run_jobs 로 한다.

    mapping: {(asset_id, field): {"file": 캐시 csv 경로, "ric": RIC, "kind": "ts"|"gd"}}
    """

    source_name = "refinitiv"

    def __init__(self, mapping: dict, drop_after: str | None = None):
        self.mapping = mapping
        self.drop_after = drop_after

    def _fetch(self, asset, fields, start, end):
        parts = []
        for f in fields:
            m = self.mapping.get((asset, f))
            if m is None:
                continue
            raw = pd.concat([pd.read_csv(p) for p in np.atleast_1d(m["file"])], ignore_index=True)
            long = (parse_timeseries_single(raw, m["ric"], self.drop_after) if m["kind"] == "ts"
                    else parse_get_data(raw))
            if m["kind"] == "ts" and len(np.atleast_1d(m["file"])) > 1:
                long = long.drop_duplicates(["date"], keep="last")
            if start is not None:
                long = long[long["date"] >= pd.Timestamp(start)]
            if end is not None:
                long = long[long["date"] <= pd.Timestamp(end)]
            parts.append(to_panel(long, asset, f, f"refinitiv:{m['ric']}"))
        if not parts:
            return pd.DataFrame(columns=["date", "asset_id", "field", "value", "as_of", "source"])
        return pd.concat(parts, ignore_index=True)
