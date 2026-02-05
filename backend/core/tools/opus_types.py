"""Common data types for Opus integration."""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class OpusResult:
    """Result from Opus CLI execution."""
    success: bool
    output: str
    error: Optional[str] = None
    exit_code: int = 0
    files_included: List[str] = field(default_factory=list)
    execution_time: float = 0.0


@dataclass
class DelegationResult:
    """Result from Opus delegation task."""
    success: bool
    response: str
    files_included: List[str] = field(default_factory=list)
    execution_time: float = 0.0
    error: Optional[str] = None


@dataclass
class OpusHealthStatus:
    """Opus service health status."""
    available: bool
    message: str
    version: Optional[str] = None
    details: Optional[Dict[str, Any]] = None
