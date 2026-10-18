"""办公助手 MCP 服务(通过小智的 MCP 接入点,让机器人用语音办公)。

当前工具:
  - office_now                 当前日期时间(让模型能把「明天下午三点」换算成具体时间)
  - draft_dingtalk_group_message / confirm_dingtalk_group_message
        钉钉群消息:先起草,复述给用户,用户确认后才真正发送

  - get_schedule / find_person / find_free_rooms     查日程、查同事、查空闲会议室(只读,通过钉钉 CLI dws)
  - draft/confirm_calendar_event                     建日程(可带参会人、会议室),先起草后确认
  - draft/confirm_dws_group_message                  用 dws 以本人身份发群消息,先起草后确认

运行方式见 office/README.md。
"""
import logging
import os
import sys
from datetime import datetime

from fastmcp import FastMCP

import dws_client as dws
from core import DingTalkConfig, PendingStore, send_group_text

if sys.platform == "win32":
    sys.stderr.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")

VERSION = "2026-10-18-r11"
logger = logging.getLogger("OfficeAssistant")
mcp = FastMCP("OfficeAssistant")
pending = PendingStore()


def _tool(fn):
    """注册为 MCP 工具。排查问题时可设置环境变量 OFFICE_TOOLS=工具名1,工具名2 只暴露指定的工具。"""
    only = {x.strip() for x in os.environ.get("OFFICE_TOOLS", "").split(",") if x.strip()}
    return mcp.tool()(fn) if not only or fn.__name__ in only else fn


def _webhook_tool(fn):
    """Webhook 群机器人只是备用方案:没配置 DINGTALK_WEBHOOK 就不暴露,工具越少模型越不容易选错。"""
    return _tool(fn) if os.environ.get("DINGTALK_WEBHOOK", "").strip() else fn


@_tool
def office_now(query: str) -> dict:
    """查询当前的日期和星期,query 传任意文字即可。用户说「明天」「下周三」「下午三点」这类相对时间时,先调用本工具知道今天是几号。"""
    now = datetime.now(dws.TZ)  # Windows 的 Python 默认没有时区数据库,不用 ZoneInfo
    weekday = "一二三四五六日"[now.weekday()]
    return {"success": True, "iso": now.isoformat(timespec="seconds"), "weekday": f"星期{weekday}"}


@_webhook_tool
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


@_webhook_tool
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


def _to_int(v) -> int:
    try:
        return max(int(str(v).strip() or 0), 0)
    except ValueError:
        return 0


def _err(e: Exception) -> dict:
    return {"success": False, "error": str(e)}


@_tool
def get_schedule(start: str, end: str) -> dict:
    """查询本人的钉钉日程。start、end 是时间段的起止,格式如 2026-03-10T00:00。查某一天就传当天的 00:00 和 23:59。"""
    try:
        s, e = dws.to_iso(start), dws.to_iso(end)
        return {"success": True, "range": [s, e], "events": dws.list_events(s, e)}
    except Exception as ex:
        return _err(ex)


@_tool
def find_person(name: str) -> dict:
    """按姓名查同事,返回候选(含 userId)。重名时需向用户确认是哪一位。"""
    try:
        return {"success": True, "candidates": dws.find_person(name)}
    except Exception as ex:
        return _err(ex)


@_tool
def find_free_rooms(start: str, end: str, room_name: str, min_capacity: str, floor: str) -> dict:
    """查询指定时间段内空闲的会议室。所有参数都必须传:room_name 只传核心专名(如「永澄亭」,不要带「会议室」三个字和楼层前缀),不限则传空字符串;min_capacity 为最少容纳人数(数字,不限传 0);floor 为楼层(数字,如 6 表示 6 层,不限传 0),不要把楼层写进 room_name。"""
    try:
        rooms = dws.search_rooms(dws.to_iso(start), dws.to_iso(end), room_name or None)
        cap, fl = _to_int(min_capacity), _to_int(floor)
        rooms = [dws.slim_room(r) for r in rooms if (r.get("capacity") or 0) >= cap and (not fl or dws.on_floor(r, fl))]
        return {"success": True, "rooms": rooms[:10], "total": len(rooms)}
    except Exception as ex:
        return _err(ex)


@_tool
def draft_calendar_event(title: str, start: str, end: str, attendee_names: str, room_request: str) -> dict:
    """起草一个钉钉日程,不会真正创建。attendee_names 填参会人姓名,多人用逗号分隔,没有就传空字符串。room_request 用一句话描述会议室要求,如「6层 8人」,不订会议室就传空字符串。"""
    try:
        s, e = dws.to_iso(start), dws.to_iso(end)
        if e <= s:
            return {"success": False, "error": "结束时间必须晚于开始时间"}
        ids, names = [], []
        for n in [x.strip() for x in attendee_names.replace("，", ",").split(",") if x.strip()]:
            cands = dws.find_person(n)
            if len(cands) != 1:
                return {"success": False, "error": f"「{n}」匹配到 {len(cands)} 人,请让用户说明是哪位", "candidates": cands[:5]}
            ids.append(cands[0]["userId"])
            names.append(cands[0].get("name") or n)
        rooms, room_label = [], ""
        if room_request.strip():
            room_name, fl, cap = dws.parse_room_request(room_request)
            cands = dws.search_rooms(s, e, room_name or None)
            if fl:
                cands = [r for r in cands if dws.on_floor(r, fl)]
            chosen = dws.pick_room(cands, max(cap, len(ids) + 1))
            if chosen is None:
                return {"success": False, "error": "该时段没有符合条件的空闲会议室"}
            rooms = [chosen["roomId"]]
            room_label = f"{chosen.get('roomName')}(可坐{chosen.get('capacity')}人)"
            if chosen.get("needApproval"):
                room_label += "【需审批,提交后通过前不算订到】"
        payload = {"title": title.strip(), "start": s, "end": e, "attendees": ids, "rooms": rooms, "desc": ""}
        code = pending.add("calendar_event", payload)
        preview = f"{title}:{s} 至 {e}" + (f";参会人:{'、'.join(names)}" if names else "") + (f";会议室:{room_label}" if rooms else "")
        return {"success": True, "preview": preview, "confirm_code": code, "expires_in_seconds": pending.ttl,
                "next": "把 preview 念给用户并问是否确认创建;用户明确说确认后,才用 confirm_code 调用 confirm_calendar_event;说取消就不要再调用"}
    except Exception as ex:
        return _err(ex)


@_tool
def confirm_calendar_event(confirm_code: str) -> dict:
    """用户明确确认后,创建之前起草的日程。没有用户明确确认时禁止调用。"""
    item = pending.pop(confirm_code.strip())
    if item is None or item[0] != "calendar_event":
        return {"success": False, "error": "确认码无效或已过期,请重新起草"}
    p = item[1]
    try:
        dws.create_event(p["title"], p["start"], p["end"], p["attendees"], p["rooms"], p["desc"])
        return {"success": True, "message": "日程已创建" + ("(会议室已提交预订,若需审批请等审批通过)" if p["rooms"] else "")}
    except Exception as ex:
        return _err(ex)


@_tool
def draft_dws_group_message(group_name: str, text: str) -> dict:
    """起草一条以本人身份发到某钉钉群的消息(按群名查找),但【不会发送】。把 preview 念给用户并问是否确认。"""
    text = text.strip()
    if not text or len(text) > 500:
        return {"success": False, "error": "消息为空或超过 500 字"}
    try:
        groups = dws.search_group(group_name)
        if len(groups) != 1:
            return {"success": False, "error": f"群名「{group_name}」匹配到 {len(groups)} 个群,请让用户说得更具体", "candidates": groups[:5]}
        g = groups[0]
        code = pending.add("dws_group_message", {"conversation_id": g["openConversationId"], "text": text})
        label = g.get("title") or g.get("name") or group_name
        return {"success": True, "preview": f"发到「{label}」:{text}", "confirm_code": code, "expires_in_seconds": pending.ttl}
    except Exception as ex:
        return _err(ex)


@_tool
def confirm_dws_group_message(confirm_code: str) -> dict:
    """用户明确确认后,发送之前起草的群消息。没有用户明确确认时禁止调用。"""
    item = pending.pop(confirm_code.strip())
    if item is None or item[0] != "dws_group_message":
        return {"success": False, "error": "确认码无效或已过期,请重新起草"}
    try:
        dws.send_group_message(item[1]["conversation_id"], item[1]["text"])
        return {"success": True, "message": "已发送"}
    except Exception as ex:
        return _err(ex)


if __name__ == "__main__":
    print(f"OfficeAssistant {VERSION} tools={os.environ.get('OFFICE_TOOLS') or 'all'}", file=sys.stderr, flush=True)
    mcp.run(transport="stdio")
