from __future__ import annotations

import re
from typing import Optional

from astrbot.api import logger

from .config import ZhuaXiaBaPluginConfig


class ZhuaXiaBaLLMAction:
    def __init__(self, config: ZhuaXiaBaPluginConfig):
        self.cfg = config
        self.context = config.context

    async def _get_persona_prompt(self) -> str:
        try:
            persona_id = (self.cfg.persona_id or "").strip()
            if persona_id:
                persona = await self.context.persona_manager.get_persona(persona_id)
                if persona:
                    prompt = getattr(persona, "system_prompt", None) or getattr(persona, "prompt", None)
                    if prompt:
                        return str(prompt).strip()
        except Exception as e:
            logger.warning(f"[ZhuaXiaBaLLM] 获取人格提示词失败：{e}")
        return ""

    @staticmethod
    def _merge_system_prompt(persona_prompt: str, task_prompt: str) -> str:
        persona_prompt = (persona_prompt or "").strip()
        task_prompt = (task_prompt or "").strip()
        if persona_prompt:
            return f"{persona_prompt}\n\n---\n\n{task_prompt}"
        return task_prompt

    async def _generate_text(self, event, prompt: str, system_prompt: Optional[str] = None) -> str:
        provider_id = None
        current_umo = getattr(event, "unified_msg_origin", None) if event else None
        try:
            if current_umo:
                provider_id = await self.context.get_current_chat_provider_id(umo=current_umo)
        except Exception:
            provider_id = None

        if provider_id:
            kwargs = {
                "chat_provider_id": provider_id,
                "prompt": prompt,
            }
            if system_prompt:
                kwargs["system_prompt"] = system_prompt
            if self.cfg.llm_model_id:
                kwargs["model_id"] = self.cfg.llm_model_id
            if current_umo:
                kwargs["umo"] = current_umo

            try:
                resp = await self.context.llm_generate(**kwargs)
            except TypeError:
                kwargs.pop("umo", None)
                try:
                    resp = await self.context.llm_generate(**kwargs)
                except TypeError:
                    kwargs.pop("model_id", None)
                    resp = await self.context.llm_generate(**kwargs)
            text = getattr(resp, "completion_text", "") or ""
            return text.strip()

        provider = None
        try:
            provider = self.context.get_using_provider()
        except Exception:
            provider = None

        if not provider:
            raise RuntimeError("未找到可用的 LLM 提供商，请先配置默认对话模型")

        kwargs = {
            "prompt": prompt,
            "contexts": [],
            "image_urls": [],
        }
        if system_prompt:
            kwargs["system_prompt"] = system_prompt
        if self.cfg.llm_model_id:
            kwargs["model_id"] = self.cfg.llm_model_id
        if current_umo:
            kwargs["session_id"] = current_umo

        try:
            resp = await provider.text_chat(**kwargs)
        except TypeError:
            kwargs.pop("session_id", None)
            try:
                resp = await provider.text_chat(**kwargs)
            except TypeError:
                kwargs.pop("model_id", None)
                resp = await provider.text_chat(**kwargs)

        text = getattr(resp, "completion_text", "") or ""
        return text.strip()

    @staticmethod
    def _clean_text(text: str) -> str:
        text = (text or "").strip()
        text = re.sub(r'^```(?:\w+)?\s*', '', text)
        text = re.sub(r'\s*```$', '', text)
        text = text.strip().strip('"\'“”‘’')
        return text.strip()

    async def generate_thread(self, event, topic: str) -> tuple[str, str]:
        persona_prompt = await self._get_persona_prompt()
        task_prompt = (
            f"{self.cfg.llm_system_prompt}\n\n"
            "任务：为抓虾吧生成一条适合公开发布的新帖子。\n"
            "请严格按如下格式输出：\n"
            "标题：<标题>\n"
            "正文：<正文>\n\n"
            "要求：\n"
            "1. 标题不要超过30个字符\n"
            "2. 正文不要超过1000个字符\n"
            "3. 语气自然，像真实吧友\n"
            "4. 不要输出解释、备注、前言、后记\n"
            f"5. 围绕主题生成：{topic}"
        )
        system_prompt = self._merge_system_prompt(persona_prompt, task_prompt)
        result = self._clean_text(await self._generate_text(event, prompt=topic, system_prompt=system_prompt))

        title_match = re.search(r"标题[:：]\s*(.+)", result)
        content_match = re.search(r"正文[:：]\s*([\s\S]+)$", result)
        if title_match and content_match:
            title = title_match.group(1).strip()
            content = content_match.group(1).strip()
            return title, content

        lines = [line.strip() for line in result.splitlines() if line.strip()]
        if len(lines) >= 2:
            title = lines[0][:30].strip()
            content = "\n".join(lines[1:]).strip()
            return title, content

        raise RuntimeError("LLM 未按预期生成标题和正文")

    async def generate_reply(self, event, target_text: str, mode: str = "主贴") -> str:
        persona_prompt = await self._get_persona_prompt()
        task_prompt = (
            f"{self.cfg.llm_system_prompt}\n\n"
            f"任务：针对抓虾吧的{mode}内容生成一条自然的评论。\n"
            "要求：\n"
            "1. 只输出评论正文\n"
            "2. 不要输出解释或前缀\n"
            "3. 评论要自然、具体，避免敷衍\n"
            "4. 字数适中，尽量像贴吧真实互动\n"
        )
        system_prompt = self._merge_system_prompt(persona_prompt, task_prompt)
        result = self._clean_text(await self._generate_text(event, prompt=target_text, system_prompt=system_prompt))
        if not result:
            raise RuntimeError("LLM 生成评论为空")
        return result
