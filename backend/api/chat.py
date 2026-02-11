from fastapi import APIRouter, Depends
from backend.core.logging import get_logger
from backend.api.deps import require_api_key

_log = get_logger("api.chat")

router = APIRouter(tags=["Chat"], dependencies=[Depends(require_api_key)])
