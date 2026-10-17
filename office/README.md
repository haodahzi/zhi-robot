# 办公助手(office-assistant 分支)

让桌面机器人用语音办公:通过小智的 **MCP 接入点**,调用电脑上的本地 MCP 服务。

> 这个分支和「对话版」(`claude/confident-faraday-mt3whh`)互相隔离:
> **固件不变**,办公功能全部在 `office/` 目录里,运行在你的 Windows 电脑上。

```
机器人(语音) → 小智云端大模型 → MCP 接入点(WebSocket) → mcp_pipe.py → office/server.py
```

## 当前已有的功能

| 工具 | 作用 |
|---|---|
| `get_current_time` | 让模型知道今天几号、星期几,才能换算「明天下午三点」 |
| `draft_dingtalk_group_message` | 起草钉钉群消息(**不发送**),返回预览和确认码 |
| `confirm_dingtalk_group_message` | 用户确认后才真正发送 |

写操作一律「先起草、复述、确认、再执行」。确认码 90 秒有效、一次有效。

## 路线图

| 阶段 | 内容 | 状态 |
|---|---|---|
| 0 | 用官方计算器示例跑通 MCP 接入点 | 你来做 |
| 1 | 查日程 / 查同事 / 查空闲会议室(只读,封装钉钉 CLI `dws`) | 代码已写,**还没连真实账号测试** |
| 2 | 语音建日程(含参会人、会议室),先起草后确认 | 代码已写,待实测 |
| 3 | 以本人身份发群消息(`dws chat`),先起草后确认;Webhook 版作为备用 | 代码已写,待实测 |

不再经过 Trae:直接调用 `dws`,避免大模型再做一轮规划(Trae 一次查询约 2 分半)。
前置条件:已安装 `dws`,并执行过 `dws auth login`(企业需允许 CLI 访问)。
自测:`dws calendar event list --format json` 能返回今天的日程,再启动本服务。

## 使用步骤(Windows,PowerShell)

1. 准备 Python 3.11+。Windows 上若 `python` 命令不可用(常见于 Microsoft Store 的占位程序),用 `py` 代替,下文同理。
2. 获取桥接脚本(官方示例项目,MIT):
   `git clone https://github.com/78/mcp-calculator` ,里面的 `mcp_pipe.py` 就是桥接脚本。
3. 安装依赖:`pip install -r office/requirements.txt`,以及 mcp-calculator 的 `requirements.txt`。
4. 在 xiaozhi.me 控制台打开你的智能体配置页,复制 **MCP 接入点** 地址。
5. 先用官方 `calculator.py` 验证链路:
   ```
   $env:MCP_ENDPOINT = "<接入点地址>"
   py mcp_pipe.py calculator.py
   ```
   对机器人说「算一下 123 乘 456」,能答出来就说明链路通了。
6. 配置钉钉群机器人:群里添加「自定义机器人」,安全设置选「加签」,把 Webhook 和密钥写进 `office/.env`(参照 `.env.example`)。
7. 把 `office/mcp_config.example.json` 复制成 mcp-calculator 目录下的 `mcp_config.json`(改好路径),再运行 `py mcp_pipe.py`。
8. 对机器人说:「给项目群发一条消息,内容是下午三点开会」。它会复述,你确认后才发送。

## 安全说明

- Webhook、密钥、MCP 接入点令牌都是机密:只放在本地 `.env` 或环境变量,不要提交、不要发给别人。
- 只暴露固定的几个工具,**不提供「执行任意命令」类工具**。
- 语音可能听错,也可能被旁人利用:写操作必须确认。后续计划加入「摸头确认」(用触摸模块做物理确认)。
- 群机器人发出的消息,发送者显示为机器人,不是你本人。

## 开发

- 核心逻辑在 `core.py`(不依赖 MCP 库),测试:`python -I -m unittest discover -s office/tests`
- 没有在真实钉钉上验证过;遇到报错把返回的 `errmsg` 发来。
