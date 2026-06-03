"""Environment configuration (port of config/load-env.ts).

Field names intentionally match the env var names (uppercase) so the rest of the
code reads ``env.CURSOR_MODEL`` exactly like the TypeScript original.
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from pydantic import ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}


def _coerce_bool(v: object) -> object:
    if isinstance(v, bool) or v is None:
        return v
    if v == "":
        return None
    s = str(v).lower()
    if s in _TRUE:
        return True
    if s in _FALSE:
        return False
    return v


class AppEnv(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=None,  # .env is loaded explicitly in load_env()
        case_sensitive=False,
        extra="ignore",
    )

    # standalone — WebSocket bot; openai — OpenAI-compatible API; both — run both
    BOT_MODE: Literal["standalone", "openai", "both"] = "standalone"
    MATTERMOST_URL: str | None = None
    MATTERMOST_BOT_TOKEN: str | None = None
    MATTERMOST_TEAM_ID: str | None = None
    MATTERMOST_ALLOWED_CHANNEL_IDS: str | None = None
    MATTERMOST_REQUIRE_MENTION: bool = True

    # cursor — Cursor Python SDK; claude — Claude Agent SDK
    AI_PROVIDER: Literal["cursor", "claude"] = "cursor"

    CURSOR_API_KEY: str | None = None
    CURSOR_MODEL: str = "composer-2"
    CURSOR_RUNTIME: Literal["local", "cloud"] = "cloud"
    CURSOR_LOCAL_CWD: str | None = None
    CURSOR_CLOUD_REPOS_JSON: str | None = None
    CURSOR_CLOUD_AUTO_CREATE_MR: bool = True
    CURSOR_CLOUD_SKIP_REVIEWER_REQUEST: bool = True
    CURSOR_CLOUD_ENV_JSON: str | None = None
    CURSOR_AUTO_APPROVE_REQUESTS: bool = True

    # Claude Agent SDK (https://code.claude.com/docs/en/agent-sdk/overview)
    ANTHROPIC_API_KEY: str | None = None
    CLAUDE_MODEL: str = "claude-sonnet-4-6"
    CLAUDE_CWD: str | None = None
    # default | acceptEdits | plan | bypassPermissions | dontAsk | auto
    CLAUDE_PERMISSION_MODE: Literal[
        "default", "acceptEdits", "plan", "bypassPermissions", "dontAsk", "auto"
    ] = "acceptEdits"
    # When true, build on the bundled claude_code system prompt and append
    # CLAUDE_SYSTEM_PROMPT (if any). When false, CLAUDE_SYSTEM_PROMPT is used verbatim.
    CLAUDE_SYSTEM_PROMPT_PRESET: bool = True
    CLAUDE_SYSTEM_PROMPT: str | None = None
    CLAUDE_MAX_TURNS: int | None = None
    CLAUDE_ALLOWED_TOOLS: str | None = None
    CLAUDE_DISALLOWED_TOOLS: str | None = None

    OPENAI_API_PORT: int = 8080
    OPENAI_API_KEY: str | None = None

    MCP_SERVERS_JSON: str | None = None
    MCP_MERGE_PRESETS: bool = False
    MCP_GITLAB_COMMAND: str = "npx"
    MCP_GITLAB_ARGS: str = "-y,@zereight/mcp-gitlab"
    MCP_ATLASSIAN_COMMAND: str = "uvx"
    MCP_ATLASSIAN_ARGS: str = "mcp-atlassian"
    MCP_GITLAB_HTTP_URL: str | None = None
    MCP_GITLAB_HTTP_HEADERS_JSON: str | None = None
    MCP_ATLASSIAN_HTTP_URL: str | None = None
    MCP_ATLASSIAN_HTTP_HEADERS_JSON: str | None = None

    JIRA_URL: str | None = None
    JIRA_USERNAME: str | None = None
    JIRA_API_TOKEN: str | None = None
    JIRA_PERSONAL_TOKEN: str | None = None
    CONFLUENCE_URL: str | None = None
    CONFLUENCE_USERNAME: str | None = None
    CONFLUENCE_API_TOKEN: str | None = None
    CONFLUENCE_PERSONAL_TOKEN: str | None = None

    GITLAB_API_URL: str | None = None
    GITLAB_PERSONAL_ACCESS_TOKEN: str | None = None

    FIGMA_PERSONAL_ACCESS_TOKEN: str | None = None
    MCP_FIGMA_COMMAND: str = "npx"
    MCP_FIGMA_ARGS: str = "-y,figma-developer-mcp,--stdio"

    GITLAB_MR_DEFAULT_TARGET_BRANCH: str = "develop"
    GITLAB_MR_FORBIDDEN_TARGET_BRANCHES: str = "main,staging"

    LOG_LEVEL: str = "info"
    MATTERMOST_STREAM_MS: int = 1200
    MATTERMOST_MAX_POST_CHARS: int = 15000
    MATTERMOST_THREAD_CONTEXT_MAX_CHARS: int = 16000

    APPROVAL_HTTP_PORT: int = 3847
    APPROVAL_PUBLIC_BASE_URL: str | None = None
    APPROVAL_ACTION_SECRET: str | None = None
    APPROVAL_TIMEOUT_MS: int = 3_600_000

    PANEL_PORT: int = 0
    PANEL_USERNAME: str | None = None
    PANEL_PASSWORD: str | None = None
    PANEL_SECRET: str | None = None

    @field_validator(
        "MATTERMOST_REQUIRE_MENTION",
        "CURSOR_CLOUD_AUTO_CREATE_MR",
        "CURSOR_CLOUD_SKIP_REVIEWER_REQUEST",
        "CURSOR_AUTO_APPROVE_REQUESTS",
        "CLAUDE_SYSTEM_PROMPT_PRESET",
        "MCP_MERGE_PRESETS",
        mode="before",
    )
    @classmethod
    def _parse_bool(cls, v: object) -> object:
        return _coerce_bool(v)

    @model_validator(mode="after")
    def _cross_field(self) -> "AppEnv":
        issues: list[str] = []
        if self.BOT_MODE in ("standalone", "both"):
            if not self.MATTERMOST_URL:
                issues.append(
                    "MATTERMOST_URL: MATTERMOST_URL is required when BOT_MODE is standalone or both"
                )
            if not self.MATTERMOST_BOT_TOKEN:
                issues.append(
                    "MATTERMOST_BOT_TOKEN: MATTERMOST_BOT_TOKEN is required when "
                    "BOT_MODE is standalone or both"
                )
        if self.AI_PROVIDER == "cursor":
            if not self.CURSOR_API_KEY:
                issues.append(
                    "CURSOR_API_KEY: CURSOR_API_KEY is required when AI_PROVIDER=cursor"
                )
            repos = (self.CURSOR_CLOUD_REPOS_JSON or "").strip()
            if self.CURSOR_RUNTIME == "cloud" and (not repos or repos == "[]"):
                issues.append(
                    "CURSOR_CLOUD_REPOS_JSON: CURSOR_CLOUD_REPOS_JSON must include at least "
                    "one repo when CURSOR_RUNTIME=cloud"
                )
        if self.PANEL_PORT and self.PANEL_PORT > 0:
            if not (self.PANEL_USERNAME or "").strip():
                issues.append("PANEL_USERNAME: PANEL_USERNAME is required when PANEL_PORT > 0")
            if not (self.PANEL_PASSWORD or "").strip():
                issues.append("PANEL_PASSWORD: PANEL_PASSWORD is required when PANEL_PORT > 0")
        if issues:
            raise ValueError("\n".join(issues))
        return self


def load_env() -> AppEnv:
    env_path = Path.cwd() / ".env"
    if env_path.exists():
        load_dotenv(env_path)
    else:
        load_dotenv()
    try:
        return AppEnv()
    except ValidationError as e:
        msgs = []
        for err in e.errors():
            loc = ".".join(str(p) for p in err["loc"]) or "(root)"
            msgs.append(f"{loc}: {err['msg']}")
        raise RuntimeError("Invalid environment:\n" + "\n".join(msgs)) from None
