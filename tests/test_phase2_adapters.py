"""Phase 2 어댑터 — 녹화한 작은 원응답(tests/fixtures/phase2)으로 파싱·as_of 규칙·스키마 통과를 확인한다(네트워크 없음)."""
import json
from pathlib import Path

import pandas as pd
import pytest

from mtscore.data.adapters import cftc, ecos, fred, krx, refinitiv
from mtscore.data.schema import validate_panel

FX = Path(__file__).parent / "fixtures" / "phase2"


# ---- Refinitiv
def test_parse_timeseries_single_drops_intraday_bar():
    raw = pd.read_csv(FX / "refinitiv" / "KRTSY10Y_KQ__2025.csv")
    last = pd.to_datetime(raw["Date"]).max()
    out = refinitiv.parse_timeseries_single(raw, "KRTSY10Y=KQ", drop_after=str((last - pd.Timedelta(days=1)).date()))
    assert out["date"].max() < last           # 기준일 이후(장중 봉) 제거
    assert (out["ric"] == "KRTSY10Y=KQ").all()
    assert len(out) == len(raw) - 1


def test_parse_get_data_dedups_holiday_redated_rows():
    raw = pd.read_csv(FX / "refinitiv" / "SPX_close.csv")
    out = refinitiv.parse_get_data(raw)
    assert raw.duplicated(["Instrument", "Date"]).sum() == 2      # 12-24·12-31 이 두 번 온다(휴장일 재반환)
    assert not out.duplicated(["ric", "date"]).any()
    assert pd.Timestamp("2025-12-25") not in set(out["date"])
    p = validate_panel(refinitiv.to_panel(out, "SP500", "close", "refinitiv:.SPX"))
    assert (p["as_of"] == p["date"]).all()


def test_refinitiv_adapter_reads_cache(tmp_path):
    a = refinitiv.RefinitivAdapter({("KTB10Y", "yield"): {"file": FX / "refinitiv" / "KRTSY10Y_KQ__2025.csv",
                                                         "ric": "KRTSY10Y=KQ", "kind": "ts"}})
    p = a.fetch("KTB10Y", ["yield", "policy_rate"])
    assert set(p["field"]) == {"yield"} and len(p) == 6
    assert p["source"].iloc[0] == "refinitiv:KRTSY10Y=KQ"


def test_run_jobs_key_via_stdin_only_and_resumes(tmp_path, monkeypatch):
    (tmp_path / "a.csv").write_text("x\n1\n")
    (tmp_path / "b.err").write_text(json.dumps({"id": "b", "error": "No data available"}))
    calls = []
    monkeypatch.setattr(refinitiv, "_key", lambda: "SECRET-KEY")
    monkeypatch.setattr(refinitiv, "_winpath", lambda p: str(p))

    def fake_run(argv, input=None, **kw):
        calls.append((argv, input))
        spec = json.loads(Path(input.splitlines()[1]).read_text())
        assert [j["id"] for j in spec["jobs"]] == ["b"]          # 받은 작업(a)은 다시 보내지 않는다
    monkeypatch.setattr(refinitiv.subprocess, "run", fake_run)
    r = refinitiv.run_jobs([{"id": "a"}, {"id": "b"}], tmp_path)
    assert r["ok"] == ["a"] and r["err"] == {"b": "No data available"}
    argv, stdin = calls[0]
    assert "SECRET-KEY" not in " ".join(argv) and stdin.startswith("SECRET-KEY\n")
    assert "-I" in argv                                          # 같은 폴더 csv.py 가 표준 csv 를 가리지 않게
    assert not list(tmp_path.glob("_jobs_*.json"))               # 작업 파일은 지운다
    calls.clear()
    (tmp_path / "b.csv").write_text("x\n1\n")
    assert refinitiv.run_jobs([{"id": "a"}, {"id": "b"}], tmp_path)["ok"] == ["a", "b"] and not calls


# ---- FRED
def test_fred_rejects_html():
    with pytest.raises(fred.FredHtmlError):
        fred.parse_fredgraph((FX / "fred" / "HTMLSER.csv").read_text(), "HTMLSER")


def test_fred_as_of_rules():
    a = fred.FredAdapter({("UST10Y", "cpi"): "CPIAUCSL", ("UST10Y", "nfci"): "NFCI", ("X", "y"): "DGS10"},
                         FX / "fred", download=False)
    cpi = a.fetch("UST10Y", ["cpi"])
    r = cpi.iloc[-1]
    assert r["date"] == pd.Timestamp(r["date"].year, r["date"].month, 1)
    nxt = r["date"] + pd.offsets.MonthBegin(1)
    assert r["as_of"] == nxt + pd.Timedelta(days=14)            # 다음 달 15일
    nf = a.fetch("UST10Y", ["nfci"])
    assert ((nf["as_of"] - nf["date"]).dt.days == 5).all()       # 금요일 → 수요일
    assert (nf["date"].dt.dayofweek == 4).all()
    dg = a.fetch("X", ["y"])
    assert (dg["as_of"] > dg["date"]).all() and (dg["as_of"].dt.dayofweek < 5).all()   # +1 영업일


def test_fred_unknown_series_rule_raises():
    with pytest.raises(KeyError):
        fred.as_of_for("NOPE", pd.Series(pd.to_datetime(["2020-01-01"])))


# ---- ECOS
def test_ecos_monthly_parse_and_as_of():
    a = ecos.EcosAdapter({("KTB10Y", "cpi"): ("901Y009", "M", "202508", "202610", "0")}, FX / "ecos", download=False)
    p = a.fetch("KTB10Y", ["cpi"])
    assert (p["date"].dt.day == 1).all()
    last = p.iloc[-1]
    assert last["as_of"] == last["date"] + pd.DateOffset(months=1, days=4)   # 다음 달 5일
    assert p["source"].iloc[0] == "ecos:901Y009/0"


def test_ecos_parse_rows_daily():
    rows = [{"TIME": "20261023", "DATA_VALUE": "4.097"}, {"TIME": "20261022", "DATA_VALUE": "4.1"}]
    d = ecos.parse_rows(rows, "D")
    assert list(d["date"]) == [pd.Timestamp("2026-10-22"), pd.Timestamp("2026-10-23")]


# ---- CFTC
def test_cftc_net_and_friday_as_of():
    recs = json.loads((FX / "cftc" / "cot_088691.json").read_text())
    d = cftc.parse_records(recs)
    r = recs[-1]
    assert d["value"].iloc[-1] == int(r["noncomm_positions_long_all"]) - int(r["noncomm_positions_short_all"])
    p = cftc.CftcAdapter({("GOLD", "cot_net"): "088691"}, FX / "cftc", download=False).fetch("GOLD", ["cot_net"])
    assert (p["date"].dt.dayofweek == 1).all() and (p["as_of"].dt.dayofweek == 4).all()


# ---- KRX
def test_krx_index_day_parse():
    j = json.loads((FX / "krx" / "idx_kospi_dd_trd_20261023.json").read_text())
    d = krx.parse_index_day(j)
    assert len(d) == 1 and d["date"].iloc[0] == pd.Timestamp("2026-10-23") and d["close"].iloc[0] > 0
    assert krx.parse_index_day({"OutBlock_1": []}).empty
    p = krx.KrxIndexAdapter(["2026-10-23"], FX / "krx", download=False).fetch("KOSPI200", ["close"])
    assert len(p) == 1 and p["field"].iloc[0] == "close"


ALFRED_TXT = """observation_date,CPIAUCSL_20200113,CPIAUCSL_20200114,CPIAUCSL_20200214
2019-11-01,257.936,257.936,257.9
2019-12-01,,258.501,258.6
2020-01-01,,,258.820
"""


def test_alfred_first_release_and_no_backfill():
    long = fred.parse_alfred(ALFRED_TXT)
    fr = fred.first_releases(long)
    # 2019-11 은 첫 표본 빈티지에 이미 있던 값(공표일 모름) — 백로그 중 최신 하나만 남긴다
    assert list(fr["date"].dt.strftime("%Y-%m")) == ["2019-11", "2019-12", "2020-01"]
    r = fr.set_index("date")
    assert r.loc["2019-12-01", "value"] == 258.501 and r.loc["2019-12-01", "as_of"] == pd.Timestamp("2020-01-14")
    assert r.loc["2020-01-01", "as_of"] == pd.Timestamp("2020-02-14")
    with pytest.raises(fred.FredHtmlError):
        fred.parse_alfred("<!DOCTYPE html><html></html>")


def test_next_us_bday_skips_holidays_and_weekends():
    d = fred.next_us_bday(pd.to_datetime(["2026-07-02", "2026-04-02", "2026-10-24", "2025-12-24"]))
    assert list(d) == list(pd.to_datetime(["2026-07-06", "2026-04-06", "2026-10-26", "2025-12-26"]))


def test_alfred_drops_out_of_window_first_appearance():
    txt = """observation_date,X_20200114,X_20200214
1950-01-01,,24.0
2019-12-01,258.5,258.6
2020-01-01,,258.8
"""
    fr = fred.first_releases(fred.parse_alfred(txt), max_lag_days=75)
    assert pd.Timestamp("1950-01-01") not in set(fr["date"])
