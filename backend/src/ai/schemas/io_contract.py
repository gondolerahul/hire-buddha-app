"""schemas/io_contract.py — IO schema contract and observability config."""
from __future__ import annotations

from typing import Any, Dict

from pydantic import BaseModel

__all__ = [
    "IOContract",
    "Observability",
]


class IOContract(BaseModel):
    input_schema: Dict[str, Any] = {"type": "object", "properties": {}}
    output_schema: Dict[str, Any] = {"type": "object", "properties": {}}


class Observability(BaseModel):
    log_level: str = "INFO"
    log_thoughts: bool = True
    track_cost: bool = True
