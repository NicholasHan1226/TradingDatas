from collectors.tushare import tushare_api


def test_empty_tushare_result_is_not_cached(monkeypatch):
    calls = []
    responses = [[], [{"ts_code": "000001.SZ"}]]

    def fake_rows(*args, **kwargs):
        calls.append((args, kwargs))
        return responses.pop(0)

    tushare_api._clear_cache()
    monkeypatch.setattr(tushare_api, "tushare_rows", fake_rows)

    assert tushare_api._call("rt_min", {"ts_code": "000001.SZ"}) == []
    assert tushare_api._call("rt_min", {"ts_code": "000001.SZ"}) == [{"ts_code": "000001.SZ"}]
    assert len(calls) == 2


def test_non_empty_tushare_result_is_cached(monkeypatch):
    calls = []

    def fake_rows(*args, **kwargs):
        calls.append((args, kwargs))
        return [{"ts_code": "000001.SZ"}]

    tushare_api._clear_cache()
    monkeypatch.setattr(tushare_api, "tushare_rows", fake_rows)

    assert tushare_api._call("rt_min", {"ts_code": "000001.SZ"}) == [{"ts_code": "000001.SZ"}]
    assert tushare_api._call("rt_min", {"ts_code": "000001.SZ"}) == [{"ts_code": "000001.SZ"}]
    assert len(calls) == 1
