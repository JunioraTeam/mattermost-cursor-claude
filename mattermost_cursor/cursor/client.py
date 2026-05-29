"""Shared Cursor SDK bridge client.

The async SDK talks to a local ``cursor-sdk-bridge`` process (bundled with the
package) which proxies to local or cloud runtimes. We launch one bridge for the
whole app and reuse it across every agent/session.
"""
from __future__ import annotations

import os
from typing import TYPE_CHECKING

from cursor_sdk import AsyncClient

if TYPE_CHECKING:
    from ..config import AppEnv
    from ..util.logger import Logger


async def create_client(env: "AppEnv", log: "Logger") -> AsyncClient:
    workspace = env.CURSOR_LOCAL_CWD or os.getcwd()
    log.info("Launching Cursor SDK bridge", workspace=workspace, runtime=env.CURSOR_RUNTIME)
    return await AsyncClient.launch_bridge(workspace=workspace)
