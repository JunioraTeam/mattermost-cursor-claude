# syntax=docker/dockerfile:1
FROM python:3.12-bookworm-slim

WORKDIR /app

# Runtime tooling:
#   - uv       : installs Python deps and runs the app
#   - node/npx : stdio MCP presets (GitLab, Figma) for CURSOR_RUNTIME=local or AI_PROVIDER=claude
#   - uvx      : provided by uv, runs the Atlassian MCP preset
#   - git      : used by some MCP servers / agents
# The Claude Agent SDK (AI_PROVIDER=claude) bundles its own Claude Code CLI via the
# installed wheel — no extra system package required.
RUN apt-get update \
  && apt-get install -y --no-install-recommends curl ca-certificates git nodejs npm \
  && rm -rf /var/lib/apt/lists/* \
  && curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local sh
ENV PATH="/usr/local/bin:${PATH}"
ENV UV_LINK_MODE=copy

# Install dependencies first (cached layer), then the package.
COPY pyproject.toml ./
COPY mattermost_cursor ./mattermost_cursor
RUN uv sync --no-dev

CMD ["uv", "run", "mattermost-cursor"]
