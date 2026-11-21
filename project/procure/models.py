"""Typed shared state ("case file") and structured agent messages."""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class Alert(BaseModel):
    sku: str
    kind: str  # low_stock | expiry | both
    on_hand: int
    reorder_point: int
    avg_daily: float
    expiring_qty: int = 0
    days_to_expiry: Optional[int] = None
    evidence: str = ""


class Forecast(BaseModel):
    sku: str
    daily: list[float]          # expected demand per day for the next days
    sigma_daily: float
    confidence: float           # 0..1
    method: str
    flags: list[str] = Field(default_factory=list)

    def mean(self, h: int) -> float:
        return float(sum(self.daily[:h]))

    def sigma(self, h: int) -> float:
        return self.sigma_daily * h ** 0.5


class SupplierOption(BaseModel):
    supplier_id: int
    name: str
    unit_price: float
    moq: int
    lead_time: int
    reliability: float
    score: float
    rationale: str = ""


class SupplierRanking(BaseModel):
    sku: str
    options: list[SupplierOption]
    flagged_notes: list[str] = Field(default_factory=list)


class DraftPO(BaseModel):
    sku: str
    supplier_id: int
    supplier_name: str
    qty: int
    unit_price: float
    rationale: str = ""
    revision: int = 0
    action: str = "order"       # order | markdown (do not reorder)

    @property
    def total(self) -> float:
        return round(self.qty * self.unit_price, 2)


class Failure(BaseModel):
    code: str                   # BUDGET MOQ ROLE SANITY PRICE STOCK
    message: str


class Validation(BaseModel):
    passed: bool
    failures: list[Failure] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class Message(BaseModel):
    task_id: str
    author: str
    inputs: dict[str, Any] = Field(default_factory=dict)
    output: dict[str, Any] = Field(default_factory=dict)
    confidence: Optional[float] = None
    evidence: list[str] = Field(default_factory=list)


class CaseFile(BaseModel):
    task_id: str
    sku: str
    requester: str
    status: str = "open"        # no_action | pending_approval | escalated | rejected | created | failed
    alert: Optional[Alert] = None
    forecast: Optional[Forecast] = None
    ranking: Optional[SupplierRanking] = None
    draft: Optional[DraftPO] = None
    validation: Optional[Validation] = None
    po_id: Optional[int] = None
    review_flag: bool = False
    used_fallback: bool = False
    notes: list[str] = Field(default_factory=list)
