"""지표 레지스트리.

두 층으로 나눈다.
- 계산 함수(`@register`): 자산·블록과 무관한 순수 함수. `func(*series, **params) -> pd.Series`.
  예: disparity(x, window). 등록 메타데이터는 이름·입력 개수·기본 파라미터·설명.
- 지표 정의(`IndicatorDef`): 프로파일 YAML 의 한 항목. 계산 함수 + block·sub_block·fields·direction·
  asset_classes·params·status·flags. 프롬프트 §5-2 의 "지표 등록 메타데이터"는 이 객체가 갖는다.
같은 계산 함수를 파라미터만 바꿔 여러 지표로 쓸 수 있다(disparity_20/60/200).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import pandas as pd

IndicatorFunc = Callable[..., pd.Series]


@dataclass(frozen=True)
class FuncSpec:
    name: str
    func: IndicatorFunc
    n_inputs: int
    defaults: dict
    doc: str


_REGISTRY: dict[str, FuncSpec] = {}


def register(name: str, n_inputs: int = 1, **defaults) -> Callable[[IndicatorFunc], IndicatorFunc]:
    """계산 함수를 레지스트리에 등록하는 데코레이터.

    Args:
        name: 프로파일의 `indicator` 키로 참조할 이름.
        n_inputs: 받는 시계열 개수(프로파일 `fields` 길이와 같아야 한다).
        **defaults: 기본 파라미터(프로파일 `params` 가 덮어쓴다).
    """

    def deco(func: IndicatorFunc) -> IndicatorFunc:
        if name in _REGISTRY:
            raise ValueError(f"계산 함수 이름 중복: {name}")
        _REGISTRY[name] = FuncSpec(name, func, n_inputs, dict(defaults), (func.__doc__ or "").strip())
        return func

    return deco


def get_func(name: str) -> FuncSpec:
    """등록된 계산 함수. 없으면 KeyError(등록된 이름 목록 포함)."""
    try:
        return _REGISTRY[name]
    except KeyError:
        raise KeyError(f"등록되지 않은 계산 함수: {name} (등록: {sorted(_REGISTRY)})") from None


def registered() -> dict[str, FuncSpec]:
    """등록된 계산 함수 전체(복사본)."""
    return dict(_REGISTRY)


@dataclass(frozen=True)
class IndicatorDef:
    """프로파일의 지표 한 항목."""

    name: str
    indicator: str
    block: str
    sub_block: str
    fields: tuple[str, ...]
    direction: int  # +1: 클수록 매수 매력 / -1: 작을수록 매수 매력
    params: dict = field(default_factory=dict)
    asset_classes: tuple[str, ...] = ()
    status: str = "active"  # active | na_until_found
    flags: tuple[str, ...] = ()
    weight: float = 1.0

    @property
    def func(self) -> FuncSpec:
        return get_func(self.indicator)

    def compute(self, series: list[pd.Series]) -> pd.Series:
        """입력 시계열(fields 순서)로 원시 지표값을 계산한다."""
        spec = self.func
        if len(series) != spec.n_inputs:
            raise ValueError(f"{self.name}: 입력 {len(series)}개, 계산 함수 {spec.name} 는 {spec.n_inputs}개 필요")
        out = spec.func(*series, **{**spec.defaults, **self.params})
        return out.rename(self.name)
