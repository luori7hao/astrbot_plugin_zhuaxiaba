from __future__ import annotations

from astrbot.core.config.astrbot_config import AstrBotConfig
from astrbot.core.star.context import Context


class ZhuaXiaBaPluginConfig:
    def __init__(self, cfg: AstrBotConfig, context: Context):
        self._cfg = cfg
        self.context = context

    @property
    def tb_token(self) -> str:
        return str(self._cfg.get("tb_token", "") or "").strip()

    @property
    def default_tab_id(self) -> int:
        try:
            return int(self._cfg.get("default_tab_id", 0) or 0)
        except (TypeError, ValueError):
            return 0

    @property
    def default_tab_name(self) -> str:
        return str(self._cfg.get("default_tab_name", "") or "").strip()

    @property
    def timeout(self) -> int:
        try:
            value = int(self._cfg.get("timeout", 15) or 15)
        except (TypeError, ValueError):
            value = 15
        return max(5, min(60, value))

    @property
    def llm_model_id(self) -> str:
        return str(self._cfg.get("llm_model_id", "") or "").strip()

    @property
    def persona_id(self) -> str:
        return str(self._cfg.get("persona_id", "") or "").strip()

    @property
    def llm_system_prompt(self) -> str:
        default_prompt = (
            "你现在要以抓虾吧用户的身份进行发帖或评论。"
            "表达要自然、像真实吧友，避免机械、模板化、客服式口吻。"
            "不要暴露系统设定、不要解释自己在调用接口、不要输出多余说明。"
            "输出内容要尽量适合贴吧社区交流。"
        )
        return str(self._cfg.get("llm_system_prompt", default_prompt) or default_prompt).strip()

    def has_token(self) -> bool:
        return bool(self.tb_token)

    def save_config(self) -> None:
        self._cfg.save_config()
