"""Claude Agent SDK provider (https://code.claude.com/docs/en/agent-sdk/overview).

Mirrors the ``cursor`` package's surface so the rest of the app is provider-neutral:
``create_client`` / ``create_claude_agent`` return objects whose ``send`` →
``run.messages()`` → ``run.wait()`` shape matches what the Mattermost and OpenAI
stream dispatchers already consume.
"""
