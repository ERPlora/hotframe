"""Tests for hotframe.templating."""
import pytest
from markupsafe import Markup

from hotframe.templating.alpine_helpers import alpine_cloak, alpine_data, alpine_show
from hotframe.templating.extensions import (
    render_icon,
    slugify_filter,
    static_url,
    truncatewords_filter,
    url_for_helper,
)
from hotframe.templating.htmx_helpers import hx_delete, hx_get, hx_post, hx_vals
from hotframe.templating.slots import SlotRegistry


class TestHTMXHelpers:
    def test_hx_get(self):
        result = hx_get("/search", target="#results", swap="innerHTML")
        assert 'hx-get="/search"' in result
        assert 'hx-target="#results"' in result
        assert 'hx-swap="innerHTML"' in result

    def test_hx_post(self):
        result = hx_post("/create", target="#list")
        assert 'hx-post="/create"' in result
        assert 'hx-target="#list"' in result

    def test_hx_delete(self):
        result = hx_delete("/item/1", confirm="Sure?")
        assert 'hx-delete="/item/1"' in result
        assert 'hx-confirm="Sure?"' in result
        assert 'hx-swap="outerHTML"' in result

    def test_hx_vals(self):
        result = hx_vals({"key": "value"})
        assert "hx-vals=" in result
        assert "key" in result

    def test_none_omitted(self):
        result = hx_get("/url")
        assert "hx-target" not in result
        assert "hx-swap" not in result


class TestAlpineHelpers:
    def test_alpine_data_dict(self):
        result = alpine_data({"count": 0, "open": False})
        assert "x-data=" in result
        assert '"count": 0' in result

    def test_alpine_show(self):
        result = alpine_show("open")
        assert 'x-show="open"' in result

    def test_alpine_cloak(self):
        result = alpine_cloak()
        assert result == Markup("x-cloak")


class TestSlotRegistry:
    @pytest.mark.asyncio
    async def test_register_and_render(self):
        registry = SlotRegistry()
        registry.register("test_slot", "<div>content</div>", module_id="test")
        items = await registry.get_entries("test_slot")
        assert len(items) >= 1


class TestGlobalFunctions:
    def test_static_url(self):
        assert static_url("css/main.css") == "/static/css/main.css"

    def test_url_for_module(self):
        assert url_for_helper("sales:dashboard") == "/m/sales/dashboard/"
        assert url_for_helper("customers.list") == "/m/customers/list/"

    def test_url_for_core(self):
        assert url_for_helper("settings") == "/settings"

    def test_render_icon(self):
        result = render_icon("home-outline")
        assert "iconify" in result
        assert "ion:home-outline" in result

    def test_render_icon_with_namespace(self):
        result = render_icon("material:search", size=20)
        assert "mdi:search" in result
        assert 'data-width="20"' in result


class TestFilters:
    def test_slugify(self):
        assert slugify_filter("Hello World!") == "hello-world"
        assert slugify_filter("Café & Bar") == "cafe-bar"

    def test_truncatewords(self):
        assert truncatewords_filter("one two three four five", 3) == "one two three\u2026"
        assert truncatewords_filter("short", 10) == "short"
        assert truncatewords_filter(None) == ""
