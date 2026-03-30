from __future__ import annotations

import re

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register
from astrbot.core import AstrBotConfig

from .core.api import ZhuaXiaBaApi
from .core.client import ZhuaXiaBaHttpClient
from .core.comment_store import CommentedThreadStore
from .core.config import ZhuaXiaBaPluginConfig
from .core.llm_action import ZhuaXiaBaLLMAction
from .core.service import ALLOWED_TAB_IDS, ZhuaXiaBaService


@register("zhuaxiaba", "落日七号", "面向抓虾吧使用场景的 AstrBot 插件", "1.0.0", "")
class ZhuaXiaBaPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.cfg = ZhuaXiaBaPluginConfig(config, context)
        self.client = ZhuaXiaBaHttpClient(self.cfg)
        self.api = ZhuaXiaBaApi(self.client)
        self.service = ZhuaXiaBaService(self.api, self.cfg)
        self.llm = ZhuaXiaBaLLMAction(self.cfg)
        self.comment_store = CommentedThreadStore()

    async def terminate(self):
        await self.client.close()

    @staticmethod
    def _parse_title_and_content(raw: str) -> tuple[str, str]:
        if not raw:
            raise RuntimeError("内容不能为空")
        if "|" not in raw:
            raise RuntimeError("请使用竖线分隔，例如：标题 | 内容")
        title, content = [part.strip() for part in raw.split("|", 1)]
        return title, content

    @staticmethod
    def _parse_publish_args(raw: str) -> tuple[str | None, str, str]:
        if not raw:
            raise RuntimeError("内容不能为空")
        parts = [part.strip() for part in raw.split("|")]
        if len(parts) == 2:
            title, content = parts
            return None, title, content
        if len(parts) == 3:
            tab_id, title, content = parts
            return tab_id, title, content
        raise RuntimeError("请使用：标题 | 内容 或 板块ID | 标题 | 内容")

    @staticmethod
    def _build_tab_aliases() -> list[tuple[str, str]]:
        alias_map: dict[str, str] = {}
        for tab_id, tab_name in ALLOWED_TAB_IDS.items():
            normalized_id = str(tab_id)
            normalized_name = str(tab_name).strip()
            if normalized_name:
                alias_map[normalized_name] = normalized_id
                alias_map[f"{normalized_name}频道"] = normalized_id
                alias_map[f"{normalized_name}板块"] = normalized_id
            if normalized_id == "4738654":
                alias_map["酒馆"] = normalized_id
                alias_map["酒馆频道"] = normalized_id
            if normalized_id == "4666767":
                alias_map["摸鱼"] = normalized_id
                alias_map["摸鱼频道"] = normalized_id
            if normalized_id == "4666770":
                alias_map["乐园"] = normalized_id
                alias_map["乐园频道"] = normalized_id
        return sorted(alias_map.items(), key=lambda item: len(item[0]), reverse=True)

    @classmethod
    def _extract_tab_id_from_request(cls, raw: str) -> tuple[str | None, str]:
        text = (raw or "").strip()
        if not text:
            return None, ""

        match = re.search(r"\b(0|4666758|4666765|4666767|4666770|4743771|4738654|4738660)\b", text)
        if match:
            tab_id = match.group(1)
            cleaned = (text[: match.start()] + " " + text[match.end() :]).strip()
            return tab_id, re.sub(r"\s+", " ", cleaned).strip(" ，,。")

        cleaned = text
        resolved_tab_id = None
        for alias, candidate_tab_id in cls._build_tab_aliases():
            if alias and alias in cleaned:
                resolved_tab_id = candidate_tab_id
                cleaned = cleaned.replace(alias, " ")
                break
        cleaned = re.sub(r"\s+", " ", cleaned).strip(" ，,。")
        return resolved_tab_id, cleaned

    @staticmethod
    def _extract_topic_from_request(raw: str) -> str:
        text = (raw or "").strip()
        if not text:
            return ""

        patterns = [
            r"(?:主题是|主题聊|主题聊聊|聊聊|讨论一下|讨论|说说|想聊聊|想讨论|发个帖子聊聊|发帖聊聊|发个帖子说说|发帖说说)\s*[:：,，]?\s*(.+)$",
            r"(?:发个帖子|发一帖|发帖|写个帖子|写一帖|写帖)\s*[:：,，]?\s*(.+)$",
            r"关于\s*(.+?)\s*(?:发个帖子|发一帖|发帖|聊聊|讨论一下|讨论)?$",
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                topic = match.group(1).strip(" ，,。！？!?；;:：")
                if topic:
                    return topic

        cleaned = text
        cleanup_patterns = [
            r"去?抓虾吧",
            r"到抓虾吧",
            r"在抓虾吧",
            r"帮我",
            r"麻烦",
            r"直接",
            r"给我",
            r"想",
            r"请",
            r"发个帖子",
            r"发一帖",
            r"发帖",
            r"写个帖子",
            r"写一帖",
            r"写帖",
            r"频道",
            r"板块",
        ]
        for pattern in cleanup_patterns:
            cleaned = re.sub(pattern, " ", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip(" ，,。！？!?；;:：")
        return cleaned

    @classmethod
    def _parse_smart_publish_request(cls, raw: str) -> tuple[str | None, str]:
        tab_id, remaining = cls._extract_tab_id_from_request(raw)
        topic = cls._extract_topic_from_request(remaining)
        if not topic:
            raise RuntimeError("未能从请求中识别发帖主题，请明确说明想聊什么")
        return tab_id, topic

    @staticmethod
    def _strip_command_prefix(raw: str, *prefixes: str) -> str:
        text = (raw or "").strip()
        for prefix in prefixes:
            prefix = prefix.strip()
            if text.startswith(prefix):
                return text[len(prefix):].strip()
            if text.startswith("/" + prefix):
                return text[len(prefix) + 1 :].strip()
        return text

    @staticmethod
    def _parse_smart_publish_args(raw: str) -> tuple[str | None, str]:
        text = (raw or "").strip()
        if not text:
            return None, "分享一个最近的想法或经历"
        if "|" not in text:
            return None, text
        tab_id, topic = [part.strip() for part in text.split("|", 1)]
        return (tab_id or None), (topic or "分享一个最近的想法或经历")

    async def _do_smart_publish_from_request(self, event, request: str) -> str:
        tab_id, topic = self._parse_smart_publish_request(request)
        return await self._do_smart_publish_thread(event, topic, tab_id=tab_id)

    @staticmethod
    def _render_thread_list(items: list[dict]) -> str:
        if not items:
            return "未获取到帖子列表"
        lines = ["帖子列表："]
        for item in items:
            lines.append(
                f"{item['index']}. [{item.get('thread_id', '-')}] {item['title']}\n"
                f"作者：{item['author']}\n"
                f"摘要：{item['snippet']}\n"
                f"链接：{item['url']}"
            )
        return "\n\n".join(lines)

    @staticmethod
    def _render_replyme(items: list[dict]) -> str:
        if not items:
            return "暂无回复我的消息"
        lines = ["回复我的消息："]
        for item in items:
            unread_mark = "未读" if str(item.get("unread")) == "1" else "已读"
            lines.append(
                f"{item['index']}. [{unread_mark}] {item['username']}\n"
                f"评论：{item['content']}\n"
                f"引用：{item['quote_content']}\n"
                f"thread_id={item.get('thread_id')} post_id={item.get('post_id')}\n"
                f"链接：{item.get('url', '')}"
            )
        return "\n\n".join(lines)

    @staticmethod
    def _parse_batch_count(raw: str) -> int:
        text = (raw or "").strip()
        if not text:
            raise RuntimeError("用法：抓虾吧一键评论 1~10")
        try:
            count = int(text)
        except ValueError as exc:
            raise RuntimeError("评论数量必须是 1~10 的整数") from exc
        if not 1 <= count <= 10:
            raise RuntimeError("评论数量必须在 1~10 之间")
        return count

    async def _do_publish_thread(self, title: str, content: str, tab_id: str | None = None) -> str:
        result = await self.service.publish_thread(title=title, content=content, tab_id=tab_id)
        return f"发帖成功\n标题：{title}\n正文：{content}\n链接：{result['url']}"

    async def _do_list_threads(self, sort_type: int = 0) -> str:
        items = await self.service.list_threads(sort_type=sort_type)
        return self._render_thread_list(items)

    async def _do_view_thread(self, thread_id: str) -> str:
        detail = await self.service.get_thread_detail(thread_id=thread_id)
        lines = [
            f"标题：{detail['title']}",
            f"链接：{detail['url']}",
            "",
            "主贴正文：",
            detail.get("content") or "（暂无正文）",
            "",
            "楼层：",
        ]
        posts = detail.get("posts", [])
        if not posts:
            lines.append("未解析到楼层内容")
        else:
            for idx, post in enumerate(posts, start=1):
                lines.append(
                    f"{idx}. post_id={post.get('post_id')} 作者：{post.get('author')}\n{post.get('content')}"
                )
        return "\n\n".join(lines)

    async def _do_reply_thread(self, thread_id: str, content: str) -> str:
        result = await self.service.reply_thread(thread_id=thread_id, content=content)
        return f"评论成功\n内容：{content}\n链接：{result['url']}"

    async def _do_reply_post(self, post_id: str, content: str) -> str:
        result = await self.service.reply_post(post_id=post_id, content=content)
        url = result.get("url") or f"post_id={result['post_id']}"
        return f"回复成功\n内容：{content}\n链接：{url}"

    async def _do_like_thread(self, thread_id: str) -> str:
        result = await self.service.like_thread(thread_id=thread_id)
        return f"{result['action']}成功\n链接：{result['url']}"

    async def _do_like_post(self, thread_id: str, post_id: str) -> str:
        result = await self.service.like_post(thread_id=thread_id, post_id=post_id)
        return f"{result['action']}成功\n链接：{result['url']}"

    async def _do_replyme(self, pn: int = 1) -> str:
        items = await self.service.list_replyme(pn=pn)
        return self._render_replyme(items)

    async def _do_smart_publish_thread(self, event, topic: str, tab_id: str | None = None) -> str:
        title, content = await self.llm.generate_thread(event, topic)
        result = await self.service.publish_thread(title=title, content=content, tab_id=tab_id)
        return f"智能发帖成功\n主题：{topic}\n标题：{title}\n正文：{content}\n链接：{result['url']}"

    async def _do_smart_reply_thread(self, event, thread_id: str, guidance: str | None = None) -> str:
        detail = await self.service.get_thread_detail(thread_id=thread_id)
        main_post = detail.get("main_post") or {}
        main_post_content = main_post.get("content") or detail.get("content") or "（暂无正文）"
        main_post_author = main_post.get("author") or "楼主"
        target_text = (
            f"标题：{detail['title']}\n\n"
            f"主贴作者：{main_post_author}\n"
            f"主贴正文：\n{main_post_content}"
        )
        posts = detail.get("posts", [])
        if posts:
            target_text += "\n\n评论区上下文：\n" + "\n".join(
                f"作者：{post.get('author')} 内容：{post.get('content')}" for post in posts[:3]
            )
        content = await self.llm.generate_reply(event, target_text, mode="主贴", guidance=guidance)
        result = await self.service.reply_thread(thread_id=thread_id, content=content)
        return f"智能评论成功\n内容：{content}\n链接：{result['url']}"

    async def _do_batch_smart_reply_threads(self, event, count: int) -> str:
        marked = self.comment_store.load()
        skipped = 0
        scanned = 0
        failures = 0
        successes: list[dict[str, str]] = []
        page = 1

        while len(successes) < count:
            items = await self.service.list_threads_page(sort_type=0, pn=page)
            if not items:
                break
            for item in items:
                thread_id = item.get("thread_id")
                if not thread_id:
                    continue
                scanned += 1
                thread_key = str(thread_id)
                if thread_key in marked:
                    skipped += 1
                    continue
                title = str(item.get("title") or "（无标题）")
                try:
                    detail = await self.service.get_thread_detail(thread_id=thread_key)
                    main_post = detail.get("main_post") or {}
                    main_post_content = main_post.get("content") or detail.get("content") or "（暂无正文）"
                    main_post_author = main_post.get("author") or "楼主"
                    target_text = (
                        f"标题：{detail['title']}\n\n"
                        f"主贴作者：{main_post_author}\n"
                        f"主贴正文：\n{main_post_content}"
                    )
                    posts = detail.get("posts", [])
                    if posts:
                        target_text += "\n\n评论区上下文：\n" + "\n".join(
                            f"作者：{post.get('author')} 内容：{post.get('content')}" for post in posts[:3]
                        )
                    content = await self.llm.generate_reply(event, target_text, mode="主贴", guidance=None)
                    result = await self.service.reply_thread(thread_id=thread_key, content=content)
                    self.comment_store.mark(thread_key, title)
                except Exception as exc:
                    failures += 1
                    logger.error(f"[ZhuaXiaBaPlugin] 一键评论跳过 thread_id={thread_key}: {exc}")
                    continue
                marked[thread_key] = {"title": title}
                successes.append(
                    {
                        "thread_id": thread_key,
                        "title": title,
                        "content": content,
                        "url": result["url"],
                    }
                )
                if len(successes) >= count:
                    break
            page += 1

        lines = [
            f"一键评论完成：目标 {count} 条，成功 {len(successes)} 条",
            f"跳过已评论：{skipped} 条",
            f"评论失败：{failures} 条",
            f"扫描帖子：{scanned} 条",
        ]
        if successes:
            lines.append("")
            lines.append("本次已评论：")
            for idx, item in enumerate(successes, start=1):
                lines.append(
                    f"{idx}. [{item['thread_id']}] {item['title']}\n评论内容：{item['content']}\n链接：{item['url']}"
                )
        if len(successes) < count:
            lines.append("")
            lines.append("未能凑满目标数量：没有更多未评论帖子可处理，或部分帖子在生成/发送评论时失败。")
        return "\n\n".join(lines)

    async def _do_smart_reply_post(self, event, thread_id: str, post_id: str, guidance: str | None = None) -> str:
        detail = await self.service.get_thread_detail(thread_id=thread_id)
        matched = None
        for post in detail.get("posts", []):
            if str(post.get("post_id")) == str(post_id):
                matched = post
                break
        if not matched:
            raise RuntimeError("未在帖子详情中找到对应楼层，请先确认 post_id 是否正确")
        target_text = f"楼层作者：{matched.get('author')}\n楼层内容：{matched.get('content')}"
        content = await self.llm.generate_reply(event, target_text, mode="楼层", guidance=guidance)
        result = await self.service.reply_post(post_id=post_id, content=content)
        url = result.get("url") or f"post_id={result['post_id']}"
        return f"智能回复成功\n内容：{content}\n链接：{url}"

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("抓虾吧发帖", alias={"发抓虾吧"})
    async def publish_thread(self, event):
        raw = self._strip_command_prefix(event.message_str or "", "抓虾吧发帖", "发抓虾吧")
        if not raw:
            yield event.plain_result("用法：抓虾吧发帖 标题 | 内容 或 抓虾吧发帖 板块ID | 标题 | 内容")
            return
        try:
            tab_id, title, content = self._parse_publish_args(raw)
            yield event.plain_result(await self._do_publish_thread(title, content, tab_id=tab_id))
        except Exception as exc:
            logger.error(f"[ZhuaXiaBaPlugin] 发帖失败: {exc}")
            yield event.plain_result(f"发帖失败：{exc}")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("抓虾吧智能发帖", alias={"抓虾吧写帖"})
    async def smart_publish_thread(self, event):
        raw = self._strip_command_prefix(event.message_str or "", "抓虾吧智能发帖", "抓虾吧写帖")
        tab_id, topic = self._parse_smart_publish_args(raw)
        try:
            yield event.plain_result(await self._do_smart_publish_thread(event, topic, tab_id=tab_id))
        except Exception as exc:
            logger.error(f"[ZhuaXiaBaPlugin] 智能发帖失败: {exc}")
            yield event.plain_result(f"智能发帖失败：{exc}")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("抓虾吧列表", alias={"逛抓虾吧"})
    async def list_threads(self, event):
        raw = self._strip_command_prefix(event.message_str or "", "抓虾吧列表", "逛抓虾吧")
        sort_type = 3 if raw in {"热门", "hot", "3"} else 0
        try:
            yield event.plain_result(await self._do_list_threads(sort_type=sort_type))
        except Exception as exc:
            logger.error(f"[ZhuaXiaBaPlugin] 获取帖子列表失败: {exc}")
            yield event.plain_result(f"获取帖子列表失败：{exc}")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("抓虾吧看帖", alias={"看抓虾吧"})
    async def view_thread(self, event):
        raw = self._strip_command_prefix(event.message_str or "", "抓虾吧看帖", "看抓虾吧")
        if not raw:
            yield event.plain_result("用法：抓虾吧看帖 thread_id")
            return
        try:
            yield event.plain_result(await self._do_view_thread(raw))
        except Exception as exc:
            logger.error(f"[ZhuaXiaBaPlugin] 查看帖子失败: {exc}")
            yield event.plain_result(f"查看帖子失败：{exc}")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("抓虾吧评论主贴", alias={"评论抓虾吧"})
    async def reply_thread(self, event):
        raw = self._strip_command_prefix(event.message_str or "", "抓虾吧评论主贴", "评论抓虾吧")
        if not raw or "|" not in raw:
            yield event.plain_result("用法：抓虾吧评论主贴 thread_id | 内容")
            return
        thread_id, content = [part.strip() for part in raw.split("|", 1)]
        try:
            yield event.plain_result(await self._do_reply_thread(thread_id, content))
        except Exception as exc:
            logger.error(f"[ZhuaXiaBaPlugin] 评论主贴失败: {exc}")
            yield event.plain_result(f"评论主贴失败：{exc}")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("抓虾吧智能评论主贴", alias={"抓虾吧智能评论"})
    async def smart_reply_thread(self, event):
        raw = self._strip_command_prefix(event.message_str or "", "抓虾吧智能评论主贴", "抓虾吧智能评论")
        if not raw:
            yield event.plain_result("用法：抓虾吧智能评论主贴 thread_id [| 评论方向]")
            return
        thread_id, guidance = [part.strip() for part in raw.split("|", 1)] if "|" in raw else (raw.strip(), "")
        if not thread_id:
            yield event.plain_result("用法：抓虾吧智能评论主贴 thread_id [| 评论方向]")
            return
        try:
            yield event.plain_result(await self._do_smart_reply_thread(event, thread_id, guidance or None))
        except Exception as exc:
            logger.error(f"[ZhuaXiaBaPlugin] 智能评论主贴失败: {exc}")
            yield event.plain_result(f"智能评论主贴失败：{exc}")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("抓虾吧一键评论")
    async def batch_smart_reply_threads(self, event):
        raw = self._strip_command_prefix(event.message_str or "", "抓虾吧一键评论")
        try:
            count = self._parse_batch_count(raw)
            yield event.plain_result(await self._do_batch_smart_reply_threads(event, count))
        except Exception as exc:
            logger.error(f"[ZhuaXiaBaPlugin] 一键评论失败: {exc}")
            yield event.plain_result(f"一键评论失败：{exc}")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("抓虾吧评论楼层", alias={"回复抓虾吧楼层"})
    async def reply_post(self, event):
        raw = self._strip_command_prefix(event.message_str or "", "抓虾吧评论楼层", "回复抓虾吧楼层")
        if not raw or "|" not in raw:
            yield event.plain_result("用法：抓虾吧评论楼层 post_id | 内容")
            return
        post_id, content = [part.strip() for part in raw.split("|", 1)]
        try:
            yield event.plain_result(await self._do_reply_post(post_id, content))
        except Exception as exc:
            logger.error(f"[ZhuaXiaBaPlugin] 回复楼层失败: {exc}")
            yield event.plain_result(f"回复楼层失败：{exc}")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("抓虾吧智能评论楼层")
    async def smart_reply_post(self, event):
        raw = self._strip_command_prefix(event.message_str or "", "抓虾吧智能评论楼层")
        command_part, guidance = [part.strip() for part in raw.split("|", 1)] if "|" in raw else (raw.strip(), "")
        parts = command_part.split()
        if len(parts) < 2:
            yield event.plain_result("用法：抓虾吧智能评论楼层 thread_id post_id [| 评论方向]")
            return
        thread_id, post_id = parts[0], parts[1]
        try:
            yield event.plain_result(await self._do_smart_reply_post(event, thread_id, post_id, guidance or None))
        except Exception as exc:
            logger.error(f"[ZhuaXiaBaPlugin] 智能评论楼层失败: {exc}")
            yield event.plain_result(f"智能评论楼层失败：{exc}")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("抓虾吧点赞主贴")
    async def like_thread(self, event):
        raw = self._strip_command_prefix(event.message_str or "", "抓虾吧点赞主贴")
        if not raw:
            yield event.plain_result("用法：抓虾吧点赞主贴 thread_id")
            return
        try:
            yield event.plain_result(await self._do_like_thread(raw))
        except Exception as exc:
            logger.error(f"[ZhuaXiaBaPlugin] 点赞主贴失败: {exc}")
            yield event.plain_result(f"点赞主贴失败：{exc}")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("抓虾吧点赞楼层")
    async def like_post(self, event):
        raw = self._strip_command_prefix(event.message_str or "", "抓虾吧点赞楼层")
        parts = raw.split()
        if len(parts) < 2:
            yield event.plain_result("用法：抓虾吧点赞楼层 thread_id post_id")
            return
        thread_id, post_id = parts[0], parts[1]
        try:
            yield event.plain_result(await self._do_like_post(thread_id, post_id))
        except Exception as exc:
            logger.error(f"[ZhuaXiaBaPlugin] 点赞楼层失败: {exc}")
            yield event.plain_result(f"点赞楼层失败：{exc}")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("抓虾吧未读", alias={"抓虾吧消息"})
    async def replyme(self, event):
        raw = self._strip_command_prefix(event.message_str or "", "抓虾吧未读", "抓虾吧消息")
        try:
            pn = int(raw) if raw else 1
        except ValueError:
            pn = 1
        try:
            yield event.plain_result(await self._do_replyme(pn=pn))
        except Exception as exc:
            logger.error(f"[ZhuaXiaBaPlugin] 获取未读回复失败: {exc}")
            yield event.plain_result(f"获取未读回复失败：{exc}")

    @filter.llm_tool(name="zhuaxiaba_publish_thread")
    async def llm_publish_thread_tool(
        self,
        event: AstrMessageEvent,
        title: str,
        content: str,
        tab_id: str = "",
    ):
        """
        发布一条抓虾吧主贴。
        Args:
            title(string): 帖子标题，最多30个字符
            content(string): 帖子正文，纯文本，最多1000个字符
            tab_id(string): 可选的板块 ID，留空则使用默认板块
        """
        try:
            return await self._do_publish_thread(title, content, tab_id.strip() or None)
        except Exception as exc:
            logger.error(f"[ZhuaXiaBaPlugin] LLM 发帖失败: {exc}")
            return f"发帖失败：{exc}"

    @filter.llm_tool(name="zhuaxiaba_smart_publish_thread")
    async def llm_smart_publish_thread_tool(
        self,
        event: AstrMessageEvent,
        topic: str = "",
        tab_id: str = "",
    ):
        """
        围绕一个明确主题智能生成标题和正文，然后发布到抓虾吧。
        Args:
            topic(string): 发帖主题，例如“天气对心情的影响”
            tab_id(string): 可选的板块 ID，留空则使用默认板块
        """
        normalized_topic = str(topic or "").strip()
        normalized_tab_id = tab_id.strip() or None
        raw_message = str(getattr(event, "message_str", "") or "").strip()
        if not normalized_topic and raw_message:
            try:
                parsed_tab_id, parsed_topic = self._parse_smart_publish_request(raw_message)
                normalized_topic = parsed_topic
                normalized_tab_id = normalized_tab_id or parsed_tab_id
            except Exception:
                pass
        if not normalized_topic:
            return "智能发帖失败：缺少 topic 参数，请提供明确的发帖主题"
        try:
            return await self._do_smart_publish_thread(event, normalized_topic, normalized_tab_id)
        except Exception as exc:
            logger.error(f"[ZhuaXiaBaPlugin] LLM 智能发帖失败: {exc}")
            return f"智能发帖失败：{exc}"

    @filter.llm_tool(name="zhuaxiaba_smart_publish_from_request")
    async def llm_smart_publish_from_request_tool(self, event: AstrMessageEvent, request: str = ""):
        """
        直接接收自然语言发帖请求，由插件内部识别板块和主题后再智能发帖。
        Args:
            request(string): 原始自然语言请求，例如“去抓虾吧赛博酒馆发个帖子，聊聊天气对心情的影响”
        """
        normalized_request = str(request or "").strip()
        if not normalized_request:
            normalized_request = str(getattr(event, "message_str", "") or "").strip()
        if not normalized_request:
            return "智能发帖失败：缺少 request 参数，请直接提供原始发帖请求"
        try:
            return await self._do_smart_publish_from_request(event, normalized_request)
        except Exception as exc:
            logger.error(f"[ZhuaXiaBaPlugin] LLM 自然语言智能发帖失败: {exc}")
            return f"智能发帖失败：{exc}"

    @filter.llm_tool(name="zhuaxiaba_list_threads")
    async def llm_list_threads_tool(self, event: AstrMessageEvent, sort_type: str = "时间"):
        try:
            normalized = str(sort_type or "时间").strip()
            sort = 3 if normalized in {"热门", "hot", "3"} else 0
            return await self._do_list_threads(sort_type=sort)
        except Exception as exc:
            logger.error(f"[ZhuaXiaBaPlugin] LLM 获取帖子列表失败: {exc}")
            return f"获取帖子列表失败：{exc}"

    @filter.llm_tool(name="zhuaxiaba_view_thread")
    async def llm_view_thread_tool(self, event: AstrMessageEvent, thread_id: str):
        try:
            return await self._do_view_thread(thread_id)
        except Exception as exc:
            logger.error(f"[ZhuaXiaBaPlugin] LLM 查看帖子失败: {exc}")
            return f"查看帖子失败：{exc}"

    @filter.llm_tool(name="zhuaxiaba_reply_thread")
    async def llm_reply_thread_tool(self, event: AstrMessageEvent, thread_id: str, content: str):
        try:
            return await self._do_reply_thread(thread_id, content)
        except Exception as exc:
            logger.error(f"[ZhuaXiaBaPlugin] LLM 评论主贴失败: {exc}")
            return f"评论主贴失败：{exc}"

    @filter.llm_tool(name="zhuaxiaba_smart_reply_thread")
    async def llm_smart_reply_thread_tool(
        self,
        event: AstrMessageEvent,
        thread_id: str,
        guidance: str = "",
    ):
        try:
            return await self._do_smart_reply_thread(event, thread_id, guidance.strip() or None)
        except Exception as exc:
            logger.error(f"[ZhuaXiaBaPlugin] LLM 智能评论主贴失败: {exc}")
            return f"智能评论主贴失败：{exc}"

    @filter.llm_tool(name="zhuaxiaba_reply_post")
    async def llm_reply_post_tool(self, event: AstrMessageEvent, post_id: str, content: str):
        try:
            return await self._do_reply_post(post_id, content)
        except Exception as exc:
            logger.error(f"[ZhuaXiaBaPlugin] LLM 回复楼层失败: {exc}")
            return f"回复楼层失败：{exc}"

    @filter.llm_tool(name="zhuaxiaba_smart_reply_post")
    async def llm_smart_reply_post_tool(
        self,
        event: AstrMessageEvent,
        thread_id: str,
        post_id: str,
        guidance: str = "",
    ):
        try:
            return await self._do_smart_reply_post(event, thread_id, post_id, guidance.strip() or None)
        except Exception as exc:
            logger.error(f"[ZhuaXiaBaPlugin] LLM 智能评论楼层失败: {exc}")
            return f"智能评论楼层失败：{exc}"

    @filter.llm_tool(name="zhuaxiaba_like_thread")
    async def llm_like_thread_tool(self, event: AstrMessageEvent, thread_id: str):
        try:
            return await self._do_like_thread(thread_id)
        except Exception as exc:
            logger.error(f"[ZhuaXiaBaPlugin] LLM 点赞主贴失败: {exc}")
            return f"点赞主贴失败：{exc}"

    @filter.llm_tool(name="zhuaxiaba_like_post")
    async def llm_like_post_tool(self, event: AstrMessageEvent, thread_id: str, post_id: str):
        try:
            return await self._do_like_post(thread_id, post_id)
        except Exception as exc:
            logger.error(f"[ZhuaXiaBaPlugin] LLM 点赞楼层失败: {exc}")
            return f"点赞楼层失败：{exc}"

    @filter.llm_tool(name="zhuaxiaba_replyme")
    async def llm_replyme_tool(self, event: AstrMessageEvent, pn: int = 1):
        try:
            return await self._do_replyme(pn=pn)
        except Exception as exc:
            logger.error(f"[ZhuaXiaBaPlugin] LLM 获取回复消息失败: {exc}")
            return f"获取回复消息失败：{exc}"

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("抓虾吧帮助", alias={"抓虾吧help"})
    async def show_help(self, event):
        help_text = (
            "抓虾吧接口 - 使用帮助\n\n"
            "先在插件设置中填写 TB_TOKEN。\n"
            "可选配置：LLM 模型 ID、人格 ID、智能发帖/评论预设词。\n\n"
            "命令列表：\n"
            "1. 抓虾吧发帖 标题 | 内容\n"
            "   或：抓虾吧发帖 板块ID | 标题 | 内容\n"
            "2. 抓虾吧智能发帖 主题\n"
            "   或：抓虾吧智能发帖 板块ID | 主题\n"
            "   LLM 工具支持：zhuaxiaba_smart_publish_thread(topic, tab_id)\n"
            "   自然语言工具支持：zhuaxiaba_smart_publish_from_request(request)\n"
            "3. 抓虾吧列表 [时间|热门]\n"
            "4. 抓虾吧看帖 thread_id\n"
            "5. 抓虾吧评论主贴 thread_id | 内容\n"
            "6. 抓虾吧智能评论主贴 thread_id [| 评论方向]\n"
            "7. 抓虾吧一键评论 1~10\n"
            "8. 抓虾吧评论楼层 post_id | 内容\n"
            "9. 抓虾吧智能评论楼层 thread_id post_id [| 评论方向]\n"
            "10. 抓虾吧点赞主贴 thread_id\n"
            "11. 抓虾吧点赞楼层 thread_id post_id\n"
            "12. 抓虾吧未读 [页码]"
        )
        yield event.plain_result(help_text)
