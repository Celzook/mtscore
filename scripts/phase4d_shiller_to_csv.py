"""Phase 4 D-1 — Shiller ie_data.xls(Data 시트) → CSV. xlrd 만 쓴다(.venv 에는 xlrd 가 없다).

    uv run --no-project --with xlrd==2.0.2 python -I scripts/phase4d_shiller_to_csv.py <in.xls> <out.csv>

열: month(YYYY-MM-01), P, D, E, CPI, CAPE(Shiller 가 계산한 P/E10, 대조용). 빈 칸·'NA' 는 빈 값으로 둔다(채우지 않는다).
날짜 셀은 year + month/100 (예: 2026.1 = 2026년 10월).
"""
import csv
import sys

import xlrd

COLS = {"P": 1, "D": 2, "E": 3, "CPI": 4, "CAPE": 12}   # Data 시트 8행 머리글: Date, P, D, E, CPI, ..., CAPE(13번째 열)


def num(v):
    return "" if isinstance(v, str) else repr(float(v))


def main(src, dst):
    s = xlrd.open_workbook(src).sheet_by_name("Data")
    head = [str(s.cell_value(7, c)).strip() for c in range(s.ncols)]
    assert head[0] == "Date" and [head[c] for c in (1, 2, 3, 4, 12)] == ["P", "D", "E", "CPI", "CAPE"], head
    n = 0
    with open(dst, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["month", *COLS])
        for r in range(8, s.nrows):
            d = s.cell_value(r, 0)
            if not isinstance(d, float):
                continue
            y = int(d)
            m = int(round((d - y) * 100))
            assert 1 <= m <= 12, (r, d)
            w.writerow([f"{y:04d}-{m:02d}-01", *(num(s.cell_value(r, c)) for c in COLS.values())])
            n += 1
    print(dst, n, "rows")


if __name__ == "__main__":
    main(*sys.argv[1:3])
