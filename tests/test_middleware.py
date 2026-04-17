"""Tests for hotframe.middleware."""
from hotframe.middleware.body_limit import BodyLimitMiddleware
from hotframe.middleware.htmx import HtmxDetails, HtmxMiddleware
from hotframe.middleware.timeout import TimeoutMiddleware
from hotframe.middleware.trailing_slash import TrailingSlashMiddleware


class TestHtmxDetails:
    def test_default_values(self):
        details = HtmxDetails()
        assert details.is_htmx is False
        assert details.boosted is False
        assert details.target is None
        assert details.trigger is None


class TestMiddlewareImports:
    def test_htmx_middleware(self):
        assert HtmxMiddleware is not None

    def test_body_limit(self):
        assert BodyLimitMiddleware is not None

    def test_timeout(self):
        assert TimeoutMiddleware is not None

    def test_trailing_slash(self):
        assert TrailingSlashMiddleware is not None
