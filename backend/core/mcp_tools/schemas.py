"""
Pydantic schemas for MCP tool input validation.

Provides type-safe validation with clear error messages.
"""

import re
from enum import Enum
from typing import Literal, Optional
from pydantic import BaseModel, Field, field_validator


# === Enums ===

class LightAction(str, Enum):
    """Light control actions."""
    TURN_ON = "turn_on"
    TURN_OFF = "turn_off"


class DeviceAction(str, Enum):
    """Device control actions."""
    TURN_ON = "turn_on"
    TURN_OFF = "turn_off"


class MemoryCategory(str, Enum):
    """Memory storage categories."""
    FACT = "fact"
    PREFERENCE = "preference"
    CONVERSATION = "conversation"
    INSIGHT = "insight"


class SearchDepth(str, Enum):
    """Search depth for Tavily."""
    BASIC = "basic"
    ADVANCED = "advanced"


# === Home Assistant Schemas ===

class HassControlLightInput(BaseModel):
    """Input schema for hass_control_light tool."""

    entity_id: str = Field(
        default="all",
        description="Light entity ID (e.g., 'light.living_room') or 'all'"
    )
    action: LightAction = Field(
        description="Action to perform"
    )
    brightness: Optional[int] = Field(
        default=None,
        ge=0,
        le=100,
        description="Brightness percentage (0-100)"
    )
    color: Optional[str] = Field(
        default=None,
        description="Color: hex (#FF0000), name (red), or hsl(240,100,50)"
    )

    @field_validator("entity_id")
    @classmethod
    def validate_entity_id(cls, v: str) -> str:
        if v != "all" and "." not in v:
            raise ValueError("entity_id must be 'all' or format 'domain.entity'")
        return v

    @field_validator("color")
    @classmethod
    def validate_color(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        v = v.strip()
        # Allow: hex, named colors, hsl
        if v.startswith("#"):
            if not re.match(r"^#[0-9A-Fa-f]{6}$", v):
                raise ValueError("Invalid hex color format. Use #RRGGBB")
        elif v.startswith("hsl("):
            if not re.match(r"^hsl\(\d+,\d+,\d+\)$", v):
                raise ValueError("Invalid hsl format. Use hsl(h,s,l)")
        # Named colors are allowed as-is
        return v


class HassControlDeviceInput(BaseModel):
    """Input schema for hass_control_device tool."""

    entity_id: str = Field(
        description="Device entity ID (e.g., 'fan.device_name', use hass_list_entities to discover)"
    )
    action: DeviceAction = Field(
        description="Action to perform"
    )

    @field_validator("entity_id")
    @classmethod
    def validate_entity_id(cls, v: str) -> str:
        if "." not in v:
            raise ValueError("entity_id must be format 'domain.entity'")
        return v


class HassReadSensorInput(BaseModel):
    """Input schema for hass_read_sensor tool."""

    query: str = Field(
        description="Sensor alias ('battery', 'printer', 'weather') or full entity_id"
    )


# === Memory Schemas ===

class StoreMemoryInput(BaseModel):
    """Input schema for store_memory tool."""

    content: str = Field(
        min_length=1,
        max_length=10000,
        description="Content to store in memory"
    )
    category: MemoryCategory = Field(
        default=MemoryCategory.CONVERSATION,
        description="Memory category"
    )
    importance: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Importance score 0.0-1.0"
    )


class RetrieveContextInput(BaseModel):
    """Input schema for retrieve_context tool."""

    query: str = Field(
        min_length=1,
        max_length=500,
        description="Search query"
    )
    max_results: int = Field(
        default=10,
        ge=1,
        le=25,
        description="Maximum results to return"
    )


class AddMemoryInput(BaseModel):
    """Input schema for add_memory tool."""

    content: str = Field(
        min_length=1,
        description="Content of the memory"
    )
    category: Literal["observation", "fact", "code"] = Field(
        default="observation",
        description="Type of memory"
    )


# === Research Schemas ===

class WebSearchInput(BaseModel):
    """Input schema for web_search tool."""

    query: str = Field(
        min_length=2,
        max_length=500,
        description="Search query"
    )
    num_results: int = Field(
        default=5,
        ge=1,
        le=10,
        description="Number of results"
    )


class VisitWebpageInput(BaseModel):
    """Input schema for visit_webpage tool."""

    url: str = Field(
        description="Full URL to visit (must start with http:// or https://)"
    )

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        v = v.strip()
        if not v.startswith(("http://", "https://")):
            raise ValueError("URL must start with http:// or https://")
        return v


class DeepResearchInput(BaseModel):
    """Input schema for deep_research tool."""

    query: str = Field(
        min_length=3,
        max_length=500,
        description="Research query - be specific and detailed"
    )


class TavilySearchInput(BaseModel):
    """Input schema for tavily_search tool."""

    query: str = Field(
        min_length=2,
        description="Search query"
    )
    max_results: int = Field(
        default=5,
        ge=1,
        le=10,
        description="Number of results"
    )
    search_depth: SearchDepth = Field(
        default=SearchDepth.BASIC,
        description="basic=fast, advanced=thorough"
    )


class GoogleDeepResearchInput(BaseModel):
    """Input schema for google_deep_research tool."""

    query: str = Field(
        min_length=5,
        description="Research query - be specific and detailed"
    )
    depth: int = Field(
        default=3,
        ge=1,
        le=5,
        description="Research depth 1-5"
    )
    async_mode: bool = Field(
        default=True,
        description="Run in background"
    )


# === System Schemas ===

class RunCommandInput(BaseModel):
    """Input schema for run_command tool."""

    command: str = Field(
        min_length=1,
        description="Bash command to execute"
    )
    cwd: Optional[str] = Field(
        default=None,
        description="Working directory"
    )
    timeout: int = Field(
        default=180,
        ge=1,
        le=600,
        description="Timeout in seconds"
    )


class SearchCodebaseInput(BaseModel):
    """Input schema for search_codebase tool."""

    keyword: str = Field(
        min_length=1,
        description="String to search for"
    )
    file_pattern: str = Field(
        default="*.py",
        description="File pattern to search"
    )
    case_sensitive: bool = Field(
        default=False,
        description="Case-sensitive search"
    )
    max_results: int = Field(
        default=50,
        ge=1,
        le=100,
        description="Maximum results"
    )


class ReadSystemLogsInput(BaseModel):
    """Input schema for read_system_logs tool."""

    log_file: str = Field(
        default="backend.log",
        description="Log file to read"
    )
    lines: int = Field(
        default=50,
        ge=1,
        le=1000,
        description="Number of lines"
    )
    filter_keyword: Optional[str] = Field(
        default=None,
        description="Filter keyword"
    )


# === Delegation Schemas ===

class DelegateToOpusInput(BaseModel):
    """Input schema for delegate_to_opus tool."""

    instruction: str = Field(
        min_length=10,
        description="Clear, detailed instruction for the coding task"
    )
    file_paths: Optional[str] = Field(
        default=None,
        description="Comma-separated file paths"
    )
    model: Literal["opus", "sonnet", "haiku"] = Field(
        default="opus",
        description="Model to use"
    )

