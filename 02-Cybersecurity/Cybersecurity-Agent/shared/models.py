from typing import Any, Union, Dict, List
from pydantic import BaseModel, Field
import uuid
from shared.config import settings
import redis
import json
import time


# ── Inbound requests ────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    """Request body for the Supervisor /chat endpoint."""
    message: str = Field(..., description="User's natural language query")
    session_id: str | None = Field(default=None, description="Session identifier for multi-turn")


class InvokeRequest(BaseModel):
    """
    Request body for each Agent /invoke endpoint.

    Supports:
    - str (legacy)
    - structured payload from Supervisor
    """
    message: Union[str, Dict[str, Any]] = Field(
        ...,
        description="Task message or structured context from supervisor"
    )


class DependencyManifestRequest(BaseModel):
    """Payload for submitting a dependency manifest for scanning."""
    file_type: str | None = Field(
        default=None,
        description="Optional normalized manifest type (e.g., package.json, requirements.txt)",
    )
    content: str = Field(..., description="Raw dependency manifest text")


# ── Outbound responses ──────────────────────────────────────────────────────

class ToolCallLog(BaseModel):
    """A single tool call made during agent execution."""
    tool_name: str
    tool_input: Dict[str, Any]
    tool_output: str


class InvokeResponse(BaseModel):
    """Response from each Agent /invoke endpoint."""
    output: str
    tool_calls: List[ToolCallLog] = Field(default_factory=list)


class ChatResponse(BaseModel):
    """Response from the Supervisor /chat endpoint."""
    output: str
    agent_used: str
    session_id: str
    tool_calls: List[ToolCallLog] = Field(default_factory=list)


# ── Health ──────────────────────────────────────────────────────────────────

class HealthResponse(BaseModel):
    status: str = "ok"
    service: str = ""


# ── Session Management ──────────────────────────────────────────────────────

def generate_session_id() -> str:
    """Generate a unique session ID."""
    return str(uuid.uuid4())


class RedisSessionStore:
    """Redis-based session store for conversation memory."""

    def __init__(self):
        self.redis = redis.Redis(
            host=settings.REDIS_HOST,
            port=settings.REDIS_PORT,
            db=settings.REDIS_DB,
            decode_responses=True
        )

    def get_session_history(self, session_id: str) -> List[Dict[str, Any]]:
        """Retrieve conversation history for a session."""
        try:
            history_json = self.redis.get(f"session:{session_id}:history")
            if history_json:
                return json.loads(history_json)
            return []
        except Exception:
            return []

    def save_session_history(self, session_id: str, history: List[Dict[str, Any]]):
        """Save conversation history for a session."""
        try:
            self.redis.set(
                f"session:{session_id}:history",
                json.dumps(history),
                ex=settings.REDIS_SESSION_TTL_SECONDS,
            )
        except Exception:
            return

    def get_session_artifacts(self, session_id: str) -> List[Dict[str, Any]]:
        """
        Retrieve structured artifacts for a session (tool calls, findings, risk summaries).
        """
        try:
            artifacts_json = self.redis.get(f"session:{session_id}:artifacts")
            if artifacts_json:
                return json.loads(artifacts_json)
            return []
        except Exception:
            return []

    def append_session_artifact(self, session_id: str, artifact: Dict[str, Any]):
        """
        Append a structured artifact entry to a session.
        """
        try:
            artifacts = self.get_session_artifacts(session_id)
            entry = dict(artifact)
            # Blueprint-compatible timestamp key.
            if "timestamp" not in entry:
                entry["timestamp"] = int(time.time())
            artifacts.append(entry)
            self.redis.set(
                f"session:{session_id}:artifacts",
                json.dumps(artifacts),
                ex=settings.REDIS_SESSION_TTL_SECONDS,
            )
        except Exception:
            return

    def get_session_settings(self, session_id: str) -> Dict[str, Any]:
        """Retrieve settings for a session."""
        try:
            settings_json = self.redis.get(f"session:{session_id}:settings")
            if settings_json:
                return json.loads(settings_json)
            return {}
        except Exception:
            return {}

    def save_session_settings(self, session_id: str, session_settings: Dict[str, Any]):
        """Save settings for a session."""
        try:
            self.redis.set(
                f"session:{session_id}:settings",
                json.dumps(session_settings),
                ex=settings.REDIS_SESSION_TTL_SECONDS,
            )
        except Exception:
            return

    def delete_session(self, session_id: str):
        """Delete a session and its data."""
        try:
            self.redis.delete(f"session:{session_id}:history")
            self.redis.delete(f"session:{session_id}:artifacts")
            self.redis.delete(f"session:{session_id}:settings")
        except Exception:
            return


# ── Settings ───────────────────────────────────────────────────────

class SettingsRequest(BaseModel):
    """Request body for saving session settings."""
    openai_model: str = Field(..., description="OpenAI model to use")
    openai_api_key: str = Field(..., description="OpenAI API key")
