"""文件读取动作。

提供给 LLM 的 Action，用于按文件名和行数范围读取已下载的文件内容。
通过自定义 go_activate 判断当前聊天流是否在白名单内，
并在参数描述中注入当前已下载的文件列表。
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any, AsyncGenerator, cast

from src.app.plugin_system.api.log_api import get_logger
from src.core.components.base.action import BaseAction
from src.core.components.types import ChatType

from .config import FileReaderConfig

logger = get_logger("file_reader")


def _get_available_files() -> list[str]:
    """获取下载目录中的可用文件名列表。

    Returns:
        可用文件名列表
    """
    download_dir = Path("data/file_reader/downloads")
    if not download_dir.exists():
        return []
    return sorted(f.name for f in download_dir.iterdir() if f.is_file())


# 构建可用文件列表描述，供 LLM 在参数描述中参考
_FILE_LIST_DESC = (
    "要读取的文件名（不含路径）。当前可用文件：" + "、".join(_get_available_files())
    if _get_available_files()
    else "要读取的文件名（不含路径）"
)


class FileReadAction(BaseAction):
    """读取已下载文件的指定行数内容。

    AI 可通过此动作传入文件名和起始行号来读取文件的部分内容，
    返回指定范围内的代码及总行数信息。
    仅在白名单聊天流中且有可用文件时激活。
    """

    action_name: str = "read_downloaded_file"
    action_description: str = (
        "读取已下载的文件内容。传入文件名和起始行号，"
        "返回从该行开始的内容片段，以及文件的总行数和当前读取位置。"
        "每次最多返回 50 行，如需继续读取请传入新的起始行号。"
    )
    primary_action: bool = False
    chat_type: ChatType = ChatType.ALL
    associated_types: list[str] = ["file"]

    LINES_PER_PAGE = 50

    async def go_activate(self) -> bool:
        """自定义激活函数：仅在 QQ 平台且白名单聊天流中且有可用文件时激活。

        检查当前 chat_stream 的平台是否为 QQ，
        以及所属群组/用户是否在配置白名单中，
        同时检查下载目录是否存在可读文件。

        Returns:
            bool: 是否激活此动作
        """
        # 仅在 QQ 平台启用
        stream = self.chat_stream
        if stream.platform.lower() != "qq":
            return False

        config = self._get_config()
        if not config:
            return False

        # 检查下载目录是否有文件
        download_dir = Path(config.storage.download_dir)
        if not download_dir.exists():
            return False

        available_files = [f for f in download_dir.iterdir() if f.is_file()]
        if not available_files:
            return False

        # 检查当前聊天流是否在白名单内
        group_ids = config.whitelist.group_ids
        user_ids = config.whitelist.user_ids

        if stream.chat_type == "group":
            group_id = getattr(stream, "group_id", "") or ""
            # 白名单为空表示不限制
            if group_ids and str(group_id) not in group_ids:
                return False
        else:
            user_id = getattr(stream, "user_id", "") or ""
            if user_ids and str(user_id) not in user_ids:
                return False

        return True

    async def execute(
        self,
        file_name: Annotated[str, _FILE_LIST_DESC],
        start_line: Annotated[int, "起始行号（从 1 开始）"] = 1,
    ) -> AsyncGenerator[tuple[bool, str] | None, None]:
        """读取已下载文件的指定行范围内容。

        Args:
            file_name: 文件名
            start_line: 起始行号（从 1 开始，默认为 1）

        Yields:
            (成功标志, 结果文本) 或 None（暂停点）
        """
        config = self._get_config()
        if not config:
            yield False, "文件读取插件配置未加载"
            return

        download_dir = Path(config.storage.download_dir)

        if not download_dir.exists():
            yield False, f"下载目录不存在: {download_dir}"
            return

        # 安全校验：防止路径穿越
        if "/" in file_name or "\\" in file_name or ".." in file_name:
            yield False, "文件名不合法，不能包含路径分隔符或 .."
            return

        file_path = download_dir / file_name

        if not file_path.exists():
            available = [f.name for f in download_dir.iterdir() if f.is_file()]
            yield False, (
                f"文件 '{file_name}' 不存在。"
                f"当前可用文件: {available[:20]}"
            )
            return

        if not file_path.is_file():
            yield False, f"'{file_name}' 不是一个文件"
            return

        # 暂停点
        yield None

        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            yield False, f"读取文件失败: {e}"
            return

        lines = content.splitlines()
        total_lines = len(lines)

        # 校验起始行号
        if start_line < 1:
            start_line = 1
        if start_line > total_lines:
            yield False, f"起始行号 {start_line} 超出文件总行数 {total_lines}"
            return

        # 计算读取范围
        end_line = min(start_line + self.LINES_PER_PAGE - 1, total_lines)
        selected_lines = lines[start_line - 1 : end_line]

        # 格式化输出，带行号
        numbered_content = "\n".join(
            f"{start_line + i:4d} | {line}"
            for i, line in enumerate(selected_lines)
        )

        result_text = (
            f"文件: {file_name}\n"
            f"总行数: {total_lines}\n"
            f"当前范围: 第 {start_line} - {end_line} 行\n"
            f"{'还有更多内容，可继续传入 start_line=' + str(end_line + 1) + ' 读取' if end_line < total_lines else '已到文件末尾'}\n"
            f"---\n{numbered_content}"
        )

        logger.info(f"读取文件 {file_name} 第 {start_line}-{end_line} 行")
        yield True, result_text

    def _get_config(self) -> FileReaderConfig | None:
        """获取插件配置。"""
        if self.plugin and self.plugin.config:
            return cast(FileReaderConfig, self.plugin.config)
        return None
