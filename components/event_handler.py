"""文件接收事件处理器。

监听 ON_MESSAGE_RECEIVED 事件，当收到符合白名单条件的文件消息时，
通过适配器命令获取文件下载链接并下载到本地。
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any, cast

from src.app.plugin_system.api import adapter_api
from src.app.plugin_system.api.log_api import get_logger
from src.core.components.base.event_handler import BaseEventHandler
from src.core.components.types import EventType
from src.core.models.message import Message, MessageType
from src.kernel.event import EventDecision

from .config import FileReaderConfig

logger = get_logger("file_reader")


class FileReceiverHandler(BaseEventHandler):
    """监听文件消息并自动下载到本地。"""

    handler_name = "file_receiver"
    handler_description = "监听文件消息，根据白名单过滤后下载到本地"
    weight = 50
    intercept_message = False
    init_subscribe = [EventType.ON_MESSAGE_RECEIVED]

    async def execute(
        self, event_name: str, params: dict[str, Any]
    ) -> tuple[EventDecision, dict[str, Any]]:
        """处理消息接收事件。

        从 params 中提取 message 和 envelope，判断是否为文件消息，
        若满足白名单条件则下载文件。

        Args:
            event_name: 事件名称
            params: 事件参数，包含 message、envelope、adapter_signature

        Returns:
            (EventDecision.SUCCESS, params) 继续后续处理器
        """
        # 检查适配器签名：仅处理来自 onebot 适配器的事件
        adapter_signature: str = params.get("adapter_signature", "")  # type: ignore[assignment]
        if "onebot_adapter:adapter:onebot_adapter" not in adapter_signature.lower():
            logger.debug(
                f"[FileReceiver] 非 OneBot 适配器事件，跳过: adapter_signature={adapter_signature}"
            )
            return EventDecision.SUCCESS, params

        message: Message | None = params.get("message")  # type: ignore[assignment]
        envelope: dict[str, Any] | None = params.get("envelope")  # type: ignore[assignment]

        if not message or not envelope:
            return EventDecision.SUCCESS, params

        # DEBUG: 打印消息类型和 envelope 中的 message_segment 结构
        envelope_seg = envelope.get("message_segment")
        logger.debug(
            f"[FileReceiver] 收到消息: message_type={message.message_type}, "
            f"envelope_seg_type={envelope_seg.get('type') if isinstance(envelope_seg, dict) else type(envelope_seg)}"
        )

        # 只处理文件类型消息
        if message.message_type != MessageType.FILE:
            return EventDecision.SUCCESS, params

        logger.debug(
            f"[FileReceiver] 进入文件处理流程, message.content type={type(message.content)}, "
            f"content={message.content}"
        )

        config = self._get_config()
        if not config:
            logger.warning("文件读取插件配置未加载，跳过文件处理")
            return EventDecision.SUCCESS, params

        # 提取文件信息
        file_data = self._extract_file_data(message, envelope)
        if not file_data:
            logger.info("无法从消息中提取文件信息，跳过")
            return EventDecision.SUCCESS, params

        file_name = file_data.get("name", "")
        file_size = file_data.get("size")
        file_id = file_data.get("id", "")

        if not file_id or not file_name:
            logger.info(f"{file_data}")
            logger.info(f"文件信息不完整: name={file_name}, id={file_id}")
            return EventDecision.SUCCESS, params

        # 白名单校验
        if not self._check_whitelist(message, config):
            logger.info(f"文件来源不在白名单内，跳过: {file_name}")
            return EventDecision.SUCCESS, params

        # 扩展名校验
        if not self._check_extension(file_name, config):
            logger.info(f"文件扩展名不在允许列表内: {file_name}")
            return EventDecision.SUCCESS, params

        # 大小校验
        if not self._check_size(file_size, config):
            logger.info(f"文件大小超出限制: {file_name}, size={file_size}")
            return EventDecision.SUCCESS, params

        # 获取文件 URL 并下载
        asyncio.create_task(
            self._download_file(
                file_id=file_id,
                file_name=file_name,
                message=message,
                envelope=envelope,
                config=config,
            )
        )

        return EventDecision.SUCCESS, params

    def _get_config(self) -> FileReaderConfig | None:
        """获取插件配置。"""
        if self.plugin and self.plugin.config:
            return cast(FileReaderConfig, self.plugin.config)
        return None

    def _extract_file_data(
        self, message: Message, envelope: dict[str, Any]
    ) -> dict[str, Any] | None:
        """从消息中提取文件数据。

        文件信息可能在 message.content 中（dict），
        也可能在 envelope 的 message_segment 中。

        Args:
            message: 消息对象
            envelope: 消息信封

        Returns:
            文件数据字典或 None
        """
        # 优先从 message.content 获取
        if isinstance(message.content, dict):
            # content 可能是 {name, size, id} 直接结构
            if "name" in message.content and "id" in message.content:
                logger.debug(
                    f"[FileReceiver._extract] 从 message.content 直接提取到文件数据: "
                    f"name={message.content.get('name')}, id={message.content.get('id')}"
                )
                return message.content
            # 也可能是 {text, media} 结构，文件数据在 media 列表中
            media_list = message.content.get("media")
            if isinstance(media_list, list):
                for item in media_list:
                    if isinstance(item, dict) and item.get("type") == "file":
                        data = item.get("data")
                        if isinstance(data, dict):
                            logger.debug(
                                f"[FileReceiver._extract] 从 message.content.media 提取到文件数据: "
                                f"name={data.get('name')}, id={data.get('id')}"
                            )
                            return data

        # 回退到 envelope 的 message_segment
        seg = envelope.get("message_segment")
        if isinstance(seg, dict):
            logger.debug(
                f"[FileReceiver._extract] 检查 envelope.message_segment: "
                f"type={seg.get('type')}, keys={list(seg.keys())}"
            )
            if seg.get("type") == "file":
                logger.debug("[FileReceiver._extract] envelope 顶层 segment 即为 file")
                return seg.get("data", {})
            # seglist 中查找 file 段
            if seg.get("type") == "seglist":
                seg_data = seg.get("data", [])
                logger.debug(
                    f"[FileReceiver._extract] envelope seglist 内有 {len(seg_data)} 个子段, "
                    f"types={[s.get('type') if isinstance(s, dict) else type(s) for s in seg_data]}"
                )
                for sub_seg in seg_data:
                    if isinstance(sub_seg, dict) and sub_seg.get("type") == "file":
                        logger.debug(
                            f"[FileReceiver._extract] 在 seglist 中找到 file 段: "
                            f"data={sub_seg.get('data')}"
                        )
                        return sub_seg.get("data", {})

        logger.debug("[FileReceiver._extract] 未找到文件数据")
        return None

    def _check_whitelist(self, message: Message, config: FileReaderConfig) -> bool:
        """校验消息来源是否在白名单内。

        Args:
            message: 消息对象
            config: 插件配置

        Returns:
            是否通过白名单校验
        """
        group_ids = config.whitelist.group_ids
        user_ids = config.whitelist.user_ids

        if message.chat_type == "group":
            group_id = message.extra.get("group_id", "")
            # 如果群聊白名单为空，表示不限制
            if not group_ids:
                return True
            return str(group_id) in group_ids
        else:
            # 私聊
            sender_id = message.sender_id
            if not user_ids:
                return True
            return str(sender_id) in user_ids

    def _check_extension(self, file_name: str, config: FileReaderConfig) -> bool:
        """校验文件扩展名是否在允许列表内。

        Args:
            file_name: 文件名
            config: 插件配置

        Returns:
            是否通过扩展名校验
        """
        allowed = config.filter.allowed_extensions
        if not allowed:
            return True

        _, ext = os.path.splitext(file_name)
        ext = ext.lower()
        return ext in allowed

    def _check_size(self, file_size: Any, config: FileReaderConfig) -> bool:
        """校验文件大小是否在限制范围内。

        Args:
            file_size: 文件大小（字节数或字符串描述）
            config: 插件配置

        Returns:
            是否通过大小校验
        """
        max_size_bytes = config.filter.max_file_size_mb * 1024 * 1024

        if file_size is None:
            # 无法确定大小时放行，下载时再判断
            return True

        if isinstance(file_size, (int, float)):
            return file_size <= max_size_bytes

        # 尝试解析字符串格式的大小（如 "1.7MB"）
        if isinstance(file_size, str):
            return self._parse_size_string(file_size) <= max_size_bytes

        return True

    def _parse_size_string(self, size_str: str) -> float:
        """解析大小字符串为字节数。

        支持格式: "1.7MB", "500KB", "2GB" 等

        Args:
            size_str: 大小字符串

        Returns:
            字节数
        """
        size_str = size_str.strip().upper()
        multipliers = {
            "GB": 1024 * 1024 * 1024,
            "MB": 1024 * 1024,
            "KB": 1024,
            "B": 1,
        }

        for suffix, multiplier in multipliers.items():
            if size_str.endswith(suffix):
                try:
                    return float(size_str[: -len(suffix)]) * multiplier
                except ValueError:
                    return 0.0

        try:
            return float(size_str)
        except ValueError:
            return 0.0

    async def _download_file(
        self,
        file_id: str,
        file_name: str,
        message: Message,
        envelope: dict[str, Any],
        config: FileReaderConfig,
    ) -> None:
        """获取文件 URL 并下载到本地。

        根据消息类型（群聊/私聊）调用对应的 OneBot API 获取文件下载链接，
        然后通过 HTTP 下载文件内容。

        Args:
            file_id: 文件 ID
            file_name: 文件名
            message: 消息对象
            envelope: 消息信封
            config: 插件配置
        """
        adapter_sign = config.adapter.adapter_signature

        try:
            # 根据消息来源选择不同的 API
            if message.chat_type == "group":
                group_id = message.extra.get("group_id", "")
                if not group_id:
                    logger.error("群聊文件缺少 group_id")
                    return

                result = await adapter_api.send_adapter_command(
                    adapter_sign=adapter_sign,
                    command_name="get_group_file_url",
                    command_data={
                        "group_id": int(group_id),
                        "file_id": file_id,
                    },
                    timeout=30.0,
                )
            else:
                # 私聊文件
                result = await adapter_api.send_adapter_command(
                    adapter_sign=adapter_sign,
                    command_name="get_private_file_url",
                    command_data={
                        "file_id": file_id,
                    },
                    timeout=30.0,
                )

            if result.get("status") != "ok":
                logger.error(f"获取文件 URL 失败: {file_name}, result={result}")
                return

            file_url = result.get("data", {}).get("url")
            if not file_url:
                logger.error(f"响应中缺少文件 URL: {file_name}")
                return

            logger.info(f"获取到文件下载链接: {file_name}")

            # 下载文件
            await self._save_file(file_url, file_name, config)

        except Exception as e:
            logger.error(f"下载文件失败: {file_name}, error={e}")

    async def _save_file(
        self, url: str, file_name: str, config: FileReaderConfig
    ) -> None:
        """从 URL 下载文件并保存到本地。

        Args:
            url: 文件下载链接
            file_name: 文件名
            config: 插件配置
        """
        import aiohttp

        download_dir = Path(config.storage.download_dir)
        download_dir.mkdir(parents=True, exist_ok=True)

        # 清理存储空间
        await self._cleanup_storage(download_dir, config)

        file_path = download_dir / file_name

        # 避免文件名冲突
        if file_path.exists():
            stem = file_path.stem
            suffix = file_path.suffix
            counter = 1
            while file_path.exists():
                file_path = download_dir / f"{stem}_{counter}{suffix}"
                counter += 1

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=60)) as resp:
                    if resp.status != 200:
                        logger.error(f"HTTP 下载失败: status={resp.status}, file={file_name}")
                        return

                    # 检查实际文件大小
                    content_length = resp.content_length
                    max_bytes = config.filter.max_file_size_mb * 1024 * 1024
                    if content_length and content_length > max_bytes:
                        logger.warning(
                            f"文件实际大小超出限制: {file_name}, "
                            f"size={content_length / (1024*1024):.2f}MB"
                        )
                        return

                    # 流式写入
                    total_written = 0
                    with open(file_path, "wb") as f:
                        async for chunk in resp.content.iter_chunked(8192):
                            total_written += len(chunk)
                            if total_written > max_bytes:
                                logger.warning(f"下载过程中文件超出大小限制: {file_name}")
                                f.close()
                                file_path.unlink(missing_ok=True)
                                return
                            f.write(chunk)

            logger.info(
                f"文件下载完成: {file_path.name}, "
                f"size={total_written / 1024:.1f}KB"
            )

        except asyncio.TimeoutError:
            logger.error(f"文件下载超时: {file_name}")
            file_path.unlink(missing_ok=True)
        except Exception as e:
            logger.error(f"文件保存失败: {file_name}, error={e}")
            file_path.unlink(missing_ok=True)

    async def _cleanup_storage(
        self, download_dir: Path, config: FileReaderConfig
    ) -> None:
        """清理存储空间，删除最旧的文件直到总大小在限制范围内。

        Args:
            download_dir: 下载目录
            config: 插件配置
        """
        max_total_bytes = config.storage.max_total_size_mb * 1024 * 1024

        files = sorted(download_dir.iterdir(), key=lambda f: f.stat().st_mtime)
        total_size = sum(f.stat().st_size for f in files if f.is_file())

        while total_size > max_total_bytes and files:
            oldest = files.pop(0)
            if oldest.is_file():
                file_size = oldest.stat().st_size
                oldest.unlink()
                total_size -= file_size
                logger.debug(f"清理旧文件: {oldest.name}")
