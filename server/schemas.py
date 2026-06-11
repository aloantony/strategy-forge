"""server/schemas.py — DTOs de la API (Pydantic)."""

from pydantic import BaseModel, Field


class BacktestRunRequest(BaseModel):
    strategy_key: str
    symbol: str
    start_date: str = Field(description="YYYY-MM-DD")
    end_date: str = Field(description="YYYY-MM-DD")
    initial_balance: float = 10_000.0
    data_source: str = "mt5"


class AccountResponse(BaseModel):
    balance: float
    equity: float
    margin: float
    free_margin: float
    margin_level: float
    currency: str


class StrategyItem(BaseModel):
    key: str
    label: str
    module: str
    has_config: bool
    enabled: bool
    timeframe: str = ""
    magic_number: int = 0
    has_params: bool = False
    error: str | None = None


class BuilderSaveResponse(BaseModel):
    key: str
    name: str
    display_name: str
    magic_number: int
    timeframe: str = ""
    schema_version: int = 1
    py_path: str


class BuilderValidateResponse(BaseModel):
    valid: bool
    errors: list[str] = []
