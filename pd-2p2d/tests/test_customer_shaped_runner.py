import io
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import customer_shaped_runner as runner


class Response(io.BytesIO):
    status = 200


class RunnerTests(unittest.TestCase):
    def test_exact_backend_construction(self):
        def tokenize(url, payload, timeout):
            count = 12 + payload["messages"][0]["content"].count(" data")
            return Response(json.dumps({"count": count}).encode())
        item = dict(request_id="r1", prefix_group="hot-0", cache_class="hot",
                    input_tokens=100, prompt_unit=" data")
        with patch.object(runner, "post", tokenize):
            messages, marker = runner.prepare(item, "new-namespace", "tokenize")
        self.assertEqual(messages[0]["content"].count(" data"), 88)
        self.assertIn(marker, messages[0]["content"])

    def test_complete_stream(self):
        data = [dict(choices=[dict(delta=dict(content="MARKER"))]),
                dict(choices=[], usage=dict(prompt_tokens=100, completion_tokens=8))]
        raw = b"".join(b"data: " + json.dumps(event).encode() + b"\n\n" for event in data)
        raw += b"data: [DONE]\n\n"
        with tempfile.TemporaryDirectory() as directory, patch.object(runner, "post", return_value=Response(raw)):
            stop = threading.Event()
            result = runner.request(dict(request_id="r1", input_tokens=100, output_tokens=8),
                                    [], "MARKER", Path(directory), "endpoint", time.monotonic() + 10, stop)
            self.assertTrue(result["success"], result)
            self.assertFalse(stop.is_set())

    def test_missing_done_preserves_failure(self):
        raw = b'data: {"choices":[{"delta":{"content":"MARKER"}}]}\n\n'
        with tempfile.TemporaryDirectory() as directory, patch.object(runner, "post", return_value=Response(raw)):
            stop = threading.Event()
            result = runner.request(dict(request_id="r1", input_tokens=100, output_tokens=8),
                                    [], "MARKER", Path(directory), "endpoint", time.monotonic() + 10, stop)
            self.assertFalse(result["success"])
            self.assertTrue(stop.is_set())
            self.assertTrue((Path(directory) / "r1" / "response.sse").exists())


if __name__ == "__main__":
    unittest.main()
