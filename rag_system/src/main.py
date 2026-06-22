"""
Fireworks AI Agentic RAG - Main FastAPI Application
"""
import os
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

from agent import RAGAgent

app = FastAPI(title="Fireworks Agentic RAG", version="1.0.0")

# Mount static files for UI
static_dir = Path(__file__).parent.parent / "static"
static_dir.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

# Initialize agent
DATA_DIR = Path(os.getenv("DATA_DIR", Path(__file__).parent.parent / "data"))
agent = RAGAgent(data_dir=DATA_DIR)


@app.on_event("shutdown")
def shutdown_event() -> None:
    """Clean up the agent's HTTP clients on shutdown."""
    try:
        agent.close()
    except Exception:
        pass


class ChatRequest(BaseModel):
    question: str


class ChatResponse(BaseModel):
    answer: str
    sources: list[dict] = []
    routing: str = ""
    tool_calls: list[dict] = []
    diagnostics: dict = {}


@app.get("/", response_class=HTMLResponse)
async def root():
    """Serve the chat UI."""
    html_file = static_dir / "index.html"
    if html_file.exists():
        return HTMLResponse(
            content=html_file.read_text(encoding="utf-8"),
            media_type="text/html; charset=utf-8",
        )
    return HTMLResponse(content="<h1>Fireworks Agentic RAG</h1><p>POST to /api/chat</p>")


@app.post("/api/chat")
async def chat(request: ChatRequest):
    """Main chat endpoint. Returns JSON with answer field."""
    if not request.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty")

    try:
        result = agent.answer(request.question)
        return {
            "answer": result["answer"],
            "sources": result.get("sources", []),
            "routing": result.get("routing", ""),
            "tool_calls": result.get("tool_calls", []),
            "diagnostics": result.get("diagnostics", {}),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
