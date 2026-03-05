import json
import os
import time
from typing import Any

from langchain_openai import ChatOpenAI

try:
    import redis
except Exception:  # pragma: no cover
    redis = None


class RedisConversationStore:
    def __init__(
        self,
        client: Any | None,
        *,
        namespace: str = "proptech",
        text_limit: int = 20000,
        summary_keep_turns: int = 6,
    ):
        self.client = client
        self.namespace = namespace
        self.text_limit = max(4000, int(text_limit))
        self.summary_keep_turns = max(2, int(summary_keep_turns))
        self._summariser = None

    @classmethod
    def from_env(cls) -> "RedisConversationStore":
        if redis is None:
            return cls(None)

        url = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")
        enabled = os.getenv("REDIS_ENABLED", "true").strip().lower() in {"1", "true", "yes"}
        if not enabled:
            return cls(None)

        try:
            client = redis.Redis.from_url(url, decode_responses=True)
            client.ping()
            text_limit = int(os.getenv("REDIS_TEXT_LIMIT", "20000"))
            keep_turns = int(os.getenv("REDIS_SUMMARY_KEEP_TURNS", "6"))
            namespace = os.getenv("REDIS_NAMESPACE", "proptech")
            return cls(
                client,
                namespace=namespace,
                text_limit=text_limit,
                summary_keep_turns=keep_turns,
            )
        except Exception:
            return cls(None)

    @property
    def enabled(self) -> bool:
        return self.client is not None

    def _session_key(self, thread_id: str) -> str:
        return f"{self.namespace}:session:{thread_id}"

    def _messages_key(self, thread_id: str) -> str:
        return f"{self.namespace}:session:{thread_id}:messages"

    def _cache_key(self, thread_id: str) -> str:
        return f"{self.namespace}:session:{thread_id}:cache"

    def _user_index_key(self, user_key: str) -> str:
        return f"{self.namespace}:sessions:user:{user_key}"

    def touch_session(self, thread_id: str, user_key: str = "") -> None:
        if not self.enabled or not thread_id:
            return
        now = str(int(time.time()))
        key = self._session_key(thread_id)
        self.client.hset(
            key,
            mapping={
                "thread_id": thread_id,
                "updated_at": now,
            },
        )
        if user_key:
            self.client.hset(key, "user_key", user_key)
            self.client.zadd(self._user_index_key(user_key), {thread_id: time.time()})

    def list_sessions(self, user_key: str, limit: int = 30) -> list[str]:
        if not self.enabled or not user_key:
            return []
        return self.client.zrevrange(self._user_index_key(user_key), 0, max(0, limit - 1))

    def get_session(self, thread_id: str) -> dict:
        if not self.enabled or not thread_id:
            return {"summary": "", "messages": []}
        summary = self.client.hget(self._session_key(thread_id), "summary") or ""
        raw_msgs = self.client.lrange(self._messages_key(thread_id), 0, -1)
        messages: list[dict] = []
        for raw in raw_msgs:
            try:
                messages.append(json.loads(raw))
            except Exception:
                continue
        return {"summary": summary, "messages": messages}

    def get_messages(self, thread_id: str) -> list[dict]:
        return self.get_session(thread_id)["messages"]

    def append_turn(self, thread_id: str, user_text: str, assistant_text: str, user_key: str = "") -> None:
        if not self.enabled or not thread_id:
            return
        msgs_key = self._messages_key(thread_id)
        self.client.rpush(msgs_key, json.dumps({"role": "human", "content": user_text}, ensure_ascii=True))
        self.client.rpush(msgs_key, json.dumps({"role": "ai", "content": assistant_text}, ensure_ascii=True))
        self.touch_session(thread_id, user_key=user_key)

    def _cache_field(self, user_text: str) -> str:
        return user_text.strip().lower()

    def get_cached_response(self, thread_id: str, user_text: str) -> str | None:
        if not self.enabled or not thread_id or not user_text.strip():
            return None
        return self.client.hget(self._cache_key(thread_id), self._cache_field(user_text))

    def set_cached_response(self, thread_id: str, user_text: str, assistant_text: str) -> None:
        if not self.enabled or not thread_id or not user_text.strip():
            return
        self.client.hset(self._cache_key(thread_id), self._cache_field(user_text), assistant_text)

    def _summariser_llm(self):
        if self._summariser is None:
            self._summariser = ChatOpenAI(
                model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
                temperature=0,
                timeout=float(os.getenv("OPENAI_TIMEOUT_SECONDS", "45")),
            )
        return self._summariser

    def _summarise(self, existing_summary: str, chunk: list[dict]) -> str:
        chunk_text = "\n".join(
            f"{m.get('role', 'unknown').upper()}: {str(m.get('content', ''))}" for m in chunk
        )
        if not chunk_text.strip():
            return existing_summary

        prompt = (
            "You are maintaining compact conversation memory for a multi-agent real-estate assistant.\n"
            "Merge the existing summary and the new dialogue chunk into a short, factual memory.\n"
            "Keep important facts, IDs, preferences, constraints, locations, budget ranges, and unresolved tasks.\n"
            "Output plain text only, max 2200 characters.\n\n"
            f"Existing summary:\n{existing_summary or '(none)'}\n\n"
            f"New dialogue chunk:\n{chunk_text}"
        )
        try:
            out = self._summariser_llm().invoke(prompt)
            text = str(getattr(out, "content", out)).strip()
            return text[:2200] if text else existing_summary
        except Exception:
            merged = (existing_summary + "\n" + chunk_text).strip()
            return merged[-2200:]

    def compact_if_needed(self, thread_id: str) -> None:
        if not self.enabled or not thread_id:
            return
        session = self.get_session(thread_id)
        summary = session.get("summary", "")
        messages = session.get("messages", [])

        def _size() -> int:
            return len(summary) + sum(len(str(m.get("content", ""))) for m in messages)

        while _size() > self.text_limit and len(messages) > self.summary_keep_turns:
            chunk_len = max(2, (len(messages) - self.summary_keep_turns) // 2)
            if chunk_len % 2 != 0:
                chunk_len += 1
            chunk = messages[:chunk_len]
            messages = messages[chunk_len:]
            summary = self._summarise(summary, chunk)

        sess_key = self._session_key(thread_id)
        msg_key = self._messages_key(thread_id)
        pipe = self.client.pipeline()
        pipe.hset(sess_key, mapping={"summary": summary, "updated_at": str(int(time.time()))})
        pipe.delete(msg_key)
        if messages:
            pipe.rpush(msg_key, *[json.dumps(m, ensure_ascii=True) for m in messages])
        pipe.execute()
