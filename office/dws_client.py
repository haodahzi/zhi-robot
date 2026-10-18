"""钉钉 CLI(dws)的薄封装:只暴露固定的几条命令,参数以列表传入(不经过 shell)。

返回结构以 dws 的 JSON 输出为准;这里只做「找出含某字段的字典」这类宽松解析,
具体字段名(userId / roomId / openConversationId)取自 dws 官方文档示例。
"""
import json
import os
import re
import shutil
import subprocess
from datetime import datetime, timedelta, timezone

TZ = timezone(timedelta(hours=8))


class DwsError(RuntimeError):
    pass


_CMD_UNSAFE = set('&|<>^%"\r\n')


def resolve_dws() -> list[str]:
    """找到可直接执行的 dws 命令行前缀。

    Windows 上 npm 安装的 dws 是 dws.cmd,Python 的 subprocess 不能像 shell 那样直接找到它;
    交给 cmd.exe 解析又会让 & | % 等字符被当成命令。所以优先解析 .cmd 里指向的真实程序
    (node 脚本或 exe),解析不了才退回 .cmd 本身,并在 run() 里拒绝危险字符。"""
    found = shutil.which("dws")
    if not found:
        return ["dws"]
    if found.lower().endswith((".cmd", ".bat")):
        try:
            text = open(found, encoding="utf-8", errors="ignore").read()
        except OSError:
            return [found]
        base = os.path.dirname(found)
        m = re.search(r'"%(?:~dp0|dp0%)\\?([^"%]+\.(?:js|mjs|cjs|exe))"', text, re.I)
        if m:
            target = os.path.join(base, m.group(1).replace("\\", os.sep))
            if os.path.exists(target):
                if target.lower().endswith(".exe"):
                    return [target]
                node = os.path.join(base, "node.exe")
                return [node if os.path.exists(node) else (shutil.which("node") or "node"), target]
    return [found]


def run(args: list[str], runner=subprocess.run, timeout: float = 40.0):
    prefix = resolve_dws() if runner is subprocess.run else ["dws"]
    if prefix[0].lower().endswith((".cmd", ".bat")) and any(_CMD_UNSAFE & set(a) for a in args):
        raise DwsError("当前 dws 只能通过 cmd.exe 调用,内容里含有 & | < > ^ % \" 等特殊字符,请去掉后重试")
    cmd = [*prefix, *args, "--format", "json"]
    try:
        # stdin 必须断开:本进程的 stdin 是 MCP 消息通道,dws 若弹出确认提示会把小智的消息吞掉
        r = runner(cmd, capture_output=True, text=True, encoding="utf-8", timeout=timeout, stdin=subprocess.DEVNULL)
    except FileNotFoundError:
        raise DwsError("找不到 dws 命令,请先安装并执行 dws auth login")
    except subprocess.TimeoutExpired:
        raise DwsError("dws 执行超时")
    if r.returncode != 0:
        raise DwsError((r.stderr or r.stdout or "dws 执行失败").strip()[:500])
    out = (r.stdout or "").strip()
    if not out:
        return {}
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        raise DwsError(f"dws 输出不是 JSON:{out[:200]}")


def find_dicts(obj, key: str) -> list[dict]:
    """递归找出所有含有 key 的字典。"""
    found = []
    if isinstance(obj, dict):
        if key in obj:
            found.append(obj)
        for v in obj.values():
            found += find_dicts(v, key)
    elif isinstance(obj, list):
        for v in obj:
            found += find_dicts(v, key)
    return found


def to_iso(value: str) -> str:
    """接受 2026-03-10T14:00 / 2026-03-10 14:00 / 带时区的 ISO,统一成带 +08:00 的 ISO-8601。"""
    dt = datetime.fromisoformat(value.strip().replace(" ", "T"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ)
    return dt.isoformat(timespec="seconds")


def day_range(day: str) -> tuple[str, str]:
    d = datetime.fromisoformat(day.strip()).date()
    start = datetime(d.year, d.month, d.day, tzinfo=TZ)
    return start.isoformat(timespec="seconds"), (start + timedelta(days=1) - timedelta(seconds=1)).isoformat(timespec="seconds")


def list_events(start: str, end: str, runner=subprocess.run):
    return run(["calendar", "event", "list", "--start", start, "--end", end], runner)


def find_person(name: str, runner=subprocess.run) -> list[dict]:
    # 通讯录精确查询,实测返回 result[] 里含 userId / openDingTalkId / name
    return find_dicts(run(["contact", "user", "search", "--query", name], runner), "userId")


def search_rooms(start: str, end: str, name: str | None = None, runner=subprocess.run) -> list[dict]:
    args = ["calendar", "room", "search", "--start", start, "--end", end]
    if name:
        args += ["--room-name", name]
    return find_dicts(run(args, runner), "roomId")


def create_event(title: str, start: str, end: str, attendees: list[str], rooms: list[str],
                 desc: str = "", runner=subprocess.run):
    args = ["calendar", "event", "create", "--title", title, "--start", start, "--end", end]
    if attendees:
        args += ["--attendees", ",".join(attendees)]
    if rooms:
        args += ["--rooms", ",".join(rooms)]
    if desc:
        args += ["--desc", desc]
    return run_confirmed(args, runner)


def run_confirmed(args: list[str], runner=subprocess.run):
    """写操作:已经在上层完成「复述-确认」,所以带 --yes 跳过 dws 自己的确认;若这条命令不认 --yes,去掉重试一次。"""
    try:
        return run(args + ["--yes"], runner)
    except DwsError as e:
        if "unknown flag" in str(e).lower() or "unknown shorthand" in str(e).lower():
            return run(args, runner)
        raise


def search_group(name: str, runner=subprocess.run) -> list[dict]:
    return find_dicts(run(["chat", "search", "--query", name], runner), "openConversationId")


def send_group_message(conversation_id: str, text: str, runner=subprocess.run):
    return run_confirmed(["chat", "message", "send", "--conversation-id", conversation_id, "--content", text], runner)


def slim_room(r: dict) -> dict:
    """只保留语音场景需要的字段(字段名取自真实返回:roomId/roomName/capacity/needApproval/fullGroupPath/labels)。"""
    return {
        "roomId": r["roomId"],
        "roomName": r.get("roomName"),
        "capacity": r.get("capacity"),
        "floor": r.get("fullGroupPath"),
        "needApproval": bool(r.get("needApproval")),
        "labels": [x.get("labelName") for x in r.get("labels") or []],
    }


def pick_room(rooms: list[dict], min_capacity: int = 0) -> dict | None:
    """选容量够用的最小会议室;无需审批的优先,没有再选需要审批的(调用方要把审批告知用户)。"""
    fit = [r for r in rooms if (r.get("capacity") or 0) >= min_capacity]
    if not fit:
        return None
    return min(fit, key=lambda r: (bool(r.get("needApproval")), r.get("capacity") or 0))


def on_floor(room: dict, floor: int) -> bool:
    """按楼层筛选。真实数据里楼层出现在 fullGroupPath(如「6层 会议室」)和 roomName(如「06F-2号会议室」);
    用数字边界避免 6 匹配到 16 层。"""
    text = f"{room.get('fullGroupPath') or ''} {room.get('roomName') or ''}"
    return bool(re.search(rf"(?<!\d){floor}层", text) or re.search(rf"(?<!\d)0?{floor}F", text, re.I))


_ROOM_STOP = ("会议室", "预订", "随便", "任意", "空闲", "需要", "容纳", "能坐", "可坐", "一个", "一间", "订", "的", "个", "间", "坐", "要", ",", ",", "。", " ")
_CN_DIGIT = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_NUM = r"(\d+|[零〇一二两三四五六七八九十]+)"


def cn_to_int(text: str) -> int:
    """阿拉伯数字或 99 以内的中文数字(语音转文字常给「六」「十二」「二十三」)转成整数。"""
    if text.isdigit():
        return int(text)
    if "十" in text:
        head, _, tail = text.partition("十")
        return (_CN_DIGIT.get(head, 1) if head else 1) * 10 + (_CN_DIGIT.get(tail, 0) if tail else 0)
    n = 0
    for ch in text:
        n = n * 10 + _CN_DIGIT.get(ch, 0)
    return n


def parse_room_request(text: str) -> tuple[str, int, int]:
    """把一句话的会议室要求拆成 (名称关键词, 楼层, 最少人数),如「6层 8人」->("", 6, 8)。拆不出来的部分当作名称。"""
    t = text or ""
    floor = cap = 0
    m = re.search(_NUM + r"\s*(?:层|楼|[Ff])", t)
    if m:
        floor = cn_to_int(m.group(1))
        t = t.replace(m.group(0), " ")
    m = re.search(_NUM + r"\s*(?:个\s*)?(?:人|位)", t)
    if m:
        cap = cn_to_int(m.group(1))
        t = t.replace(m.group(0), " ")
    for w in _ROOM_STOP:
        t = t.replace(w, "")
    return t.strip(), floor, cap
