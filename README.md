# Mattermost Cursor & Claude

Run coding agents from Mattermost — either as a **standalone bot** (WebSocket + post streaming) or as an **OpenAI-compatible backend** for [mattermost-plugin-agents](https://github.com/mattermost/mattermost-plugin-agents) (blinking caret, rich tool UI).

The agent backend is pluggable via **`AI_PROVIDER`**:

| `AI_PROVIDER` | SDK | Runtime |
|---------------|-----|---------|
| `cursor` (default) | [Cursor Python SDK](https://cursor.com/docs/sdk/python) (`cursor-sdk`) | local or Cursor cloud |
| `claude` | [Claude Agent SDK](https://code.claude.com/docs/en/agent-sdk/overview#python) (`claude-agent-sdk`) | local (bundled Claude Code CLI) |

Both providers stream the same way into Mattermost (assistant text, thinking, tool-call progress). Switching is one env var — the bot, OpenAI API, queue, history, and panel are provider-agnostic.

This is a Python service built on the provider SDKs, [aiohttp](https://docs.aiohttp.org/), and [pydantic-settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/). Run it with [uv](https://docs.astral.sh/uv/):

```bash
uv sync
uv run mattermost-cursor
```

## Two integration modes

| Mode | Env | UX |
|------|-----|-----|
| **Standalone bot** | `BOT_MODE=standalone` (default) | Bot listens on WebSocket, streams into one thread post via REST `PUT`. Tool progress is markdown blockquotes. |
| **Agents plugin** | `BOT_MODE=openai` | This service exposes `/v1/chat/completions`. Configure the plugin’s **OpenAI Compatible** service to point here. You get the plugin’s **blinking caret**, structured posts, and **tool approval cards**. |

The caret and tool-approval UI are implemented in the **plugin webapp** (`LLMBotPost`, `PostText`, `ToolApprovalSet`), not in the Mattermost core API. A plain bot token cannot reproduce them — only the Agents plugin (or similar custom webapp code) can.

Reference plugin source is vendored under `vendor/mattermost-plugin-agents/` for local study (not committed by default).

## Agent providers

Set `AI_PROVIDER` to pick the backend (default `cursor`).

### Cursor (`AI_PROVIDER=cursor`)

```bash
AI_PROVIDER=cursor
CURSOR_API_KEY=...
CURSOR_MODEL=composer-2
CURSOR_RUNTIME=local      # or cloud + CURSOR_CLOUD_REPOS_JSON
```

Runs [Cursor agents](https://cursor.com/docs/sdk/python) locally or in Cursor cloud. Cloud agents only accept HTTP/SSE MCP; local accepts stdio presets. Interactive `request` events drive the human-approval flow (reply `approve <token>` / `deny <token>`).

### Claude (`AI_PROVIDER=claude`)

```bash
AI_PROVIDER=claude
ANTHROPIC_API_KEY=sk-ant-...   # omit to reuse an existing Claude Code login
CLAUDE_MODEL=claude-sonnet-4-6
CLAUDE_PERMISSION_MODE=acceptEdits
# CLAUDE_CWD=/workspace
```

Runs a local [Claude Agent SDK](https://code.claude.com/docs/en/agent-sdk/overview#python) agent. The SDK bundles its own Claude Code CLI, so no separate install is needed — `uv sync` is enough. Auth uses `ANTHROPIC_API_KEY`, or an existing `claude` login if the variable is unset.

Tool permissioning is governed by `CLAUDE_PERMISSION_MODE` (`default` | `acceptEdits` | `plan` | `bypassPermissions` | `dontAsk` | `auto`) rather than the per-request approval card flow. `CLAUDE_ALLOWED_TOOLS` / `CLAUDE_DISALLOWED_TOOLS` (CSV) restrict the toolset; `CLAUDE_SYSTEM_PROMPT` is appended to the bundled `claude_code` system prompt (set `CLAUDE_SYSTEM_PROMPT_PRESET=false` to use it verbatim). Claude runs locally, so stdio MCP presets (GitLab, Atlassian, Figma) work directly.

| Capability | Cursor | Claude |
|------------|--------|--------|
| Local runtime | ✅ | ✅ |
| Cloud runtime / auto-MR | ✅ | ❌ (use local + GitLab MCP) |
| stdio MCP presets | local only | ✅ |
| Per-request approval cards | ✅ (`request` events) | governed by `CLAUDE_PERMISSION_MODE` |

## Quick start — Agents plugin (recommended UI)

1. Install and enable [mattermost-plugin-agents](https://github.com/mattermost/mattermost-plugin-agents) on your Mattermost server.

2. Run this service in OpenAI mode (pick a provider):

```bash
BOT_MODE=openai
OPENAI_API_PORT=8080
# OPENAI_API_KEY=optional-bearer-secret

# Cursor backend:
AI_PROVIDER=cursor
CURSOR_API_KEY=...
CURSOR_RUNTIME=local   # or cloud + CURSOR_CLOUD_REPOS_JSON

# …or Claude backend:
# AI_PROVIDER=claude
# ANTHROPIC_API_KEY=sk-ant-...
# CLAUDE_MODEL=claude-sonnet-4-6
```

3. In **System Console → Plugins → Agents**, add an **OpenAI Compatible** service:

   - **API URL**: `http://<host>:8080/v1` (must be reachable from the Mattermost server)
   - **API Key**: same as `OPENAI_API_KEY` if set
   - **Default model**: your `CURSOR_MODEL` / `CLAUDE_MODEL` (e.g. `composer-2` or `claude-sonnet-4-6`). The `/v1/models` endpoint reports the active provider's model.
   - **Use Responses API**: **disabled** (Chat Completions compatibility)

4. On the **Agents** page, create an agent that uses that service. Disable **Enable Tools** on the agent if you want the backend's own MCP only (tools run inside Cursor/Claude, shown as markdown in the stream). Enable plugin MCP tools if you want the plugin’s approval UI for those tools.

5. `@mention` the new agent in a channel.

## Quick start — Standalone bot

```bash
BOT_MODE=standalone
MATTERMOST_URL=https://mattermost.example.com
MATTERMOST_BOT_TOKEN=...

# Cursor backend:
AI_PROVIDER=cursor
CURSOR_API_KEY=...
# …or Claude backend:
# AI_PROVIDER=claude
# ANTHROPIC_API_KEY=sk-ant-...
```

See `.env.example` for provider, MCP, cloud, and approval settings.

### Thread context (standalone bot)

When @mentioned in a thread, the bot loads the **full thread** via Mattermost’s API (`GET /posts/{id}/thread`) and includes it in the agent prompt (oldest first). The invoking message is marked _(invoked you)_. Long threads are truncated from the oldest messages; tune with `MATTERMOST_THREAD_CONTEXT_MAX_CHARS` (default `16000`).

### Per-thread queue (standalone bot)

Only **one run** is active per thread at a time. Additional `@mentions` are queued (FIFO). You get an ephemeral confirmation with a queue id.

| Command | Action |
|---------|--------|
| `queue` | List pending messages |
| `cancel queue` / `cancel all` | Remove all queued messages |
| `cancel <id>` | Remove one queued message |
| `cancel run` | Cancel the run in progress |
| `reset-session` | Clear queue, cancel run, reset agent |

## Tool call display

When a tool finishes, the **running** line (`…`) is replaced by the **completed** line (`→ **completed**`) in the same post — no duplicate lines.

## Configuration

Copy `.env.example` to `.env`. Key variables:

- `BOT_MODE` — `standalone` | `openai` | `both`
- `AI_PROVIDER` — `cursor` (default) | `claude`
- `OPENAI_API_PORT` — default `8080`
- `CURSOR_AUTO_APPROVE_REQUESTS` — default `true` in OpenAI mode (Cursor `request` events; not used by the Claude provider)
- Provider keys — `CURSOR_API_KEY` (required for `cursor`); `ANTHROPIC_API_KEY` (Claude; optional if already logged in via Claude Code)
- Mattermost vars only required for `standalone` / `both`

### Figma MCP (optional)

[Framelink MCP for Figma](https://github.com/GLips/Figma-Context-MCP) (`figma-developer-mcp`) is enabled when you set `FIGMA_PERSONAL_ACCESS_TOKEN` ([create a token](https://www.framelink.ai/docs/quickstart) with read access to file content and dev resources). If unset, the Figma server is not registered.

```bash
FIGMA_PERSONAL_ACCESS_TOKEN=figd_...
# MCP_FIGMA_COMMAND=npx
# MCP_FIGMA_ARGS=-y,figma-developer-mcp,--stdio
```

Stdio MCP requires `CURSOR_RUNTIME=local` (Cursor cloud agents only accept HTTP/SSE MCP). The Claude provider runs locally and accepts stdio MCP unconditionally. Use `MCP_MERGE_PRESETS=true` if you override servers via `MCP_SERVERS_JSON` but still want the Figma preset.

## Admin panel

Set `PANEL_PORT` (default `3850`, use `0` to disable), `PANEL_USERNAME`, and `PANEL_PASSWORD`. Open `http://localhost:3850`, sign in, and view:

- **Runs** — queued, running, and completed agent turns (Mattermost + OpenAI API)
- **Users** — activity history per Mattermost user

Data is kept in memory and resets when the process restarts.

## Docker

```bash
docker compose up --build
```

Expose `OPENAI_API_PORT` when using plugin mode (update `docker-compose.yml` ports as needed).

## Architecture

```
mattermost-plugin-agents  ──POST /v1/chat/completions──►  mattermost-cursor (OpenAI API)
        │                                                          │
        │  WebSocket + custom post UI                              │  provider facade (AI_PROVIDER)
        ▼                                                          ▼
   Mattermost clients                              cursor-sdk ┄┄┄┄┄┄┄┄┄┐
                                                              ▼        ▼
                                                   Cursor agent    Claude agent
                                                   (+ MCP)         (claude-agent-sdk, + MCP)
```

Standalone mode skips the plugin and talks to Mattermost directly over WebSocket + REST. Both providers stream through the same dispatcher, so the bot, queue, history, and panel are identical regardless of `AI_PROVIDER`.
