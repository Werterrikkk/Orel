import io
import json
from urllib.error import HTTPError, URLError

import pytest

from orel import telegram_client
from orel.telegram_client import TelegramClient, TelegramError

TOKEN = "123456:TEST_ONLY_PRIVATE_TOKEN_VALUE"


class Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def test_transport_uploads_the_real_photo_as_multipart_without_markup(tmp_path, monkeypatch):
    photo = tmp_path / "frame.jpg"
    photo.write_bytes(b"actual test jpeg")
    requests = []

    def open_request(request, timeout):
        requests.append(request)
        assert timeout == 8
        return Response(json.dumps({"ok": True, "result": {"message_id": 7}}).encode())

    monkeypatch.setattr(telegram_client, "urlopen", open_request)
    result = TelegramClient(TOKEN).call(
        "sendPhoto", {"chat_id": "42", "caption": "Каска не обнаружена"}, photo
    )
    assert result["message_id"] == 7
    assert b"actual test jpeg" in requests[0].data
    assert "Каска не обнаружена".encode() in requests[0].data
    assert "multipart/form-data" in requests[0].get_header("Content-type")
    assert b"parse_mode" not in requests[0].data


def test_api_rate_limit_is_a_safe_retry_with_server_delay(monkeypatch):
    def limited(*args, **kwargs):
        raise HTTPError(
            f"https://api.telegram.org/bot{TOKEN}/sendPhoto",
            429,
            TOKEN,
            {},
            io.BytesIO(
                json.dumps(
                    {
                        "ok": False,
                        "error_code": 429,
                        "parameters": {"retry_after": 7},
                        "description": TOKEN,
                    }
                ).encode()
            ),
        )

    monkeypatch.setattr(telegram_client, "urlopen", limited)
    with pytest.raises(TelegramError) as caught:
        TelegramClient(TOKEN).call("sendMessage", {"chat_id": "42", "text": "test"})
    assert caught.value.retry_after == 7
    assert TOKEN not in str(caught.value)


def test_network_error_never_leaks_bot_url_or_claims_definite_failure(monkeypatch):
    def timeout(*args, **kwargs):
        raise URLError(TOKEN)

    monkeypatch.setattr(telegram_client, "urlopen", timeout)
    with pytest.raises(TelegramError) as caught:
        TelegramClient(TOKEN).call("sendMessage", {"chat_id": "42", "text": "test"})
    assert caught.value.uncertain is True
    assert TOKEN not in str(caught.value)
