# axnmihn Project Rules

- **Stack**: FastAPI backend, SQLite database, MCP server
- **Project path**: `~/projects/axnmihn`
- **axel-chat** (CLI): `~/projects/axel-chat` (Rust, fork of sigoden/aichat)
- **Python venv**: `~/projects-env/` (Python 3.12)
- **Service management**: systemd user units (`~/.config/systemd/user/`)
- **MCP servers**: axel-mcp, context7, markitdown

## Memory Policy

- This project has its own memory system (axel-mcp: ChromaDB + GraphRAG)
- Prefer axel-mcp memory tools (`store_memory`, `retrieve_context`) over Claude Code auto memory
- Do NOT duplicate information between both memory systems
