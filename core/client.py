from __future__ import annotations

from typing import Any

import aiohttp

from .config import ZhuaXiaBaPluginConfig


class ZhuaXiaBaHttpClient:
    BASE_URL = "https://tieba.baidu.com"

    def __init__(self, config: ZhuaXiaBaPluginConfig):
        self.config = config
        self._session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=self.config.timeout)
        )

    async def close(self) -> None:
        await self._session.close()

    def _authorization(self) -> str:
        token = self.config.tb_token
        if not token:
            raise RuntimeError("未配置 TB_TOKEN，请先在插件设置中填写")
        return token

    async def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        headers = {
            "Authorization": self._authorization(),
            "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
        }
        async with self._session.get(
            f"{self.BASE_URL}{path}", params=params, headers=headers
        ) as resp:
            return await self._parse_response(resp)

    async def post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        headers = {
            "Authorization": self._authorization(),
            "Content-Type": "application/json",
        }
        async with self._session.post(
            f"{self.BASE_URL}{path}", json=payload, headers=headers
        ) as resp:
            return await self._parse_response(resp)

    async def _parse_response(self, resp: aiohttp.ClientResponse) -> dict[str, Any]:
        text = await resp.text()
        if resp.status != 200:
            raise RuntimeError(f"贴吧接口请求失败：HTTP {resp.status}，响应：{text[:300]}")
        try:
            data = await resp.json(content_type=None)
        except Exception as exc:
            raise RuntimeError(f"贴吧接口返回了非 JSON 内容：{text[:300]}") from exc

        errno = data.get("errno")
        if errno not in (0, "0", None):
            errmsg = data.get("errmsg") or data.get("error") or "未知错误"
            raise RuntimeError(f"贴吧接口返回失败：{errmsg} (errno={errno})")
        return data
