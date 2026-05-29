"""Standalone Mattermost WebSocket bot orchestration (port of bot/app.ts)."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ..cursor.agent_runner import run_cursor_turn
from ..cursor.create_agent import create_cursor_agent
from ..mattermost.api import MattermostApi
from ..mattermost.post_utils import (
    is_approval_token,
    is_queue_status_command,
    parse_cancel_command,
    strip_mentions,
)
from ..mattermost.streaming_post import StreamingPost
from ..mattermost.thread_context import build_user_message_with_thread_context
from ..mattermost.types import MattermostPost
from .thread_queue import QueuedRun, ThreadRunQueue, new_queue_id

if TYPE_CHECKING:
    from cursor_sdk import AsyncClient

    from ..approval.manager import ApprovalManager
    from ..config import AppEnv
    from ..history.store import HistoryStore
    from ..util.logger import Logger


@dataclass
class ThreadSession:
    agent: Any
    mcp_servers: dict[str, Any]
    run_queue: ThreadRunQueue
    current_run: Any = None


def _thread_key(channel_id: str, post: MattermostPost) -> str:
    root = post.root_id or post.id
    return f"{channel_id}:{root}"


class CursorMattermostBot:
    def __init__(
        self,
        env: "AppEnv",
        log: "Logger",
        approvals: "ApprovalManager",
        history: "HistoryStore",
        client: "AsyncClient",
    ) -> None:
        self._env = env
        self._log = log
        self._approvals = approvals
        self._history = history
        self._client = client
        self._api = MattermostApi(env.MATTERMOST_URL, env.MATTERMOST_BOT_TOKEN, log)
        self._bot_user_id = ""
        self._bot_username = ""
        self._sessions: dict[str, ThreadSession] = {}

    async def init(self) -> None:
        me = await self._api.get_me()
        self._bot_user_id = me.id
        self._bot_username = me.username
        self._log.info("Mattermost bot identity", user=me.username, id=me.id)

    def get_bot_user_id(self) -> str:
        return self._bot_user_id

    def get_approvals(self) -> "ApprovalManager":
        return self._approvals

    async def aclose(self) -> None:
        await self._api.aclose()

    async def handle_posted(self, post: MattermostPost) -> None:
        if post.user_id == self._bot_user_id:
            return
        if post.type == "system_message":
            return

        allowed_raw = self._env.MATTERMOST_ALLOWED_CHANNEL_IDS
        if allowed_raw:
            allowed = [s.strip() for s in allowed_raw.split(",") if s.strip()]
            if allowed and post.channel_id not in allowed:
                return

        text = strip_mentions(post.message, self._bot_user_id, self._bot_username)
        approval = is_approval_token(text)
        if approval:
            ok = approval.kind == "approve"
            asyncio.ensure_future(self._record_user_event(post, "approval", text))
            if self._approvals.resolve(approval.token, ok):
                await self._api.create_ephemeral_post(
                    user_id=post.user_id,
                    channel_id=post.channel_id,
                    message="Approval recorded." if ok else "Denial recorded.",
                    root_id=post.root_id or post.id,
                )
            return

        if text.lower() in ("reset-session", "reset session"):
            asyncio.ensure_future(self._record_user_event(post, "reset_session", text))
            await self._reset_session(post.channel_id, post)
            await self._api.create_ephemeral_post(
                user_id=post.user_id,
                channel_id=post.channel_id,
                message="Session reset for this thread (queue cleared).",
                root_id=post.root_id or post.id,
            )
            return

        key = _thread_key(post.channel_id, post)
        session = await self._get_or_create_session(key)

        cancel = parse_cancel_command(text)
        if cancel:
            asyncio.ensure_future(self._record_user_event(post, "cancel", text))
            await self._handle_cancel_command(post, session, cancel)
            return

        if is_queue_status_command(text):
            asyncio.ensure_future(self._record_user_event(post, "queue", text))
            await self._handle_queue_status(post, session)
            return

        if not text:
            return

        mention_token = f"@{self._bot_user_id}"
        bracket_mention = f"<@{self._bot_user_id}>"
        mention_username = f"@{self._bot_username}"
        mentioned = (
            mention_token in post.message
            or bracket_mention in post.message
            or mention_username in post.message
        )

        if self._env.MATTERMOST_REQUIRE_MENTION and not mentioned:
            ch = await self._safe_get_channel(post.channel_id)
            ch_type = ch.get("type") if ch else None
            if ch_type != "D" and ch_type != "G":
                return

        username = await self._resolve_username(post.user_id)
        queue_id = new_queue_id()
        history_run_id = self._history.start_run(
            source="mattermost",
            userId=post.user_id,
            username=username,
            channelId=post.channel_id,
            threadKey=key,
            messagePreview=text,
            queueId=queue_id,
            status="queued",
        )
        item = QueuedRun(
            id=queue_id, post=post, user_text=text, history_run_id=history_run_id
        )
        asyncio.ensure_future(self._record_user_event(post, "message", text, username))
        position = session.run_queue.enqueue(item)
        starts_now = position == 1 and not session.run_queue.processing
        asyncio.ensure_future(self._drain_queue(key, session))

        root = post.root_id or post.id
        if starts_now:
            await self._api.create_ephemeral_post(
                user_id=post.user_id,
                channel_id=post.channel_id,
                message="Processing your message…",
                root_id=root,
            )
        else:
            await self._api.create_ephemeral_post(
                user_id=post.user_id,
                channel_id=post.channel_id,
                message=(
                    f"Queued as `{item.id}` (position {position}). "
                    f"Reply `cancel {item.id}` or `cancel queue` to remove. "
                    f"`queue` lists pending messages."
                ),
                root_id=root,
            )

    async def _handle_cancel_command(
        self, post: MattermostPost, session: ThreadSession, cmd: Any
    ) -> None:
        root = post.root_id or post.id

        if cmd.kind == "queue":
            n = session.run_queue.cancel_all()
            cancelled = self._history.cancel_all_queued()
            if n:
                message = f"Removed {n} queued message(s)."
            elif cancelled:
                message = f"Cleared {cancelled} queued run(s) from history."
            else:
                message = "The queue is already empty."
        elif cmd.kind == "id":
            removed = session.run_queue.cancel(cmd.id)
            if removed:
                self._history.cancel_queued_by_queue_id(cmd.id)
            message = (
                f"Removed queued message `{cmd.id}`."
                if removed
                else f"No queued message with id `{cmd.id}`."
            )
        else:
            run = session.current_run
            if not run:
                message = "No run is in progress in this thread."
            elif run.supports("cancel"):
                await run.cancel()
                message = "Cancellation requested for the current run."
            else:
                message = "The current run cannot be cancelled."

        await self._api.create_ephemeral_post(
            user_id=post.user_id,
            channel_id=post.channel_id,
            message=message,
            root_id=root,
        )

    async def _handle_queue_status(
        self, post: MattermostPost, session: ThreadSession
    ) -> None:
        root = post.root_id or post.id
        pending = session.run_queue.list()
        if session.run_queue.processing and not pending:
            message = "A run is in progress. The queue is empty."
        elif not session.run_queue.processing and not pending:
            message = "The queue is empty."
        else:
            lines = [
                f"{i + 1}. `{qid}` — {utext[:80]}{'…' if len(utext) > 80 else ''}"
                for i, (qid, utext) in enumerate(pending)
            ]
            active = "_(run in progress)_\n" if session.run_queue.processing else ""
            message = f"{active}**Queued messages:**\n" + "\n".join(lines)
        await self._api.create_ephemeral_post(
            user_id=post.user_id,
            channel_id=post.channel_id,
            message=message,
            root_id=root,
        )

    async def _drain_queue(self, key: str, session: ThreadSession) -> None:
        if session.run_queue.processing:
            return
        session.run_queue.processing = True
        try:
            while session.run_queue.pending:
                item = session.run_queue.pending.pop(0)
                await self._process_queued_run(session, item)
        finally:
            session.run_queue.processing = False
            session.current_run = None
            if session.run_queue.pending:
                asyncio.ensure_future(self._drain_queue(key, session))

    async def _record_user_event(
        self, post: MattermostPost, event_type: str, preview: str, username: str | None = None
    ) -> None:
        name = username if username is not None else await self._resolve_username(post.user_id)
        self._history.record_user_event(
            userId=post.user_id,
            username=name,
            type=event_type,
            channelId=post.channel_id,
            threadKey=_thread_key(post.channel_id, post),
            preview=preview,
        )

    async def _resolve_username(self, user_id: str) -> str | None:
        try:
            users = await self._api.get_users_by_ids([user_id])
            u = users.get(user_id)
            return u.username if u else None
        except Exception:
            return None

    async def _process_queued_run(self, session: ThreadSession, item: QueuedRun) -> None:
        post = item.post
        self._history.update_run(item.history_run_id, status="running")
        user_text = await build_user_message_with_thread_context(
            api=self._api,
            post=post,
            raw_user_text=item.user_text,
            bot_user_id=self._bot_user_id,
            bot_username=self._bot_username,
            max_chars=self._env.MATTERMOST_THREAD_CONTEXT_MAX_CHARS,
            log=self._log,
        )
        root_for_reply = post.root_id or post.id
        try:
            reply = await self._api.create_post(
                channel_id=post.channel_id,
                message="_Thinking…_",
                root_id=root_for_reply,
                props={"from_bot": "cursor", "queue_id": item.id},
            )
            self._history.update_run(item.history_run_id, replyPostId=reply.id)
        except Exception as e:
            self._log.error("Failed to create reply post", err=str(e), queueId=item.id)
            self._history.finish_run(
                item.history_run_id, ok=False, detail="Failed to create reply post"
            )
            return

        streamer = StreamingPost(
            self._api,
            reply,
            self._env.MATTERMOST_STREAM_MS,
            self._env.MATTERMOST_MAX_POST_CHARS,
        )

        session.current_run = None
        result = None
        try:
            def on_run_started(run: Any) -> None:
                session.current_run = run
                self._history.update_run(
                    item.history_run_id,
                    cursorRunId=run.run_id,
                    agentId=getattr(run, "agent_id", None),
                )

            result = await run_cursor_turn(
                env=self._env,
                log=self._log,
                agent=session.agent,
                mcp_servers=session.mcp_servers,
                user_text=user_text,
                streamer=streamer,
                approvals=self._approvals,
                on_run_started=on_run_started,
            )
            await streamer.close(None if result.ok else f"_{result.detail}_")
        except Exception as e:
            self._log.error("run_cursor_turn failed", err=str(e), queueId=item.id)
            result = type("R", (), {"ok": False, "detail": str(e)})()
            await streamer.close(f"_Error: {e}_")
        finally:
            session.current_run = None
            if result is not None:
                self._history.finish_run(
                    item.history_run_id,
                    ok=result.ok,
                    detail=result.detail,
                    status="cancelled" if result.detail == "cancelled" else None,
                )

    async def _safe_get_channel(self, channel_id: str) -> dict | None:
        try:
            return await self._api.request("GET", f"/channels/{channel_id}")
        except Exception:
            return None

    async def _reset_session(self, channel_id: str, post: MattermostPost) -> None:
        key = _thread_key(channel_id, post)
        s = self._sessions.get(key)
        if not s:
            return

        s.run_queue.cancel_all()
        run = s.current_run
        if run and run.supports("cancel"):
            try:
                await run.cancel()
            except Exception:
                pass
        s.current_run = None

        try:
            await s.agent.close()
        except Exception:
            pass
        self._sessions.pop(key, None)

    async def _get_or_create_session(self, key: str) -> ThreadSession:
        s = self._sessions.get(key)
        if s:
            return s
        agent, mcp_servers = await create_cursor_agent(self._env, self._log, self._client)
        s = ThreadSession(
            agent=agent,
            mcp_servers=mcp_servers,
            run_queue=ThreadRunQueue(),
            current_run=None,
        )
        self._sessions[key] = s
        return s
