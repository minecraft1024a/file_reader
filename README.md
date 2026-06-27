# file_reader

文件读取插件 - 自动下载聊天中的文件并提供 AI 读取工具。

## 功能概述

本插件为 Neo-MoFox 提供两项核心能力：

1. **文件自动下载**：监听群聊/私聊中的文件消息，按白名单条件自动下载到本地。
2. **AI 文件读取**：提供 Action 供 LLM 按文件名和行号读取已下载文件的内容。

## 组件

| 组件类型 | 组件名称 | 说明 |
|---------|---------|------|
| EventHandler | `file_receiver` | 监听 `ON_MESSAGE_RECEIVED` 事件，识别文件消息并自动下载 |
| Action | `read_downloaded_file` | 供 LLM 调用，按文件名和行号范围读取已下载文件的内容 |

## 依赖

- 插件依赖：`onebot_adapter`
- Python 依赖：`aiohttp`

## 配置

配置文件路径：`config/plugins/file_reader/config.toml`

### `[whitelist]` 白名单

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `group_ids` | `list[str]` | `[]` | 允许下载文件的群聊 ID 列表，为空则不限制 |
| `user_ids` | `list[str]` | `[]` | 允许下载文件的私聊用户 ID 列表，为空则不限制 |

### `[filter]` 文件过滤

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `allowed_extensions` | `list[str]` | 见下方 | 允许下载的文件扩展名列表 |
| `max_file_size_mb` | `float` | `10.0` | 允许下载的最大文件大小（MB） |

默认允许的扩展名：

```
.py .js .ts .java .c .cpp .h .go .rs .rb .php .sh .bash
.json .yaml .yml .toml .xml
.md .txt .csv .log .ini .cfg
.html .css .scss .vue .svelte
```

### `[storage]` 存储

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `download_dir` | `str` | `data/file_reader/downloads` | 文件下载目录 |
| `max_total_size_mb` | `float` | `500.0` | 下载目录最大总大小（MB），超出后自动清理最旧文件 |

### `[adapter]` 适配器

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `adapter_signature` | `str` | `onebot_adapter:adapter:onebot_adapter` | 用于获取文件 URL 的适配器签名 |

## 工作流程

```
用户在群聊/私聊中发送文件
        │
        ▼
FileReceiverHandler 监听到 ON_MESSAGE_RECEIVED 事件
        │
        ▼
检查适配器签名（仅处理 OneBot 适配器事件）
        │
        ▼
检查消息类型是否为 FILE
        │
        ▼
提取文件信息（name, id, size）
        │
        ▼
白名单校验 → 扩展名校验 → 文件大小校验
        │
        ▼
调用适配器 API 获取文件下载链接
        │
        ▼
流式下载文件到本地（自动去重、自动清理旧文件）
        │
        ▼
LLM 通过 read_downloaded_file Action 读取文件内容
（每次最多返回 50 行，支持分页读取）
```

## 使用示例

配置白名单后，在允许的群聊中发送代码文件，插件会自动下载。之后 AI 可以主动读取文件内容进行分析和回答。

AI 调用示例：

```
read_downloaded_file(file_name="main.py", start_line=1)
```

返回内容包含行号、总行数和当前读取范围，若文件未读完会提示继续读取的起始行号。

## 安全机制

- **路径穿越防护**：文件名中不允许包含 `/`、`\` 或 `..`
- **白名单控制**：可精确限制哪些群组和用户能触发文件下载
- **扩展名过滤**：仅下载配置中允许的文件类型
- **大小限制**：下载前和下载过程中均会检查文件大小
- **存储空间管理**：超出总容量限制时自动清理最旧文件
