"""钉钉 CLI(dws)的薄封装:只暴露固定的几条命令,参数以列表传入(不经过 shell)。

返回结构以 dws 的 JSON 输出为准;这里只做「找出含某字段的字典」这类宽松解析,
具体字段名(userId / roomId / openConversationId)取自 dws 官方文档示例。
"""
import json
import subprocess
from datetime import datetime, timedelta, timezone

TZ = timezone(timedelta(hours=8))


class DwsError(RuntimeError):
    pass


def run(args: list[str], runner=subprocess.run, timeout: float = 40.0):
    cmd = ["dws", *args, "--format", "json"]
    try:
        r = runner(cmd, capture_output=True, text=True, encoding="utf-8", timeout=timeout)
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
    data = run(["aisearch", "person", "--query", name, "--dimension", "name"], runner)
    return find_dicts(data, "userId")


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
    return run(args + ["--yes"], runner)


def search_group(name: str, runner=subprocess.run) -> list[dict]:
    return find_dicts(run(["chat", "search", "--query", name], runner), "openConversationId")


def send_group_message(conversation_id: str, text: str, runner=subprocess.run):
    return run(["chat", "message", "send", "--conversation-id", conversation_id, "--content", text, "--yes"], runner)
