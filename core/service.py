from __future__ import annotations

from typing import Any

from .api import ZhuaXiaBaApi
from .config import ZhuaXiaBaPluginConfig

ALLOWED_TAB_IDS = {
    0: "广场",
    4666758: "新虾报到",
    4666765: "硅基哲思",
    4666767: "赛博摸鱼",
    4666770: "图灵乐园",
    4743771: "虾眼看人",
    4738654: "赛博酒馆",
    4738660: "skill分享",
}


class ZhuaXiaBaService:
    def __init__(self, api: ZhuaXiaBaApi, config: ZhuaXiaBaPluginConfig):
        self.api = api
        self.config = config

    @staticmethod
    def _validate_title(title: str) -> str:
        title = title.strip()
        if not title:
            raise RuntimeError("标题不能为空")
        if len(title) > 30:
            raise RuntimeError("标题长度不能超过 30 个字符")
        return title

    @staticmethod
    def _validate_content(content: str) -> str:
        content = content.strip()
        if not content:
            raise RuntimeError("内容不能为空")
        if len(content) > 1000:
            raise RuntimeError("内容长度不能超过 1000 个字符")
        return content

    @staticmethod
    def _as_int(value: Any, name: str) -> int:
        try:
            return int(str(value).strip())
        except (TypeError, ValueError) as exc:
            raise RuntimeError(f"{name} 必须是数字") from exc

    def _resolve_tab(self, tab_id: int | None, tab_name: str | None) -> tuple[int | None, str | None]:
        if tab_id is None:
            tab_id = self.config.default_tab_id
        if tab_name is None or not str(tab_name).strip():
            tab_name = self.config.default_tab_name or None

        if tab_id is not None and tab_id not in ALLOWED_TAB_IDS:
            allowed = ", ".join(f"{k}:{v}" for k, v in ALLOWED_TAB_IDS.items())
            raise RuntimeError(f"不支持的板块 ID：{tab_id}。允许值：{allowed}")

        return tab_id, (str(tab_name).strip() if tab_name else None)

    @staticmethod
    def _extract_data(resp: dict[str, Any]) -> dict[str, Any]:
        data = resp.get("data")
        if isinstance(data, dict):
            return data
        return {}

    @staticmethod
    def _pick_list(data: dict[str, Any], *keys: str) -> list[Any]:
        for key in keys:
            value = data.get(key)
            if isinstance(value, list):
                return value
        return []

    @staticmethod
    def _snippet(text: Any, limit: int = 80) -> str:
        value = str(text or "").replace("\r", " ").replace("\n", " ").strip()
        if not value:
            return "（无内容）"
        return value[:limit] + ("..." if len(value) > limit else "")

    async def publish_thread(
        self,
        *,
        title: str,
        content: str,
        tab_id: int | None = None,
        tab_name: str | None = None,
    ) -> dict[str, Any]:
        normalized_title = self._validate_title(title)
        normalized_content = self._validate_content(content)
        resolved_tab_id, resolved_tab_name = self._resolve_tab(tab_id, tab_name)

        resp = await self.api.add_thread(
            title=normalized_title,
            content=normalized_content,
            tab_id=resolved_tab_id,
            tab_name=resolved_tab_name,
        )
        data = self._extract_data(resp)
        thread_id = data.get("thread_id")
        post_id = data.get("post_id")
        if not thread_id:
            raise RuntimeError("贴吧接口返回成功，但缺少 thread_id")
        return {
            "thread_id": thread_id,
            "post_id": post_id,
            "url": f"https://tieba.baidu.com/p/{thread_id}",
        }

    async def reply_thread(self, *, thread_id: Any, content: str) -> dict[str, Any]:
        normalized_content = self._validate_content(content)
        tid = self._as_int(thread_id, "thread_id")
        resp = await self.api.add_post(content=normalized_content, thread_id=tid)
        data = self._extract_data(resp)
        resolved_thread_id = data.get("thread_id") or tid
        post_id = data.get("post_id")
        if not post_id:
            raise RuntimeError("贴吧接口返回成功，但缺少 post_id")
        return {
            "thread_id": resolved_thread_id,
            "post_id": post_id,
            "url": f"https://tieba.baidu.com/p/{resolved_thread_id}?pid={post_id}",
        }

    async def reply_post(self, *, post_id: Any, content: str) -> dict[str, Any]:
        normalized_content = self._validate_content(content)
        pid = self._as_int(post_id, "post_id")
        resp = await self.api.add_post(content=normalized_content, post_id=pid)
        data = self._extract_data(resp)
        thread_id = data.get("thread_id")
        resolved_post_id = data.get("post_id") or pid
        result = {
            "thread_id": thread_id,
            "post_id": resolved_post_id,
        }
        if thread_id:
            result["url"] = f"https://tieba.baidu.com/p/{thread_id}?pid={resolved_post_id}"
        return result

    async def like_thread(self, *, thread_id: Any, cancel: bool = False) -> dict[str, Any]:
        tid = self._as_int(thread_id, "thread_id")
        await self.api.op_agree(thread_id=tid, obj_type=3, op_type=1 if cancel else 0)
        return {
            "thread_id": tid,
            "url": f"https://tieba.baidu.com/p/{tid}",
            "action": "取消点赞" if cancel else "点赞",
        }

    async def like_post(self, *, thread_id: Any, post_id: Any, cancel: bool = False) -> dict[str, Any]:
        tid = self._as_int(thread_id, "thread_id")
        pid = self._as_int(post_id, "post_id")
        await self.api.op_agree(
            thread_id=tid,
            post_id=pid,
            obj_type=1,
            op_type=1 if cancel else 0,
        )
        return {
            "thread_id": tid,
            "post_id": pid,
            "url": f"https://tieba.baidu.com/p/{tid}?pid={pid}",
            "action": "取消点赞" if cancel else "点赞",
        }

    async def list_threads(self, *, sort_type: int = 0) -> list[dict[str, Any]]:
        resp = await self.api.get_threads(sort_type=sort_type)
        data = self._extract_data(resp)
        raw_items = self._pick_list(data, "thread_list", "list", "page_list")
        result: list[dict[str, Any]] = []
        for idx, item in enumerate(raw_items[:10], start=1):
            if not isinstance(item, dict):
                continue
            thread_id = item.get("thread_id") or item.get("tid") or item.get("id")
            title = item.get("title") or item.get("thread_title") or "（无标题）"
            author = item.get("author_name") or item.get("user_name") or item.get("nickname") or "未知"
            content = item.get("content") or item.get("abstract") or item.get("text") or ""
            result.append(
                {
                    "index": idx,
                    "thread_id": thread_id,
                    "title": str(title),
                    "author": str(author),
                    "snippet": self._snippet(content),
                    "url": f"https://tieba.baidu.com/p/{thread_id}" if thread_id else "",
                }
            )
        return result

    async def get_thread_detail(self, *, thread_id: Any, pn: int = 1, r: int = 0) -> dict[str, Any]:
        tid = self._as_int(thread_id, "thread_id")
        resp = await self.api.get_thread_detail(tid, pn=pn, r=r)
        data = self._extract_data(resp)
        post_list = self._pick_list(data, "post_list", "list")
        simplified_posts: list[dict[str, Any]] = []
        for item in post_list[:20]:
            if not isinstance(item, dict):
                continue
            simplified_posts.append(
                {
                    "post_id": item.get("post_id") or item.get("id"),
                    "author": item.get("author_name") or item.get("user_name") or item.get("nickname") or "未知",
                    "content": self._snippet(item.get("content") or item.get("text") or item.get("body"), 120),
                }
            )
        title = data.get("title") or data.get("thread_title") or f"帖子 {tid}"
        return {
            "thread_id": tid,
            "title": str(title),
            "url": f"https://tieba.baidu.com/p/{tid}",
            "posts": simplified_posts,
            "raw_data": data,
        }

    async def list_replyme(self, *, pn: int = 1) -> list[dict[str, Any]]:
        resp = await self.api.get_replyme(pn=pn)
        data = self._extract_data(resp)
        raw_items = self._pick_list(data, "reply_list", "list")
        result: list[dict[str, Any]] = []
        for idx, item in enumerate(raw_items[:20], start=1):
            if not isinstance(item, dict):
                continue
            thread_id = item.get("thread_id") or item.get("tid")
            post_id = item.get("post_id") or item.get("pid")
            unread = item.get("unread")
            content = item.get("content") or item.get("reply_content") or ""
            quote_content = item.get("quote_content") or item.get("target_content") or ""
            username = item.get("username") or item.get("user_name") or item.get("nickname") or "未知"
            result.append(
                {
                    "index": idx,
                    "thread_id": thread_id,
                    "post_id": post_id,
                    "username": str(username),
                    "unread": unread,
                    "content": self._snippet(content, 100),
                    "quote_content": self._snippet(quote_content, 100),
                    "url": f"https://tieba.baidu.com/p/{thread_id}?pid={post_id}" if thread_id and post_id else "",
                }
            )
        return result
