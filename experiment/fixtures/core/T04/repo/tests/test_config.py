"""Tests for clientconfig."""

import pytest
from clientconfig.config import get_timeout, get_host, get_retries
from clientconfig.loader import parse_config, merge_configs


def test_default_timeout():
    """Verify default timeout of 30 when configuration specifies 30."""
    cfg = {"timeout": 30}
    assert get_timeout(cfg) == 30


def test_empty_config():
    """Verify empty configuration defaults to 30."""
    assert get_timeout({}) == 30


def test_loader_roundtrip():
    """Verify timeout extraction from normalized configuration."""
    cfg = parse_config({"timeout": 30, "host": "127.0.0.1"})
    assert get_timeout(cfg) == 30


def test_get_host_default():
    """Verify default host extraction."""
    assert get_host({}) == "localhost"


def test_get_retries_default():
    """Verify default retries extraction."""
    assert get_retries({}) == 3


def test_merge_configs():
    """Verify merge configs functionality."""
    res = merge_configs({"timeout": 30}, {"host": "remote"})
    assert res["timeout"] == 30
    assert res["host"] == "remote"
