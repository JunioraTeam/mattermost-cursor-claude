"""Mattermost REST API client over aiohttp (port of mattermost/api.ts)."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

import aiohttp

from .types import MattermostPost, MattermostUser, PostThreadResponse

if TYPE_CHECKING:
    from ..util.logger import Logger


class MattermostApi:
    def __init__(self, base_url: str, token: str, log: "Logger") -> None:
        self._base_url = base_url
        self._token = token
        self._log = log
        self._session: aiohttp.ClientSession | None = None

    def _url(self, path: str) -> str:
        return f"{self._base_url.rstrip('/')}/api/v4{path}"

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                headers={
                    "Authorization": f"Bearer {self._token}",
                    "Content-Type": "application/json",
                }
            )
        return self._session

    async def request(self, method: str, path: str, body: Any = None) -> Any:
        session = await self._get_session()
        async with session.request(
            method,
            self._url(path),
            json=body if body is not None else None,
        ) as res:
            if not (200 <= res.status < 300):
                text = await res.text()
                self._log.error(
                    "Mattermost API error", path=path, status=res.status, text=text
                )
                raise RuntimeError(
                    f"Mattermost {method} {path} failed: {res.status} {text}"
                )
            return await res.json()

    async def get_me(self) -> MattermostUser:
        return MattermostUser.from_json(await self.request("GET", "/users/me"))

    async def get_post(self, post_id: str) -> MattermostPost:
        return MattermostPost.from_json(await self.request("GET", f"/posts/{post_id}"))

    async def get_post_thread(self, root_post_id: str) -> PostThreadResponse:
        return PostThreadResponse.from_json(
            await self.request("GET", f"/posts/{root_post_id}/thread")
        )

    async def get_users_by_ids(self, user_ids: list[str]) -> dict[str, MattermostUser]:
        out: dict[str, MattermostUser] = {}
        if not user_ids:
            return out
        unique = list(dict.fromkeys(user_ids))
        chunk_size = 200
        for i in range(0, len(unique), chunk_size):
            chunk = unique[i : i + chunk_size]
            users = await self.request("POST", "/users/ids", chunk)
            for u in users:
                user = MattermostUser.from_json(u)
                out[user.id] = user
        return out

    async def create_post(
        self,
        *,
        channel_id: str,
        message: str,
        root_id: str | None = None,
        props: dict[str, Any] | None = None,
    ) -> MattermostPost:
        body: dict[str, Any] = {"channel_id": channel_id, "message": message}
        if root_id is not None:
            body["root_id"] = root_id
        if props is not None:
            body["props"] = props
        return MattermostPost.from_json(await self.request("POST", "/posts", body))

    async def update_post(self, post: MattermostPost) -> MattermostPost:
        return MattermostPost.from_json(
            await self.request("PUT", f"/posts/{post.id}", post.to_json())
        )

    async def create_ephemeral_post(
        self,
        *,
        user_id: str,
        channel_id: str,
        message: str,
        root_id: str | None = None,
    ) -> None:
        await self.request(
            "POST",
            "/posts/ephemeral",
            {
                "user_id": user_id,
                "post": {
                    "channel_id": channel_id,
                    "message": message,
                    "root_id": root_id or "",
                },
            },
        )

    async def aclose(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
