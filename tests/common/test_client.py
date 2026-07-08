"""Unit tests for src.common.client: HTTP retry classification."""

from __future__ import annotations

import httpx
import pytest

from src.common.client import _is_retryable_error


def _status_error(status_code: int) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://example.com")
    response = httpx.Response(status_code, request=request)
    return httpx.HTTPStatusError("error", request=request, response=response)


class TestIsRetryableError:
    def test_connect_error_is_retryable(self):
        assert _is_retryable_error(httpx.ConnectError("boom")) is True

    def test_timeout_exception_is_retryable(self):
        assert _is_retryable_error(httpx.TimeoutException("boom")) is True

    @pytest.mark.parametrize("status_code", [429, 500, 502, 503, 504])
    def test_retryable_http_status_codes(self, status_code):
        assert _is_retryable_error(_status_error(status_code)) is True

    @pytest.mark.parametrize("status_code", [400, 401, 403, 404, 422])
    def test_non_retryable_http_status_codes(self, status_code):
        assert _is_retryable_error(_status_error(status_code)) is False

    def test_unrelated_exception_is_not_retryable(self):
        assert _is_retryable_error(ValueError("boom")) is False
