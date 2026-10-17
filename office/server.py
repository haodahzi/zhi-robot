"""办公助手 MCP 服务(通过小智的 MCP 接入点,让机器人用语音办公)。

当前工具:
  - get_current_time           当前日期时间(让模型能把「明天下午三点」换算成具体时间)
  - draft_dingtalk_group_message / confirm_dingtalk_group_message
        钉钉群消息:先起草,复述给用户,用户确认后才真正发送

运行方式见 office/README.md。日程、会议室等功能见 README 的路线图,后续加入。
"""
import logging
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

from fastmcp import FastMCP

from core import DingTalkConfig, PendingStore, send_group_text

if sys.platform == "win32":
    sys.stderr.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")

logger = logging.getLogger("OfficeAssistant")
mcp = FastMCP("OfficeAssistant")
pending = PendingStore()


@mcp.tool()
def get_current_time(timezone: str = "Asia/Shanghai") -> dict:
    """获取当前日期和时间。用户说「明天」「下周三」「下午三点」这类相对时间时,先调用本工具得到今天的日期,再换算成具体日期时间。"""
    now = datetime.now(ZoneInfo(timezone))
    weekday = "一二三四五六日"[now.weekday()]
    return {"success": True, "iso": now.isoformat(timespec="seconds"), "weekday": f"星期{weekday}", "timezone": timezone}


@mcp.tool()
def draft_dingtalk_group_message(text: str) -> dict:
    """起草一条要发到钉钉群的消息,但【不会发送】。调用后必须把 preview 的内容念给用户听,并问「确认发送吗」。
    只有用户明确说「确认」「发吧」之后,才可以用返回的 confirm_code 调用 confirm_dingtalk_group_message。用户说「取消」就不要再调用。"""
    text = text.strip()
    if not text:
        return {"success": False, "error": "消息内容为空"}
    if len(text) > 500:
        return {"success": False, "error": "消息太长(超过 500 字),请精简"}
    code = pending.add("dingtalk_group_message", {"text": text})
    return {"success": True, "preview": text, "confirm_code": code, "expires_in_seconds": pending.ttl,
            "next": "把 preview 念给用户并询问是否确认发送"}


@mcp.tool()
def confirm_dingtalk_group_message(confirm_code: str) -> dict:
    """用户确认后,发送之前起草的钉钉群消息。confirm_code 来自 draft_dingtalk_group_message。没有用户明确确认时禁止调用。"""
    item = pending.pop(confirm_code.strip())
    if item is None:
        return {"success": False, "error": "确认码无效或已过期,请重新起草"}
    _, payload = item
    try:
        resp = send_group_text(DingTalkConfig.from_env(), payload["text"])
    except Exception as e:  # 网络或配置错误
        logger.exception("send failed")
        return {"success": False, "error": f"发送失败:{e}"}
    if resp.get("errcode") != 0:
        return {"success": False, "error": f"钉钉返回错误:{resp.get('errmsg')}(errcode={resp.get('errcode')})"}
    return {"success": True, "message": "已发送到钉钉群"}


if __name__ == "__main__":
    mcp.run(transport="stdio")
