"""文件读取插件入口。

提供文件自动下载和 AI 读取功能：
- 监听群聊/私聊中的文件消息，按白名单条件自动下载
- 提供 Action 供 LLM 按文件名和行号读取已下载文件的内容
"""

from src.app.plugin_system.base import BasePlugin, register_plugin

from .components.action import FileReadAction
from .components.config import FileReaderConfig
from .components.event_handler import FileReceiverHandler


@register_plugin
class FileReaderPlugin(BasePlugin):
    """文件读取插件。"""

    plugin_name = "file_reader"
    plugin_description = "监听文件消息并自动下载，提供 AI 文件读取动作"
    plugin_version = "1.0.0"

    configs: list[type] = [FileReaderConfig]
    dependent_components: list[str] = []

    def get_components(self) -> list[type]:
        """返回插件组件类。"""
        return [FileReceiverHandler, FileReadAction]
