from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.responses import StreamingResponse, Response
import ast
import json
from agent.dependency_graph import run_dependency_agent
from langchain_core.messages import HumanMessage

from .graph import build_supervisor_graph, run_supervisor
from .mcp_client import get_mcp_tools, get_all_mcp_tools
from shared.models import (
    ChatRequest,
    ChatResponse,
    DependencyManifestRequest,
    generate_session_id,
    RedisSessionStore,
)
from shared.dependency_scan import canonicalize_manifest_type, supported_manifest_types
from .report import generate_session_report_pdf


app = FastAPI(title="Supervisor API")

# Build graph without checkpointer for now
SUPERVISOR_GRAPH = build_supervisor_graph()


# Load tools once
@app.on_event("startup")
async def startup():
    try:
        recon_tools, vuln_tools = await get_mcp_tools()
        all_tools = await get_all_mcp_tools()

        print("\nSupervisor loaded tools")
        print("Recon:", [t.name for t in recon_tools])
        print("Vulnerability:", [t.name for t in vuln_tools])
        print("All MCP tools:", [t.name for t in all_tools])
        print()
    except Exception as e:
        # Don't fail supervisor startup if one MCP server is down.
        print(f"\nSupervisor startup warning: MCP tools not fully available ({e})\n")


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    session_id = req.session_id or generate_session_id()
    result = await run_supervisor(req.message, session_id, SUPERVISOR_GRAPH)
    return ChatResponse(
        output=result["output"],
        agent_used=result["agent_used"],
        session_id=session_id,
        tool_calls=result["tool_calls"]
    )


@app.post("/chat/stream")
async def chat_stream(req: ChatRequest):
    session_id = req.session_id or generate_session_id()

    async def generate_response():
        # Yield start event
        yield f"data: {json.dumps({'type': 'start', 'session_id': session_id})}\n\n"

        result = await run_supervisor(req.message, session_id, SUPERVISOR_GRAPH)

        # Yield tool calls
        for tool in result["tool_calls"]:
            yield f"data: {json.dumps({'type': 'tool_call', 'data': tool})}\n\n"

        # Yield output
        yield f"data: {json.dumps({'type': 'output', 'data': result['output']})}\n\n"

        # Yield final output node
        yield f"data: {json.dumps({'type': 'final_output', 'agent_used': result['agent_used'], 'session_id': session_id})}\n\n"

        # Yield end
        yield f"data: {json.dumps({'type': 'end'})}\n\n"

    return StreamingResponse(generate_response(), media_type="text/event-stream")


@app.get("/chat/history/{session_id}")
async def get_chat_history(session_id: str):
    session_store = RedisSessionStore()
    history = session_store.get_session_history(session_id)
    return {"history": history}


@app.get("/chat/report/{session_id}")
async def download_session_report(session_id: str):
    """Return a PDF report for the session (history + artifacts)."""
    session_store = RedisSessionStore()
    history = session_store.get_session_history(session_id)
    artifacts = session_store.get_session_artifacts(session_id)

    if not history and not artifacts:
        raise HTTPException(status_code=404, detail="Session not found or no data available")

    try:
        pdf_bytes = generate_session_report_pdf(session_id, history, artifacts)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate PDF: {e}")

    headers = {
        "Content-Disposition": f"attachment; filename=session_report_{session_id}.pdf"
    }
    return Response(content=pdf_bytes, media_type="application/pdf", headers=headers)


MANIFEST_TYPE_HINT = ", ".join(supported_manifest_types())


async def _run_manifest_scan(content: str, manifest_type: str) -> dict:
    dependency_tools, _ = await get_mcp_tools()
    if not dependency_tools:
        raise HTTPException(status_code=503, detail="Dependency scanning tools are unavailable")

    message = HumanMessage(content=f"Scan the following {manifest_type} dependency manifest for vulnerabilities:\n{content}")
    result = await run_dependency_agent([message], dependency_tools)
    return {
        "summary": result.get("output", ""),
        "scan": _parse_dependency_tool_output(result.get("tool_calls", [])),
        "tool_calls": result.get("tool_calls", []),
    }


def _parse_dependency_tool_output(tool_calls: list[dict]) -> dict | None:
    for call in tool_calls:
        if call.get("tool_name") == "tool_scan_dependency_text":
            raw = call.get("tool_output")
            if raw is None:
                return None
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                try:
                    return ast.literal_eval(raw)
                except Exception:
                    return raw
    return None


@app.post("/dependency/manifest")
async def scan_dependency_manifest(req: DependencyManifestRequest):
    normalized = canonicalize_manifest_type(req.file_type, None)
    if not normalized:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported manifest type. Supported values: {MANIFEST_TYPE_HINT}",
        )
    if not req.content.strip():
        raise HTTPException(status_code=400, detail="Manifest content must not be empty")
    return await _run_manifest_scan(req.content.strip(), normalized)


@app.post("/dependency/manifest/upload")
async def upload_dependency_manifest(
    file: UploadFile = File(...),
    file_type: str | None = Form(None),
):
    normalized = canonicalize_manifest_type(file_type, file.filename)
    if not normalized:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported manifest type. Supported values: {MANIFEST_TYPE_HINT}",
        )
    content = await file.read()
    text = content.decode("utf-8", errors="replace").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")
    return await _run_manifest_scan(text, normalized)
