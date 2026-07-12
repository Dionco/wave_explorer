import os
import time
from wave_explorer.full_model.__main__ import is_cache_valid


def test_cache_invalid_when_missing(tmp_path):
    assert is_cache_valid(tmp_path / "model-full.fits", tmp_path / "results.txt") is False


def test_cache_valid_when_newer(tmp_path):
    res = tmp_path / "results.txt"
    res.write_text("x")
    cache = tmp_path / "model-full.fits"
    cache.write_text("y")
    now = time.time()
    os.utime(res, (now - 10, now - 10))
    os.utime(cache, (now, now))
    assert is_cache_valid(cache, res) is True


def test_cache_invalid_when_stale(tmp_path):
    res = tmp_path / "results.txt"
    res.write_text("x")
    cache = tmp_path / "model-full.fits"
    cache.write_text("y")
    now = time.time()
    os.utime(cache, (now - 10, now - 10))
    os.utime(res, (now, now))
    assert is_cache_valid(cache, res) is False


def test_cache_invalid_when_config_copy_newer(tmp_path):
    # F6: the driver also reads config_copy.ini, so an edited config must
    # invalidate a cache that is still newer than results.txt.
    res = tmp_path / "results.txt"
    res.write_text("x")
    cache = tmp_path / "model-full.fits"
    cache.write_text("y")
    cfg = tmp_path / "config_copy.ini"
    cfg.write_text("z")
    now = time.time()
    os.utime(res, (now - 20, now - 20))
    os.utime(cache, (now - 10, now - 10))
    os.utime(cfg, (now, now))
    assert is_cache_valid(cache, res) is False


def test_cache_valid_when_newer_than_config_copy_too(tmp_path):
    res = tmp_path / "results.txt"
    res.write_text("x")
    cache = tmp_path / "model-full.fits"
    cache.write_text("y")
    cfg = tmp_path / "config_copy.ini"
    cfg.write_text("z")
    now = time.time()
    os.utime(cfg, (now - 20, now - 20))
    os.utime(res, (now - 10, now - 10))
    os.utime(cache, (now, now))
    assert is_cache_valid(cache, res) is True
