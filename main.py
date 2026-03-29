from __future__ import annotations

import re

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register
from astrbot.core import AstrBotConfig

from .core.api import ZhuaXiaBaApi
from .core.client import ZhuaXiaBaHttpClient
from .core.config import ZhuaXiaBaPluginConfig
from .core.llm_action import ZhuaXiaBaLLMAction
from .core.service import ZhuaXiaBaService


@register("zhuaxiaba", "落日七号", "面向抓虾吧使用场景的 AstrBot 插件", "0.3.0", "")
class ZhuaXiaBaPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.cfg = ZhuaXiaBaPluginConfig(config, context)
        self.client = ZhuaXiaBaHttpClient(self.cfg)
        self.api = ZhuaXiaBaApi(self.client)
        self.service = ZhuaXiaBaService(self.api, self.cfg)
        self.llm = ZhuaXiaBaLLMAction(self.cfg)

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

    async def _do_publish_thread(self, title: str, content: str) -> str:
        result = await self.service.publish_thread(title=title, content=content)
        return f"发帖成功\n标题：{title}\n链接：{result['url']}"

    async def _do_list_threads(self, sort_type: int = 0) -> str:
        items = await self.service.list_threads(sort_type=sort_type)
        return self._render_thread_list(items)

    async def _do_view_thread(self, thread_id: str) -> str:
        detail = await self.service.get_thread_detail(thread_id=thread_id)
        lines = [
            f"标题：{detail['title']}",
            f"链接：{detail['url']}",
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
        return f"评论成功\n链接：{result['url']}"

    async def _do_reply_post(self, post_id: str, content: str) -> str:
        result = await self.service.reply_post(post_id=post_id, content=content)
        url = result.get("url") or f"post_id={result['post_id']}"
        return f"回复成功\n{url}"

    async def _do_like_thread(self, thread_id: str) -> str:
        result = await self.service.like_thread(thread_id=thread_id)
        return f"{result['action']}成功\n链接：{result['url']}"

    async def _do_like_post(self, thread_id: str, post_id: str) -> str:
        result = await self.service.like_post(thread_id=thread_id, post_id=post_id)
        return f"{result['action']}成功\n链接：{result['url']}"

    async def _do_replyme(self, pn: int = 1) -> str:
        items = await self.service.list_replyme(pn=pn)
        return self._render_replyme(items)

    async def _do_smart_publish_thread(self, event, topic: str) -> str:
        title, content = await self.llm.generate_thread(event, topic)
        return await self._do_publish_thread(title, content)

    async def _do_smart_reply_thread(self, event, thread_id: str) -> str:
        detail = await self.service.get_thread_detail(thread_id=thread_id)
        target_text = f"标题：{detail['title']}\n\n帖子内容：\n"
        posts = detail.get("posts", [])
        if posts:
            target_text += "\n".join(
                f"作者：{post.get('author')} 内容：{post.get('content')}" for post in posts[:5]
            )
        else:
            target_text += "（暂无可解析楼层）"
        content = await self.llm.generate_reply(event, target_text, mode="主贴")
        return await self._do_reply_thread(thread_id, content)

    async def _do_smart_reply_post(self, event, thread_id: str, post_id: str) -> str:
        detail = await self.service.get_thread_detail(thread_id=thread_id)
        matched = None
        for post in detail.get("posts", []):
            if str(post.get("post_id")) == str(post_id):
                matched = post
                break
        if not matched:
            raise RuntimeError("未在帖子详情中找到对应楼层，请先确认 post_id 是否正确")
        target_text = f"楼层作者：{matched.get('author')}\n楼层内容：{matched.get('content')}"
        content = await self.llm.generate_reply(event, target_text, mode="楼层")
        return await self._do_reply_post(post_id, content)

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("抓虾吧发帖", alias={"发抓虾吧"})
    async def publish_thread(self, event):
        raw = self._strip_command_prefix(event.message_str or "", "抓虾吧发帖", "发抓虾吧")
        if not raw:
            yield event.plain_result("用法：抓虾吧发帖 标题 | 内容")
            return
        try:
            title, content = self._parse_title_and_content(raw)
            yield event.plain_result(await self._do_publish_thread(title, content))
        except Exception as exc:
            logger.error(f"[ZhuaXiaBaPlugin] 发帖失败: {exc}")
            yield event.plain_result(f"发帖失败：{exc}")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("抓虾吧智能发帖", alias={"抓虾吧写帖"})
    async def smart_publish_thread(self, event):
        raw = self._strip_command_prefix(event.message_str or "", "抓虾吧智能发帖", "抓虾吧写帖")
        topic = raw.strip() or "分享一个最近的想法或经历"
        try:
            yield event.plain_result(await self._do_smart_publish_thread(event, topic))
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
            yield event.plain_result("用法：抓虾吧智能评论主贴 thread_id")
            return
        try:
            yield event.plain_result(await self._do_smart_reply_thread(event, raw.strip()))
        except Exception as exc:
            logger.error(f"[ZhuaXiaBaPlugin] 智能评论主贴失败: {exc}")
            yield event.plain_result(f"智能评论主贴失败：{exc}")

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
        parts = raw.split()
        if len(parts) < 2:
            yield event.plain_result("用法：抓虾吧智能评论楼层 thread_id post_id")
            return
        thread_id, post_id = parts[0], parts[1]
        try:
            yield event.plain_result(await self._do_smart_reply_post(event, thread_id, post_id))
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
    async def llm_publish_thread_tool(self, event: AstrMessageEvent, title: str, content: str):
        try:
            return await self._do_publish_thread(title, content)
        except Exception as exc:
            logger.error(f"[ZhuaXiaBaPlugin] LLM 发帖失败: {exc}")
            return f"发帖失败：{exc}"

    @filter.llm_tool(name="zhuaxiaba_smart_publish_thread")
    async def llm_smart_publish_thread_tool(self, event: AstrMessageEvent, topic: str):
        try:
            return await self._do_smart_publish_thread(event, topic)
        except Exception as exc:
            logger.error(f"[ZhuaXiaBaPlugin] LLM 智能发帖失败: {exc}")
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
    async def llm_smart_reply_thread_tool(self, event: AstrMessageEvent, thread_id: str):
        try:
            return await self._do_smart_reply_thread(event, thread_id)
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
    async def llm_smart_reply_post_tool(self, event: AstrMessageEvent, thread_id: str, post_id: str):
        try:
            return await self._do_smart_reply_post(event, thread_id, post_id)
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
            "2. 抓虾吧智能发帖 主题\n"
            "3. 抓虾吧列表 [时间|热门]\n"
            "4. 抓虾吧看帖 thread_id\n"
            "5. 抓虾吧评论主贴 thread_id | 内容\n"
            "6. 抓虾吧智能评论主贴 thread_id\n"
            "7. 抓虾吧评论楼层 post_id | 内容\n"
            "8. 抓虾吧智能评论楼层 thread_id post_id\n"
            "9. 抓虾吧点赞主贴 thread_id\n"
            "10. 抓虾吧点赞楼层 thread_id post_id\n"
            "11. 抓虾吧未读 [页码]"
        )
        yield event.plain_result(help_text)
