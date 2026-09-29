from __future__ import annotations

import json
import re
import socket
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .stats import normalize_result


API_BASE_URL = "https://yu28.top/api"
DRAWS_URL = f"{API_BASE_URL}/kj.json"
LATEST_URL = f"{DRAWS_URL}?nbr=1"
ISSUE_URL = f"{API_BASE_URL}/qh.json"
KENO_URL = f"{API_BASE_URL}/keno.json"
DAILY_STATS_URL = f"{API_BASE_URL}/yk.json"
OMISSION_URL = f"{API_BASE_URL}/yl.json"
LONG_DRAGON_URL = f"{API_BASE_URL}/cl.json"
BEIJING_TIME = timezone(timedelta(hours=8))


class YU28Error(RuntimeError):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class YU28Draw:
    nbr: str
    time: str
    number: str
    combination: str
    countdown: str

    @property
    def result(self) -> str:
        return self.number.rsplit("=", 1)[1]

    def payload(self) -> dict[str, str]:
        return asdict(self)


def _error_message(status: int, payload: Any) -> str:
    remote = ""
    if isinstance(payload, dict) and isinstance(payload.get("error"), dict):
        remote = str(payload["error"].get("message") or "").strip()
    defaults = {
        401: "API Key 无效或未授权",
        403: "API Key 无权访问 YU28",
        404: "YU28 未找到请求的数据",
        429: "YU28 请求过于频繁，请稍后重试",
    }
    fallback = "YU28 服务暂时不可用" if 500 <= status <= 599 else f"YU28 返回 HTTP {status}"
    return remote or defaults.get(status, fallback)


def parse_latest_response(payload: Any) -> YU28Draw:
    if not isinstance(payload, dict):
        raise YU28Error("YU28 JSON 根节点格式错误")
    countdown = payload.get("countdown", "")
    if not isinstance(countdown, str):
        raise YU28Error("YU28 countdown 字段格式错误")
    countdown = countdown.strip()
    if countdown and not re.fullmatch(r"\d{2,3}:\d{2}", countdown):
        raise YU28Error("YU28 countdown 字段格式错误")
    rows = payload.get("data")
    if not isinstance(rows, list) or not rows or not isinstance(rows[0], dict):
        raise YU28Error("YU28 未返回最新期开奖数据")
    row = rows[0]
    nbr = row.get("nbr")
    draw_time = row.get("time")
    number = row.get("number")
    combination = row.get("combination")
    if not isinstance(nbr, str) or not nbr.isdigit():
        raise YU28Error("YU28 nbr 字段格式错误")
    if not isinstance(draw_time, str) or not re.fullmatch(
        r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", draw_time.strip()
    ):
        raise YU28Error("YU28 time 字段格式错误")
    if not isinstance(number, str):
        raise YU28Error("YU28 number 字段格式错误")
    compact_number = re.sub(r"\s+", "", number)
    match = re.fullmatch(r"(\d{1,2})\+(\d{1,2})\+(\d{1,2})=(\d{1,2})", compact_number)
    if not match:
        raise YU28Error("YU28 number 字段格式错误")
    calculated = sum(int(match.group(index)) for index in (1, 2, 3))
    result = int(match.group(4))
    if calculated != result or not 0 <= result <= 27:
        raise YU28Error("YU28 开奖算式校验失败")
    expected_combo = normalize_result(str(result))
    if combination != expected_combo:
        raise YU28Error("YU28 combination 与开奖算式不一致")
    return YU28Draw(nbr, draw_time.strip(), compact_number, combination, countdown)


def parse_text_trend_response(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise YU28Error("YU28 文本走势数据格式错误")
    countdown = payload.get("countdown", "")
    draws = [
        parse_latest_response({"countdown": countdown, "data": [row]})
        for row in payload["data"]
    ]
    return {"countdown": countdown.strip(), "data": draws}


def _parse_counter_response(payload: Any, name: str) -> dict[str, int]:
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), dict):
        raise YU28Error(f"YU28 {name}数据格式错误")
    values: dict[str, int] = {}
    for key, value in payload["data"].items():
        if not isinstance(key, str) or not key or isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise YU28Error(f"YU28 {name}数据格式错误")
        values[key] = value
    return values


def parse_keno_response(payload: Any) -> dict[str, list[dict[str, str]]]:
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise YU28Error("YU28 Keno 数据格式错误")
    rows: list[dict[str, str]] = []
    for row in payload["data"]:
        if not isinstance(row, dict):
            raise YU28Error("YU28 Keno 数据格式错误")
        nbr, draw_time, nbrs = row.get("nbr"), row.get("time"), row.get("nbrs")
        if not isinstance(nbr, str) or not nbr.isdigit():
            raise YU28Error("YU28 Keno 期号格式错误")
        if not isinstance(draw_time, str) or not re.fullmatch(
            r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", draw_time.strip()
        ):
            raise YU28Error("YU28 Keno 时间格式错误")
        numbers = nbrs.split(",") if isinstance(nbrs, str) else []
        if (
            len(numbers) != 20
            or len(set(numbers)) != 20
            or any(not item.isdigit() or not 1 <= int(item) <= 80 for item in numbers)
        ):
            raise YU28Error("YU28 Keno 20码格式错误")
        rows.append({"nbr": nbr, "time": draw_time.strip(), "nbrs": nbrs})
    return {"data": rows}


def parse_long_dragon_response(payload: Any) -> dict[str, list[dict[str, Any]]]:
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise YU28Error("YU28 长龙数据格式错误")
    rows: list[dict[str, Any]] = []
    for row in payload["data"]:
        if not isinstance(row, dict):
            raise YU28Error("YU28 长龙数据格式错误")
        dragon_type, content = row.get("type"), row.get("content")
        status, count = row.get("status"), row.get("count")
        start, current = row.get("start"), row.get("current")
        if (
            not isinstance(dragon_type, str)
            or not dragon_type
            or not isinstance(content, str)
            or not content
            or status not in {"进行中", "已断开"}
            or isinstance(count, bool)
            or not isinstance(count, int)
            or count < 1
            or not isinstance(start, str)
            or not start.isdigit()
            or not isinstance(current, str)
            or not current.isdigit()
        ):
            raise YU28Error("YU28 长龙数据格式错误")
        rows.append({
            "type": dragon_type,
            "content": content,
            "status": status,
            "count": count,
            "start": start,
            "current": current,
        })
    return {"data": rows}


class YU28Client:
    def __init__(self, api_key: str, timeout: float = 15.0):
        from .secure_store import validate_yu28_api_key

        self._api_key = validate_yu28_api_key(api_key)
        self.timeout = max(1.0, float(timeout))

    def _request_json(self, url: str) -> Any:
        request = Request(
            url,
            headers={
                "X-Api-Key": self._api_key,
                "Accept": "application/json",
                "User-Agent": "Wuyou28/1.0",
            },
            method="GET",
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                raw = response.read(1_048_577)
                if len(raw) > 1_048_576:
                    raise YU28Error("YU28 响应数据过大")
        except HTTPError as exc:
            try:
                payload = json.loads(exc.read().decode("utf-8", errors="replace"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                payload = None
            raise YU28Error(_error_message(exc.code, payload), exc.code) from exc
        except (socket.timeout, TimeoutError) as exc:
            raise YU28Error("YU28 请求超时") from exc
        except URLError as exc:
            if isinstance(exc.reason, (socket.timeout, TimeoutError)):
                raise YU28Error("YU28 请求超时") from exc
            raise YU28Error("无法连接 YU28，请检查网络后重试") from exc
        except OSError as exc:
            raise YU28Error("无法连接 YU28，请检查网络后重试") from exc
        try:
            return json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise YU28Error("YU28 返回了无效 JSON") from exc

    def fetch_latest(self) -> YU28Draw:
        return parse_latest_response(self._request_json(LATEST_URL))

    def fetch_text_trend(self, limit: int = 20) -> dict[str, Any]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise ValueError("YU28 文本走势期数必须在 1 到 100 之间")
        return parse_text_trend_response(
            self._request_json(f"{DRAWS_URL}?{urlencode({'nbr': limit})}")
        )

    def fetch_draw_by_issue(self, issue: str | int) -> YU28Draw:
        issue_value = str(issue).strip()
        if not issue_value.isdigit() or int(issue_value) < 1:
            raise ValueError("YU28 期号必须是正整数")
        payload = self._request_json(f"{ISSUE_URL}?{urlencode({'nbr': issue_value})}")
        draw = parse_latest_response(payload)
        if draw.nbr != issue_value:
            raise YU28Error("YU28 返回期号与查询期号不一致")
        return draw

    def fetch_keno(self, limit: int = 1) -> dict[str, list[dict[str, str]]]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise ValueError("YU28 Keno 条数必须在 1 到 100 之间")
        return parse_keno_response(
            self._request_json(f"{KENO_URL}?{urlencode({'nbr': limit})}")
        )

    def fetch_daily_stats(self) -> dict[str, Any]:
        payload = self._request_json(DAILY_STATS_URL)
        today = datetime.now(BEIJING_TIME).date().isoformat()
        if not isinstance(payload, dict) or payload.get("date") != today:
            raise YU28Error("YU28 今日已开统计日期不一致")
        return {"date": today, "data": _parse_counter_response(payload, "今日已开统计")}

    def fetch_omission(self) -> dict[str, dict[str, int]]:
        payload = self._request_json(OMISSION_URL)
        return {"data": _parse_counter_response(payload, "遗漏")}

    def fetch_long_dragon(self) -> dict[str, list[dict[str, Any]]]:
        return parse_long_dragon_response(self._request_json(LONG_DRAGON_URL))
