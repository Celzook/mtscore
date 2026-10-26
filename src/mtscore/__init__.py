"""mtscore — 자산 독립적 멀티에셋 마켓타이밍 스코어링 엔진."""
from .api import ENGINE_VERSION, SCHEMA_VERSION, ScoreResult, ScoringEngine
from .config import AssetSpec, Config, ConfigError, build_config, load_config
from .data.schema import PANEL_COLUMNS, SchemaError, validate_panel

__version__ = ENGINE_VERSION
__all__ = ["ScoringEngine", "ScoreResult", "load_config", "build_config", "Config", "AssetSpec", "ConfigError",
           "validate_panel", "SchemaError", "PANEL_COLUMNS", "SCHEMA_VERSION", "ENGINE_VERSION"]
