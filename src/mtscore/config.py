"""YAML 설정 로딩·검증. 지표 정의(IndicatorDef)는 여기서 프로파일 + 자산 overrides 로 만든다."""
from __future__ import annotations

import copy
import logging
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import yaml

from .core import indicators  # noqa: F401  (계산 함수 등록)
from .core.registry import IndicatorDef, get_func
from .core.scoring import BLOCKS, SUB_BLOCK_AGGS

log = logging.getLogger(__name__)

KNOWN_ASSET_KEYS = {"asset_id", "name", "asset_class", "currency", "return_field", "calendar_field", "refs",
                    "field_transforms", "overrides"}
FIELD_TRANSFORMS = ("reciprocal", "negate")
OVERRIDE_KEYS = {"exclude", "weights", "params", "add"}
PERCENTILE_METHODS = ("expanding", "rolling")
CURRENCY_VARIANTS = ("both", "oversold_only", "fundamental_only")
REGIME_KEYS = {"o", "v", "f", "label"}


class ConfigError(ValueError):
    """설정 파일 오류."""


@dataclass(frozen=True)
class AssetSpec:
    """유니버스 한 자산. calendar_field 는 자산 달력(거래일)을 정하는 필드(없으면 close·yield·spread 순으로 찾음)."""

    asset_id: str
    name: str
    asset_class: str
    currency: str = ""
    return_field: str = "close"
    calendar_field: str | None = None
    refs: dict = field(default_factory=dict)              # field → (asset_id, field)
    field_transforms: dict = field(default_factory=dict)  # field → reciprocal | negate
    overrides: dict = field(default_factory=dict)
    meta: dict = field(default_factory=dict)


@dataclass
class Config:
    """검증된 설정 묶음: 유니버스(자산 목록)·자산군 프로파일·스코어링 설정."""

    universe: list[AssetSpec]
    profiles: dict[str, dict]
    scoring: dict
    root: Path | None = None

    def asset(self, asset_id: str) -> AssetSpec:
        """asset_id 로 자산을 찾는다. 없으면 KeyError."""
        for a in self.universe:
            if a.asset_id == asset_id:
                return a
        raise KeyError(f"유니버스에 없는 자산: {asset_id}")

    def indicator_defs(self, asset: AssetSpec) -> tuple[list[IndicatorDef], dict[str, str], dict[str, float]]:
        """자산의 지표 정의, 사전 제외(지표 → 사유), 하위블록 가중치 override 를 돌려준다."""
        prof = self.profiles.get(asset.asset_class)
        if prof is None:
            raise ConfigError(f"{asset.asset_id}: 프로파일 없음({asset.asset_class})")
        ov = asset.overrides or {}
        bad = set(ov) - OVERRIDE_KEYS
        if bad:
            raise ConfigError(f"{asset.asset_id}: overrides 에 알 수 없는 키 {sorted(bad)} (허용 {sorted(OVERRIDE_KEYS)})")
        for k, typ in (("exclude", list), ("weights", dict), ("params", dict)):
            if ov.get(k) is not None and not isinstance(ov[k], typ):
                raise ConfigError(f"{asset.asset_id}: overrides.{k} 는 {typ.__name__}")
        excl_keys = set(ov.get("exclude", []) or [])
        weights = dict(ov.get("weights", {}) or {})
        params_ov = dict(ov.get("params", {}) or {})
        bad_p = {k: v for k, v in params_ov.items() if not isinstance(v, dict)}
        if bad_p:
            raise ConfigError(f"{asset.asset_id}: overrides.params 값은 dict ({bad_p})")
        blocks = copy.deepcopy(prof["blocks"])
        add = ov.get("add", {}) or {}
        if not isinstance(add, dict):
            raise ConfigError(f"{asset.asset_id}: overrides.add 는 {{'block.sub_block': [항목...]}} 형식")
        for key, items in add.items():  # 자산 전용 지표 추가
            if not isinstance(items, list) or not all(isinstance(i, dict) for i in items):
                raise ConfigError(f"{asset.asset_id}: overrides.add.{key} 는 지표 항목(dict)의 리스트")
            if "." not in key:
                raise ConfigError(f"{asset.asset_id}: overrides.add 키는 'block.sub_block' ({key!r})")
            blk, sb = key.split(".", 1)
            if blk not in BLOCKS:
                raise ConfigError(f"{asset.asset_id}: overrides.add 블록 오류 {blk!r} (허용 {BLOCKS})")
            blocks.setdefault(blk, {}).setdefault(sb, []).extend(copy.deepcopy(items or []))
        defs, excluded, sub_w = [], {}, {}
        item_w = set()   # 프로파일·overrides.add 항목에 weight 를 직접 적은 지표
        for blk, subs in blocks.items():
            for sb, items in subs.items():
                if f"{blk}.{sb}" in weights:
                    sub_w[f"{blk}.{sb}"] = _nonneg(weights[f"{blk}.{sb}"], f"{asset.asset_id}.weights.{blk}.{sb}")
                for it in items:
                    w = weights.get(it.get("name"))
                    d = _make_def(blk, sb, it, params_ov.get(it.get("name")),
                                  None if w is None else _nonneg(w, f"{asset.asset_id}.weights.{it.get('name')}"))
                    defs.append(d)
                    if "weight" in it:
                        item_w.add(d.name)
                    hit =excl_keys & {d.name, blk, sb, f"{blk}.{sb}"}
                    if hit:
                        excluded[d.name] = "override_exclude:" + ",".join(sorted(hit))
        names = [d.name for d in defs]
        dup = {n for n in names if names.count(n) > 1}
        if dup:
            raise ConfigError(f"{asset.asset_id}: 지표 이름 중복(overrides.add 포함) {sorted(dup)}")
        groups = {d.block for d in defs} | {d.sub_block for d in defs} | {f"{d.block}.{d.sub_block}" for d in defs}
        unknown = excl_keys - set(names) - groups
        if unknown:
            raise ConfigError(f"{asset.asset_id}: overrides.exclude 에 없는 이름 {sorted(unknown)}")
        unknown = set(weights) - set(names) - {f"{d.block}.{d.sub_block}" for d in defs}
        if unknown:
            raise ConfigError(f"{asset.asset_id}: overrides.weights 에 없는 이름 {sorted(unknown)}")
        unknown = set(params_ov) - set(names)
        if unknown:
            raise ConfigError(f"{asset.asset_id}: overrides.params 에 없는 지표 {sorted(unknown)}")
        agg = self.scoring.get("sub_block_agg") or {}
        in_min = sorted(d.name for d in defs if d.name in weights and agg.get(f"{d.block}.{d.sub_block}") == "min")
        if in_min:   # min 하위블록은 지표 가중치를 쓰지 않으므로(scoring._min_joint) 조용히 무시되는 설정을 막는다
            raise ConfigError(f"{asset.asset_id}: overrides.weights 의 {in_min} 는 min 하위블록 지표라 가중치가 적용되지 않음"
                              " — 빼려면 overrides.exclude 를 쓴다")
        in_min = sorted(d.name for d in defs if d.name in item_w and agg.get(f"{d.block}.{d.sub_block}") == "min")
        if in_min:
            raise ConfigError(f"{asset.asset_id}: 항목 weight 가 적힌 {in_min} 는 min 하위블록 지표라 가중치가 적용되지 않음"
                              " — weight 를 지우고, 빼려면 overrides.exclude 를 쓴다")
        return defs, excluded, sub_w


def _nonneg(v, where: str) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        raise ConfigError(f"{where}: 가중치는 숫자여야 함 ({v!r})") from None
    if not np.isfinite(f) or f < 0:
        raise ConfigError(f"{where}: 가중치는 0 이상 유한값 ({v!r})")
    return f


def _make_def(blk: str, sb: str, it: dict, params_override: dict | None, weight: float | None) -> IndicatorDef:
    name = it.get("name")
    if not name:
        raise ConfigError(f"{blk}.{sb}: name 없는 지표 항목 {it}")
    func = it.get("indicator", name)
    spec = get_func(func)
    dir_raw = str(it.get("direction", "")).strip()
    if dir_raw not in ("+", "-"):
        raise ConfigError(f"{name}: direction 은 '+' 또는 '-' ({dir_raw!r})")
    fields = tuple(it.get("fields", []))
    if len(fields) != spec.n_inputs:
        raise ConfigError(f"{name}: fields {len(fields)}개, 계산 함수 {func} 는 {spec.n_inputs}개 필요")
    params = {**(it.get("params") or {}), **(params_override or {})}
    unknown = set(params) - set(spec.defaults)
    if unknown:
        raise ConfigError(f"{name}: 계산 함수 {func} 에 없는 params {sorted(unknown)} (허용 {sorted(spec.defaults)})")
    status = it.get("status", "active")
    if status not in ("active", "na_until_found"):
        raise ConfigError(f"{name}: status 값 오류 {status!r}")
    return IndicatorDef(name=name, indicator=func, block=blk, sub_block=sb, fields=fields,
                        direction=1 if dir_raw == "+" else -1, params=params,
                        asset_classes=tuple(it.get("asset_classes", []) or []), status=status,
                        flags=tuple(it.get("flags", []) or []),
                        weight=weight if weight is not None else _nonneg(it.get("weight", 1.0), f"{name}.weight"))


def _parse_asset(raw: dict) -> AssetSpec:
    for k in ("asset_id", "asset_class"):
        if not raw.get(k):
            raise ConfigError(f"유니버스 항목에 {k} 없음: {raw}")
    refs = {}
    for f, target in (raw.get("refs") or {}).items():
        if not isinstance(target, str) or "." not in target:
            raise ConfigError(f"{raw['asset_id']}: refs.{f} 는 'ASSET.field' 형식이어야 함 ({target!r})")
        a, tf = target.split(".", 1)
        refs[f] = (a, tf)
    tr = dict(raw.get("field_transforms") or {})
    bad = {k: v for k, v in tr.items() if v not in FIELD_TRANSFORMS}
    if bad:
        raise ConfigError(f"{raw['asset_id']}: field_transforms 값 오류 {bad} (허용 {FIELD_TRANSFORMS})")
    return AssetSpec(asset_id=str(raw["asset_id"]), name=str(raw.get("name", raw["asset_id"])),
                     asset_class=str(raw["asset_class"]), currency=str(raw.get("currency", "")),
                     return_field=str(raw.get("return_field", "close")),
                     calendar_field=str(raw["calendar_field"]) if raw.get("calendar_field") else None,
                     refs=refs, field_transforms=tr,
                     overrides=dict(raw.get("overrides") or {}),
                     meta={k: v for k, v in raw.items() if k not in KNOWN_ASSET_KEYS})


SCORING_KEYS = {
    "percentile": {"method", "min_history_years", "rolling_years"},
    "missing": {"daily_ffill_max_bdays", "lowfreq_max_hold_bdays", "lowfreq_threshold_days"},
    "bands": {"extreme", "alert", "contra_alert", "contra_extreme"},
    "regime": {"threshold", "partial_label", "matrix"},
    "staged_entry": {"oversold_min", "vol_ratio_min", "vol_functions"},
    "trend": {"months", "cash_field", "cash_days_per_year"},
    "currency_variant": None, "confirm_trigger": None, "backtest": None, "sub_block_agg": None,
}


def _finite_num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and bool(np.isfinite(v))


def validate_scoring(sc: dict) -> None:
    """scoring.yaml 검증: 알 수 없는 키, 백분위 방식·연수, 결측 규칙, 구간 순서, 국면 매트릭스, 통화 변형,
    분할 진입 표시(staged_entry)·추세 표시(trend), 하위블록 집계(sub_block_agg)."""
    bad = set(sc) - set(SCORING_KEYS)
    if bad:
        raise ConfigError(f"scoring.yaml 알 수 없는 키 {sorted(bad)} (허용 {sorted(SCORING_KEYS)})")
    for sec, allowed in SCORING_KEYS.items():
        if allowed is None or sc.get(sec) is None:
            continue
        if not isinstance(sc[sec], dict):
            raise ConfigError(f"scoring.yaml {sec} 는 매핑이어야 함")
        bad = set(sc[sec]) - allowed
        if bad:
            raise ConfigError(f"scoring.yaml {sec} 에 알 수 없는 키 {sorted(bad)} (허용 {sorted(allowed)})")
    pc = sc.get("percentile", {}) or {}
    if pc.get("method", "expanding") not in PERCENTILE_METHODS:
        raise ConfigError(f"percentile.method 값 오류 {pc.get('method')!r} (허용 {PERCENTILE_METHODS})")
    for k in ("min_history_years", "rolling_years"):
        if k in pc and not (isinstance(pc[k], (int, float)) and pc[k] > 0):
            raise ConfigError(f"percentile.{k} 는 양수 ({pc[k]!r})")
    mc = sc.get("missing", {}) or {}
    for k in ("daily_ffill_max_bdays", "lowfreq_max_hold_bdays", "lowfreq_threshold_days"):
        if k in mc and not (isinstance(mc[k], (int, float)) and np.isfinite(mc[k]) and mc[k] >= 0):
            raise ConfigError(f"missing.{k} 는 0 이상 유한값 ({mc[k]!r})")
    b = {"contra_extreme": 10, "contra_alert": 25, "alert": 75, "extreme": 90, **(sc.get("bands", {}) or {})}
    if not (0 <= b["contra_extreme"] <= b["contra_alert"] < b["alert"] <= b["extreme"] <= 100):
        raise ConfigError(f"bands 순서 오류(0 ≤ contra_extreme ≤ contra_alert < alert ≤ extreme ≤ 100): {b}")
    rg = sc.get("regime", {}) or {}
    if not isinstance(rg.get("threshold", 50), (int, float)):
        raise ConfigError(f"regime.threshold 는 숫자 ({rg.get('threshold')!r})")
    matrix = rg.get("matrix", []) or []
    if not isinstance(matrix, list):
        raise ConfigError("regime.matrix 는 행(dict)의 리스트")
    for i, row in enumerate(matrix):
        if not isinstance(row, dict):
            raise ConfigError(f"regime.matrix[{i}] 는 dict ({row!r})")
        bad = set(row) - REGIME_KEYS
        if bad or not isinstance(row.get("label"), str):
            raise ConfigError(f"regime.matrix[{i}]: 키는 o·v·f·label, label 은 문자열 ({row})")
        for k in ("o", "v", "f"):
            if row.get(k) not in (None, "high", "low"):
                raise ConfigError(f"regime.matrix[{i}].{k} 는 high·low·null ({row.get(k)!r})")
    if sc.get("currency_variant", "both") not in CURRENCY_VARIANTS:
        raise ConfigError(f"currency_variant 값 오류 {sc.get('currency_variant')!r} (허용 {CURRENCY_VARIANTS})")
    for sec in ("staged_entry", "trend"):   # 표시 전용 섹션: 있으면 키를 모두 적어야 한다(엔진에 숨은 기본값 없음)
        if sc.get(sec) and set(sc[sec]) != SCORING_KEYS[sec]:
            raise ConfigError(f"scoring.yaml {sec} 에 빠진 키 {sorted(SCORING_KEYS[sec] - set(sc[sec]))}")
    se = sc.get("staged_entry", {}) or {}
    if "oversold_min" in se and not (_finite_num(se["oversold_min"]) and 0 <= se["oversold_min"] <= 100):
        raise ConfigError(f"staged_entry.oversold_min 은 0~100 숫자 ({se['oversold_min']!r})")
    if "vol_ratio_min" in se and not (_finite_num(se["vol_ratio_min"]) and se["vol_ratio_min"] > 0):
        raise ConfigError(f"staged_entry.vol_ratio_min 은 양의 유한값 ({se['vol_ratio_min']!r})")
    if "vol_functions" in se:
        vf = se["vol_functions"]
        if not (isinstance(vf, list) and vf and all(isinstance(x, str) for x in vf)):
            raise ConfigError(f"staged_entry.vol_functions 는 계산 함수 이름의 비어 있지 않은 리스트 ({vf!r})")
        for x in vf:
            try:
                get_func(x)
            except KeyError as e:
                raise ConfigError(f"staged_entry.vol_functions: {e.args[0]}") from None
    tr = sc.get("trend", {}) or {}
    if "months" in tr and not (isinstance(tr["months"], int) and not isinstance(tr["months"], bool) and tr["months"] > 0):
        raise ConfigError(f"trend.months 는 양의 정수 ({tr['months']!r})")
    if "cash_field" in tr and not (isinstance(tr["cash_field"], str) and tr["cash_field"]):
        raise ConfigError(f"trend.cash_field 는 필드 이름 문자열 ({tr['cash_field']!r})")
    if "cash_days_per_year" in tr and not (_finite_num(tr["cash_days_per_year"]) and tr["cash_days_per_year"] > 0):
        raise ConfigError(f"trend.cash_days_per_year 는 양의 유한값 ({tr['cash_days_per_year']!r})")
    agg = sc.get("sub_block_agg")
    if agg is not None and not isinstance(agg, dict):
        raise ConfigError("sub_block_agg 는 {'block.sub_block': mean | min} 매핑")
    for k, v in (agg or {}).items():
        blk, _, sb = str(k).partition(".")
        if (not isinstance(k, str) or blk not in BLOCKS or not sb or "." in sb
                or any(ch.isspace() for ch in k)):
            raise ConfigError(f"sub_block_agg 키는 공백 없는 'block.sub_block'(점 하나, block ∈ {BLOCKS}) ({k!r})")
        if v not in SUB_BLOCK_AGGS:
            raise ConfigError(f"sub_block_agg.{k} 값 오류 {v!r} (허용 {SUB_BLOCK_AGGS})")


def build_config(universe: list[dict], profiles: dict[str, dict], scoring: dict, root: Path | None = None,
                 strict_agg_keys: bool = False) -> Config:
    """파싱된 dict 들로 Config 를 만들고 검증한다(파일 없이 테스트·호스트에서 쓸 때).

    strict_agg_keys: True 면 어느 프로파일·overrides.add 에도 없는 sub_block_agg 키를 ConfigError 로 거부한다.
        load_config(전 프로파일을 읽는 실제 경로)는 True 로 부른다. 기본값 False(경고만)는 공유 scoring.yaml 을
        일부 프로파일과 함께 쓰는 dict 경로(테스트 픽스처 등)용이다 — 전 프로파일을 dict 로 넘기면 True 를 준다."""
    validate_scoring(scoring)
    assets = [_parse_asset(copy.deepcopy(a)) for a in universe]
    ids = [a.asset_id for a in assets]
    dup = {i for i in ids if ids.count(i) > 1}
    if dup:
        raise ConfigError(f"asset_id 중복: {sorted(dup)}")
    for name, p in profiles.items():
        blocks = p.get("blocks") or {}
        bad = set(blocks) - set(BLOCKS)
        if bad:
            raise ConfigError(f"프로파일 {name}: 알 수 없는 블록 {sorted(bad)} (허용 {BLOCKS})")
        names = [it.get("name") for subs in blocks.values() for items in subs.values() for it in items]
        dupn = {n for n in names if names.count(n) > 1}
        if dupn:
            raise ConfigError(f"프로파일 {name}: 지표 이름 중복 {sorted(dupn)}")
    # sub_block_agg 키가 어느 프로파일·overrides.add 에도 없으면: strict 면 오류, 아니면 경고. scoring.yaml 은 모든
    # 자산군이 공유하므로 일부 프로파일만 넘기는 dict 설정에서는 키가 비는 것이 정상이다.
    known = {f"{b}.{sb}" for p in profiles.values() for b, subs in (p.get("blocks") or {}).items() for sb in subs}
    known |= {k for a in assets if isinstance((a.overrides or {}).get("add"), dict) for k in a.overrides["add"]}
    unknown_agg = sorted(set(scoring.get("sub_block_agg") or {}) - known)
    if unknown_agg and strict_agg_keys:
        raise ConfigError(f"sub_block_agg 에 어느 프로파일에도 없는 하위블록 {unknown_agg}")
    for k in unknown_agg:
        log.warning("sub_block_agg.%s: 이 설정의 어느 프로파일에도 없는 하위블록(오타인지 확인)", k)
    cfg = Config(assets, profiles, scoring, root)
    for a in assets:
        for f, (ra, rf) in a.refs.items():
            if ra not in ids:
                raise ConfigError(f"{a.asset_id}: refs.{f} 가 유니버스에 없는 자산 {ra} 를 가리킴")
        cfg.indicator_defs(a)  # 프로파일·overrides 검증
    return cfg


def load_config(path: str | Path) -> Config:
    """config 디렉터리(universe.yaml, scoring.yaml, profiles/*.yaml)를 읽는다."""
    root = Path(path)
    try:
        universe = yaml.safe_load((root / "universe.yaml").read_text(encoding="utf-8")) or []
        scoring = yaml.safe_load((root / "scoring.yaml").read_text(encoding="utf-8")) or {}
    except FileNotFoundError as e:
        raise ConfigError(f"설정 파일 없음: {e.filename}") from None
    profiles = {}
    for p in sorted((root / "profiles").glob("*.yaml")):
        d = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        cls = d.get("asset_class", p.stem)
        if cls in profiles:
            raise ConfigError(f"자산군 프로파일 중복: {cls}")
        profiles[cls] = d
    return build_config(universe, profiles, scoring, root, strict_agg_keys=True)
