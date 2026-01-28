"""Opus 관련 공통 데이터 타입."""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class OpusResult:
    """Opus CLI 실행 결과."""
    success: bool
    output: str
    error: Optional[str] = None
    exit_code: int = 0
    files_included: List[str] = field(default_factory=list)
    execution_time: float = 0.0


@dataclass
class DelegationResult:
    """Opus 위임 작업 결과."""
    success: bool
    response: str
    files_included: List[str] = field(default_factory=list)
    execution_time: float = 0.0
    error: Optional[str] = None


@dataclass
class OpusHealthStatus:
    """Opus 서비스 상태."""
    available: bool
    message: str
    version: Optional[str] = None
    details: Optional[Dict[str, Any]] = None
