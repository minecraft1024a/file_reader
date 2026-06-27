"""文件读取插件配置。"""

from src.app.plugin_system.base import BaseConfig, Field, SectionBase, config_section


class FileReaderConfig(BaseConfig):
    """文件读取插件配置，定义白名单和下载限制。"""

    config_name = "config"
    config_description = "文件读取插件配置"

    @config_section("whitelist")
    class WhitelistSection(SectionBase):
        """白名单配置：限定哪些群/私聊可以触发文件下载。"""

        group_ids: list[str] = Field(
            default_factory=list,
            description="允许下载文件的群聊 ID 列表，为空则不限制",
        )
        user_ids: list[str] = Field(
            default_factory=list,
            description="允许下载文件的私聊用户 ID 列表，为空则不限制",
        )

    @config_section("filter")
    class FilterSection(SectionBase):
        """文件过滤配置：限定可下载的文件类型和大小。"""

        allowed_extensions: list[str] = Field(
            default_factory=lambda: [
                ".py", ".js", ".ts", ".java", ".c", ".cpp", ".h",
                ".go", ".rs", ".rb", ".php", ".sh", ".bash",
                ".json", ".yaml", ".yml", ".toml", ".xml",
                ".md", ".txt", ".csv", ".log", ".ini", ".cfg",
                ".html", ".css", ".scss", ".vue", ".svelte",
            ],
            description="允许下载的文件扩展名列表",
        )
        max_file_size_mb: float = Field(
            default=10.0,
            description="允许下载的最大文件大小（MB）",
        )

    @config_section("storage")
    class StorageSection(SectionBase):
        """存储配置。"""

        download_dir: str = Field(
            default="data/file_reader/downloads",
            description="文件下载目录",
        )
        max_total_size_mb: float = Field(
            default=500.0,
            description="下载目录最大总大小（MB），超出后自动清理最旧文件",
        )

    @config_section("adapter")
    class AdapterSection(SectionBase):
        """适配器配置。"""

        adapter_signature: str = Field(
            default="onebot_adapter:adapter:onebot_adapter",
            description="用于获取文件 URL 的适配器签名",
        )

    whitelist: WhitelistSection = Field(default_factory=WhitelistSection)
    filter: FilterSection = Field(default_factory=FilterSection)
    storage: StorageSection = Field(default_factory=StorageSection)
    adapter: AdapterSection = Field(default_factory=AdapterSection)
