import numpy as np
import pandas as pd
import pytest

from mtscore import SchemaError, validate_panel
from mtscore.data.adapters import CsvAdapter


def base_rows():
    return pd.DataFrame({"date": ["2024-01-02", "2024-01-03"], "asset_id": ["A", "A"], "field": ["close", "close"],
                         "value": [1.0, 2.0]})


def test_as_of_defaults_to_date_and_source_filled():
    out = validate_panel(base_rows())
    assert (out["as_of"] == out["date"]).all()
    assert list(out.columns) == ["date", "asset_id", "field", "value", "as_of", "source"]
    assert (out["source"] == "").all()


def test_missing_required_column_rejected():
    with pytest.raises(SchemaError, match="필수 컬럼"):
        validate_panel(base_rows().drop(columns="field"))


def test_non_numeric_value_rejected():
    df = base_rows()
    df["value"] = df["value"].astype(object)
    df.loc[1, "value"] = "abc"
    with pytest.raises(SchemaError, match="숫자 변환"):
        validate_panel(df)


def test_bad_date_rejected():
    df = base_rows()
    df.loc[0, "date"] = "not-a-date"
    with pytest.raises(SchemaError, match="날짜 변환"):
        validate_panel(df)


def test_as_of_before_date_rejected():
    df = base_rows().assign(as_of=["2024-01-01", "2024-01-03"])
    with pytest.raises(SchemaError, match="as_of < date"):
        validate_panel(df)


def test_duplicate_key_rejected():
    df = pd.concat([base_rows(), base_rows().iloc[[0]]], ignore_index=True)
    with pytest.raises(SchemaError, match="중복"):
        validate_panel(df)


def test_same_date_different_vintage_allowed():
    df = pd.concat([base_rows(), base_rows().iloc[[0]].assign(as_of="2024-01-05", value=1.5)], ignore_index=True)
    assert len(validate_panel(df)) == 3


def test_inf_and_nan_values_dropped():
    df = base_rows()
    df.loc[0, "value"] = np.inf
    out = validate_panel(df)
    assert len(out) == 1 and out["value"].iloc[0] == 2.0


def test_csv_adapter_roundtrip(tmp_path):
    p = tmp_path / "x.csv"
    base_rows().assign(as_of="", source="manual").to_csv(p, index=False)
    (tmp_path / "TEMPLATE.csv").write_text("date,asset_id,field,value,as_of,source\n")
    out = CsvAdapter(tmp_path).fetch("A", ["close"], start="2024-01-03")
    assert len(out) == 1 and out["value"].iloc[0] == 2.0 and out["source"].iloc[0] == "manual"
    assert out["as_of"].iloc[0] == pd.Timestamp("2024-01-03")


def test_csv_adapter_rejects_contract_violation(tmp_path):
    p = tmp_path / "x.csv"
    base_rows().assign(as_of="2023-12-31").to_csv(p, index=False)
    with pytest.raises(SchemaError):
        CsvAdapter(tmp_path).fetch("A", ["close"])
