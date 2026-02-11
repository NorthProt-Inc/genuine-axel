from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Dict, Any
from backend.core.logging import get_logger
from backend.protocols.mcp.server import MCPServer, MCPRequest
from backend.api.deps import get_state, require_api_key

_log = get_logger("api.mcp")

router = APIRouter(tags=["MCP"], dependencies=[Depends(require_api_key)])

def _get_mcp_server() -> MCPServer:

    state = get_state()
    if state.mcp_server is None:
        state.mcp_server = MCPServer(
            memory_manager=state.memory_manager,
            identity_manager=state.identity_manager,
            graph_rag=state.graph_rag,
        )
    return state.mcp_server

@router.get("/mcp/status")
async def get_mcp_status():

    _log.debug("REQ recv", path="/mcp/status")
    mcp = _get_mcp_server()
    result = {
        "status": "running",
        "server_info": mcp.SERVER_INFO,
        "resources": len(mcp.resources),
        "tools": len(mcp.tools),
        "prompts": len(mcp.prompts),
    }
    _log.info("RES sent", status=200, tools=len(mcp.tools), resources=len(mcp.resources))
    return result

@router.get("/mcp/manifest")
async def get_mcp_manifest():

    _log.debug("REQ recv", path="/mcp/manifest")
    mcp = _get_mcp_server()
    manifest = mcp.get_manifest()
    _log.info("RES sent", status=200, manifest_keys=list(manifest.keys()) if isinstance(manifest, dict) else "unknown")
    return manifest

class MCPExecuteRequest(BaseModel):

    id: Any
    method: str
    params: Dict[str, Any] = {}

@router.post("/mcp/execute")
async def execute_mcp(request: MCPExecuteRequest):

    _log.info("REQ recv", path="/mcp/execute", method=request.method, req_id=request.id)
    mcp = _get_mcp_server()
    try:
        mcp_request = MCPRequest(
            id=str(request.id),
            method=request.method,
            params=request.params or {},
        )
        response = await mcp.handle_request(mcp_request)
        status_code = 200 if response.error is None else 400
        _log.info("RES sent", status=status_code, method=request.method, has_error=response.error is not None)
        return JSONResponse(
            status_code=status_code,
            content={
                "id": response.id,
                "result": response.result,
                "error": response.error,
            },
        )
    except Exception as e:
        _log.error("MCP execute error", error=str(e))
        raise HTTPException(status_code=500, detail="MCP execution failed")
