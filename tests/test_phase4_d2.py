"""Phase 4 D-2 바텀업 CAPE(data/cape_bu.py) — PIT 가용일·창 요건·CPI 공표 규칙을 작은 합성 입력으로 확인한다(테스트 전용)."""
import numpy as np
import pandas as pd

from mtscore.data import cape_bu as C

T = pd.Timestamp


def _fiscal(ric="A.KS", years=range(2001, 2013), ni=100.0, ann=None, ibes=None, month=12):
    pe = [T(f"{y}-{month:02d}-01") + pd.offsets.MonthEnd(0) for y in years]
    return pd.DataFrame({"ric": ric, "pe": pe, "ni": ni,
                         "ann": pd.NaT if ann is None else ann, "ibes_date": pd.NaT if ibes is None else ibes})


def _cpi(start="1999-01-01", end="2026-12-01", value=100.0, growth=0.0):
    d = pd.date_range(start, end, freq="MS")
    v = value * (1 + growth) ** np.arange(len(d))
    return pd.DataFrame({"date": d, "value": v, "as_of": d + pd.DateOffset(months=1, days=4)})


def _mcap(ric, dates, mc=1000.0):
    return pd.DataFrame({"ric": ric, "date": pd.to_datetime(dates), "mcap": mc})


def test_avail_is_later_of_lag_floor_and_filing():
    f = _fiscal(years=[2010, 2011, 2012])
    f["ann"] = [T("2011-01-20 23:00"), T("2012-05-10 03:00"), pd.NaT]   # 이른 공시·늦은 공시·결측
    a = C.available_date(f).set_index("pe")
    assert a.loc[T("2010-12-31"), "avail"] == T("2011-03-31")     # 결산 + 90일 바닥
    assert a.loc[T("2011-12-31"), "avail"] == T("2012-05-11")     # 늦은 공시는 다음 날부터
    assert a.loc[T("2012-12-31"), "avail"] == T("2013-03-31")     # 공시일 결측 → 결산 + 90일
    assert list(a["avail_src"]) == ["ann", "ann", "lag_only"]


def test_avail_caps_implausible_announcement_and_falls_back_to_ibes():
    f = _fiscal(years=[2010])
    f["ann"] = [T("2015-01-01")]       # 결산 + 365일 초과 → 쓰지 않는다
    f["ibes_date"] = [T("2011-06-01")]
    a = C.available_date(f).iloc[0]
    assert a["avail_src"] == "ibes" and a["avail"] == T("2011-06-02")


def test_member_e10_pit_excludes_unavailable_year():
    f = C.available_date(_fiscal(years=range(2002, 2013), ni=100.0))
    f.loc[f["pe"] == T("2012-12-31"), "ni"] = 1100.0      # 2012 연도만 큰 이익
    cpi = _cpi()
    before = C.member_e10(f, cpi, T("2013-03-30"), 100.0)  # 2012 연도는 2013-03-31 부터
    after = C.member_e10(f, cpi, T("2013-03-31"), 100.0)
    assert before == 100.0                                  # 2003~2012 아님: 2002~2011 창
    assert after == (100.0 * 9 + 1100.0) / 10


def test_member_e10_requires_full_window():
    f = C.available_date(_fiscal(years=range(2004, 2013)))  # 9개 연도뿐
    assert np.isnan(C.member_e10(f, _cpi(), T("2013-12-31"), 100.0))
    f10 = C.available_date(_fiscal(years=range(2003, 2013)))
    assert C.member_e10(f10, _cpi(), T("2013-12-31"), 100.0) == 100.0


def test_member_e10_span_and_stale_rules():
    yrs = [y for y in range(2000, 2013) if y not in (2005, 2006)]   # 전환기 2개 빠짐 → 11년 넘게 걸침
    f = C.available_date(_fiscal(years=yrs))
    assert np.isnan(C.member_e10(f, _cpi(), T("2013-06-30"), 100.0))
    yrs1 = [y for y in range(2002, 2013) if y != 2006]               # 1개 빠짐 → 허용
    assert C.member_e10(C.available_date(_fiscal(years=yrs1)), _cpi(), T("2013-06-30"), 100.0) == 100.0
    f2 = C.available_date(_fiscal(years=range(2001, 2011)))         # 최신 결산 2010 → 2013-06 에는 낡음
    assert np.isnan(C.member_e10(f2, _cpi(), T("2013-06-30"), 100.0))


def test_real_terms_use_cpi_known_at_asof():
    f = C.available_date(_fiscal(years=range(2003, 2013), ni=100.0))
    cpi = _cpi(growth=0.01)
    asof = T("2013-04-30")
    known = cpi[cpi["as_of"] <= asof]
    now = float(known["value"].iloc[-1])
    assert known["date"].iloc[-1] == T("2013-03-01")      # 4월분은 5월 5일 공표 → 아직 모른다
    e = C.member_e10(f, cpi, asof, now)
    fy = [cpi[(cpi["date"].dt.year == y)]["value"].mean() for y in range(2003, 2013)]
    assert np.isclose(e, np.mean([100.0 * now / c for c in fy]))
    # 결산월 CPI 가 아직 공표 전이면 그 연도는 실질화할 수 없다 → NaN
    assert np.isnan(C.cpi_fy_avg(cpi, T("2012-12-31"), T("2013-01-04")))


def test_cape_bottomup_aggregates_same_members_and_nans_without_window():
    fa = pd.concat([_fiscal("A.KS", range(2003, 2013), 100.0), _fiscal("B.KS", range(2005, 2013), 50.0)])
    mc = pd.concat([_mcap("A.KS", ["2013-04-30", "2013-05-31"], 2000.0), _mcap("B.KS", ["2013-04-30"], 500.0)])
    out = C.cape_bottomup(fa, mc, _cpi(), ["A.KS", "B.KS"], min_share=0.5).set_index("date")
    r = out.loc[T("2013-04-30")]
    assert r["value"] == 2000.0 / 100.0                   # B 는 창 미성립 → 분자·분모 모두에서 빠진다
    assert r["n_listed"] == 2 and r["n_used"] == 1 and np.isclose(r["mcap_share_used"], 0.8)
    strict = C.cape_bottomup(fa, mc, _cpi(), ["A.KS", "B.KS"]).set_index("date")   # 기본 min_share 0.9 > 0.8
    assert np.isnan(strict.loc[T("2013-04-30"), "value"]) and strict.loc[T("2013-05-31"), "value"] == 20.0
    assert out.loc[T("2013-05-31"), "as_of"] == T("2013-05-31")
    none = C.cape_bottomup(_fiscal("A.KS", range(2004, 2013)), _mcap("A.KS", ["2013-04-30"]), _cpi(), ["A.KS"])
    assert np.isnan(none["value"].iloc[0])


def test_cape_bottomup_future_rows_do_not_change_past():
    fa = _fiscal("A.KS", range(2003, 2014), 100.0)
    mc = _mcap("A.KS", ["2013-04-30", "2014-04-30"], 1000.0)
    full = C.cape_bottomup(fa, mc, _cpi(), ["A.KS"]).set_index("date")["value"]
    fa2 = fa.copy()
    fa2.loc[fa2["pe"] == T("2013-12-31"), "ni"] = 9999.0   # 미래(2014-03-31 가용) 연도 수정
    cut = C.cape_bottomup(fa2, mc, _cpi(), ["A.KS"]).set_index("date")["value"]
    assert cut.loc[T("2013-04-30")] == full.loc[T("2013-04-30")]
    assert cut.loc[T("2014-04-30")] != full.loc[T("2014-04-30")]


def test_fixed_set_and_parse_fiscal_keep_controlling_ni_only():
    raw = pd.DataFrame({"Instrument": ["A.KS", "A.KS", "B.KS"],
                        "Period End Date": ["2003-12-31", "2004-12-31", "2005-12-31"],
                        "Original Announcement Date Time": ["2004-02-01T00:00:00Z", None, None],
                        "Net Income after Minority Interest": [1.0, None, 3.0],
                        "Net Income after Tax": [1.1, 2.0, 3.1]})
    f = C.parse_fiscal(raw)
    assert len(f) == 2 and set(f["ric"]) == {"A.KS", "B.KS"}   # 지배 NI 결측 행은 총 NI 로 채우지 않는다
    assert C.fixed_set(f, 2003) == ["A.KS"]
