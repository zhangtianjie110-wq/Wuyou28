from __future__ import annotations

import io
import json
import socket
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch
from urllib.error import HTTPError

from app.integration.gateway import IntegrationGateway
from app.yu28 import YU28Client, YU28Error


API_KEY = "yu28_0123456789abcdef"


class _Response:
    def __init__(self, payload):
        self.body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def read(self, _limit):
        return self.body


class YU28ToolsTests(unittest.TestCase):
    def client_response(self, payload):
        return patch("app.yu28.urlopen", return_value=_Response(payload))

    def test_draw_by_issue_validates_identity(self):
        payload = {
            "countdown": "02:40",
            "data": [{
                "nbr": "3463701",
                "time": "2026-07-31 11:25:00",
                "number": "4+8+2=14",
                "combination": "大双",
            }],
        }
        with self.client_response(payload):
            draw = YU28Client(API_KEY).fetch_draw_by_issue("3463701")
        self.assertEqual(draw.nbr, "3463701")

    def test_keno_preserves_api_order(self):
        raw = "74,1,62,4,58,7,56,9,54,20,52,23,49,25,39,26,38,27,31,72"
        payload = {"data": [{
            "nbr": "3463701",
            "time": "2026-07-31 11:25:00",
            "nbrs": raw,
        }]}
        with self.client_response(payload):
            result = YU28Client(API_KEY).fetch_keno()
        self.assertEqual(result["data"][0]["nbrs"], raw)

    def test_text_trend_preserves_api_order(self):
        payload = {
            "countdown": "02:40",
            "data": [
                {
                    "nbr": "3463702",
                    "time": "2026-07-31 11:28:30",
                    "number": "8+8+2=18",
                    "combination": "大双",
                },
                {
                    "nbr": "3463701",
                    "time": "2026-07-31 11:25:00",
                    "number": "4+8+2=14",
                    "combination": "大双",
                },
            ],
        }
        with self.client_response(payload):
            result = YU28Client(API_KEY).fetch_text_trend(2)
        self.assertEqual([draw.nbr for draw in result["data"]], ["3463702", "3463701"])

    def test_daily_stats_omission_and_long_dragon(self):
        client = YU28Client(API_KEY)
        today = datetime.now(timezone(timedelta(hours=8))).date().isoformat()
        with self.client_response({"date": today, "data": {"大": 102, "10": 8}}):
            self.assertEqual(client.fetch_daily_stats()["data"]["大"], 102)
        with self.client_response({"data": {"大": 2, "小单": 0}}):
            self.assertEqual(client.fetch_omission()["data"]["大"], 2)
        dragon = {"data": [{
            "type": "周期",
            "content": "单双",
            "status": "进行中",
            "count": 8,
            "start": "3463693",
            "current": "3463700",
        }]}
        with self.client_response(dragon):
            self.assertEqual(client.fetch_long_dragon(), dragon)

    def test_unified_http_timeout_and_json_errors(self):
        client = YU28Client(API_KEY)
        for status in (401, 403, 404, 429, 500, 503):
            with self.subTest(status=status):
                error = HTTPError("url", status, "error", {}, io.BytesIO(b"{}"))
                with patch("app.yu28.urlopen", side_effect=error):
                    with self.assertRaises(YU28Error) as caught:
                        client.fetch_omission()
                    self.assertEqual(caught.exception.status, status)
        with patch("app.yu28.urlopen", side_effect=socket.timeout()):
            with self.assertRaisesRegex(YU28Error, "超时"):
                client.fetch_omission()
        response = _Response({})
        response.body = b"not-json"
        with patch("app.yu28.urlopen", return_value=response):
            with self.assertRaisesRegex(YU28Error, "无效 JSON"):
                client.fetch_omission()

    def test_gateway_uses_secure_store_and_forwards_read_methods(self):
        client = Mock()
        with (
            patch("app.integration.gateway.load_yu28_api_key", return_value=API_KEY) as load,
            patch("app.integration.gateway.YU28Client", return_value=client),
        ):
            gateway = IntegrationGateway.__new__(IntegrationGateway)
            gateway.draw_by_issue("1")
            gateway.keno_20(2)
            gateway.text_trend(20)
            gateway.daily_stats()
            gateway.omission()
            gateway.long_dragon()
        self.assertEqual(load.call_count, 6)
        client.fetch_draw_by_issue.assert_called_once_with("1")
        client.fetch_keno.assert_called_once_with(2)
        client.fetch_text_trend.assert_called_once_with(20)
        client.fetch_daily_stats.assert_called_once_with()
        client.fetch_omission.assert_called_once_with()
        client.fetch_long_dragon.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
