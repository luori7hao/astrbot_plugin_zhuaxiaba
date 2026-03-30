from __future__ import annotations

from typing import Any

from .client import ZhuaXiaBaHttpClient


class ZhuaXiaBaApi:
    def __init__(self, client: ZhuaXiaBaHttpClient):
        self.client = client

    async def get_replyme(self, pn: int = 1) -> dict[str, Any]:
        return await self.client.get("/mo/q/claw/replyme", {"pn": pn})

    async def get_threads(self, sort_type: int = 0, pn: int = 1) -> dict[str, Any]:
        return await self.client.get("/c/f/frs/page_claw", {"sort_type": sort_type, "pn": pn})

    async def get_thread_detail(self, thread_id: int, pn: int = 1, r: int = 0) -> dict[str, Any]:
        return await self.client.get(
            "/c/f/pb/page_claw",
            {"pn": pn, "kz": thread_id, "r": r},
        )

    async def get_floor_detail(self, post_id: int, thread_id: int) -> dict[str, Any]:
        return await self.client.get(
            "/c/f/pb/nestedFloor_claw",
            {"post_id": post_id, "thread_id": thread_id},
        )

    async def add_thread(
        self,
        *,
        title: str,
        content: str,
        tab_id: int | None = None,
        tab_name: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "title": title,
            "content": [
                {
                    "type": "text",
                    "content": content,
                }
            ],
        }
        if tab_id is not None:
            payload["tab_id"] = tab_id
        if tab_name:
            payload["tab_name"] = tab_name
        return await self.client.post("/c/c/claw/addThread", payload)

    async def add_post(
        self,
        *,
        content: str,
        thread_id: int | None = None,
        post_id: int | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"content": content}
        if thread_id is not None:
            payload["thread_id"] = thread_id
        if post_id is not None:
            payload["post_id"] = post_id
        return await self.client.post("/c/c/claw/addPost", payload)

    async def op_agree(
        self,
        *,
        thread_id: int,
        obj_type: int,
        op_type: int = 0,
        post_id: int | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "thread_id": thread_id,
            "obj_type": obj_type,
            "op_type": op_type,
        }
        if post_id is not None:
            payload["post_id"] = post_id
        return await self.client.post("/c/c/claw/opAgree", payload)
