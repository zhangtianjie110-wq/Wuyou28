import io
import json
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from app.database import Database
from app.secure_store import validate_yu28_api_key
from app.yu28 import YU28Client, YU28Error, parse_latest_response


VALID_RESPONSE = {
    "countdown": "02:40",
    "data": [{
        "nbr": "3485700",
        "time": "2026-09-24 04:55:00",
        "number": "4+8+2=14",
        "combination": "大双",
    }],
}


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _limit):
        return json.dumps(self.payload, ensure_ascii=False).encode("utf-8")


class YU28Tests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).parent / ".test_data"
        root.mkdir(exist_ok=True)
        self.path = root / "yu28_tests.db"
        for suffix in ("", "-wal", "-shm"):
            candidate = Path(str(self.path) + suffix)
            if candidate.exists():
                candidate.unlink()
        self.database = Database(self.path)

    def tearDown(self):
        for suffix in ("", "-wal", "-shm"):
            candidate = Path(str(self.path) + suffix)
            if candidate.exists():
                candidate.unlink()

    def test_key_format(self):
        self.assertEqual(validate_yu28_api_key("yu28_0123456789abcdef"), "yu28_0123456789abcdef")
        for value in ("", "yu28_short", "key_0123456789abcdef", "yu28_0123456789abcdeg"):
            with self.assertRaises(ValueError):
                validate_yu28_api_key(value)

    def test_parses_official_latest_contract(self):
        draw = parse_latest_response(VALID_RESPONSE)
        self.assertEqual(draw.nbr, "3485700")
        self.assertEqual(draw.number, "4+8+2=14")
        self.assertEqual(draw.result, "14")
        self.assertEqual(draw.combination, "大双")
        self.assertEqual(draw.countdown, "02:40")

    def test_rejects_bad_json_shapes_and_inconsistent_draw(self):
        bad = json.loads(json.dumps(VALID_RESPONSE, ensure_ascii=False))
        bad["data"][0]["combination"] = "小双"
        with self.assertRaises(YU28Error):
            parse_latest_response(bad)
        with self.assertRaises(YU28Error):
            parse_latest_response({"countdown": "02:40", "data": []})

    def test_client_uses_header_and_exact_whitelisted_url(self):
        with patch("app.yu28.urlopen", return_value=_Response(VALID_RESPONSE)) as open_url:
            draw = YU28Client("yu28_0123456789abcdef").fetch_latest()
        request = open_url.call_args.args[0]
        self.assertEqual(request.full_url, "https://yu28.top/api/kj.json?nbr=1")
        self.assertEqual(request.get_header("X-api-key"), "yu28_0123456789abcdef")
        self.assertEqual(draw.nbr, "3485700")

    def test_http_and_network_errors_are_readable(self):
        body = io.BytesIO(b'{"error":{"code":"UNAUTHORIZED","message":"invalid"}}')
        error = HTTPError("https://yu28.top/api/kj.json?nbr=1", 401, "", {}, body)
        with patch("app.yu28.urlopen", side_effect=error):
            with self.assertRaisesRegex(YU28Error, "invalid"):
                YU28Client("yu28_0123456789abcdef").fetch_latest()
        with patch("app.yu28.urlopen", side_effect=URLError("offline")):
            with self.assertRaisesRegex(YU28Error, "检查网络"):
                YU28Client("yu28_0123456789abcdef").fetch_latest()

    def test_draw_is_unique_and_updates_existing_predictions(self):
        prediction_id = self.database.add_prediction({
            "issue_no": "3485700",
            "source_type": "VIP",
            "big_single": 25,
            "big_double": 25,
            "small_single": 25,
            "small_double": 25,
        })
        draw = parse_latest_response(VALID_RESPONSE)
        self.assertTrue(self.database.save_yu28_draw(draw.payload()))
        self.assertFalse(self.database.save_yu28_draw(draw.payload()))
        self.assertEqual(self.database.count_yu28_draws(), 1)
        self.assertEqual(self.database.latest_yu28_draw()["nbr"], "3485700")
        self.assertEqual(self.database.update_result_by_issue(draw.nbr, draw.result), 1)
        saved = self.database.get_prediction(prediction_id)
        self.assertEqual(saved["actual_result"], "14")
        self.assertEqual(saved["status"], "正常")


if __name__ == "__main__":
    unittest.main()
