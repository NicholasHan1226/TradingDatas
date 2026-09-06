from collections import Counter
from datetime import datetime, timedelta, timezone
import sqlite3

import pytest

import tools.run_binance_spot_canary as canary
from storage.schema import SCHEMA_SQL
from storage.schema_contract import PROVIDER_DATASET_ROWS_DDL

pytestmark = pytest.mark.slow


def _store(tmp_path, monkeypatch):
    path = tmp_path / 'facts.sqlite'
    with sqlite3.connect(path) as conn:
        conn.executescript(SCHEMA_SQL)
        conn.executescript(PROVIDER_DATASET_ROWS_DDL)
    monkeypatch.setenv('TRADINGDATAS_CANARY_MODE', 'binance_spot_v1')
    datasets = ('crypto.spot.binance.btcusdt.5m', 'crypto.spot.binance.ethusdt.5m')
    monkeypatch.setattr(canary, '_bar_datasets', lambda registry: datasets)
    now = datetime.now(timezone.utc)
    window = canary.latest_closed_window(now)
    monkeypatch.setattr(canary, 'latest_closed_window', lambda clock: window)
    calls = []

    def get(endpoint, query):
        calls.append(query['symbol'])
        return [[ms, '10', '12', '9', '11', '5', ms + 299999, '55', 2, '2', '22', '0']
                for ms in range(query['startTime'], query['endTime'], 300000)]

    monkeypatch.setattr(canary.BinanceSpotPublicCollector, '_get', staticmethod(get))
    return path, datasets, now, window, calls


def _counts(path):
    with sqlite3.connect(path) as conn:
        return tuple(conn.execute(f'SELECT count(*) FROM {table}').fetchone()[0]
                     for table in ('provider_dataset_rows', 'market_ingest_runs'))


def test_completed_primary_backup_makes_no_provider_or_receipt_write(tmp_path, monkeypatch):
    path, datasets, now, window, calls = _store(tmp_path, monkeypatch)
    primary = canary.run(db_path=path, lock_path=tmp_path / 'collect.lock', execute=True, now=now)
    assert primary['state'] == 'success'
    before = _counts(path)
    backup = canary.run(db_path=path, lock_path=tmp_path / 'collect.lock', execute=True,
                        now=now + timedelta(seconds=70), backup_wake=True)
    assert Counter(calls) == Counter(['BTCUSDT', 'ETHUSDT'])
    assert _counts(path) == before
    assert backup['skipped_completed_dataset_count'] == 2
    assert all(row['collection_action'] == 'reused_completed_receipt' for row in backup['datasets'])
    assert [row['receipt_ids'] for row in backup['datasets']] == [row['receipt_ids'] for row in primary['datasets']]


def test_partial_primary_backup_collects_only_missing_dataset(tmp_path, monkeypatch):
    path, datasets, now, window, calls = _store(tmp_path, monkeypatch)
    monkeypatch.setattr(canary, '_bar_datasets', lambda registry: datasets[:1])
    canary.run(db_path=path, lock_path=tmp_path / 'collect.lock', execute=True, now=now)
    monkeypatch.setattr(canary, '_bar_datasets', lambda registry: datasets)
    backup = canary.run(db_path=path, lock_path=tmp_path / 'collect.lock', execute=True,
                        now=now + timedelta(seconds=70), backup_wake=True)
    assert Counter(calls) == Counter(['BTCUSDT', 'ETHUSDT'])
    assert backup['skipped_completed_dataset_count'] == 1
    assert _counts(path) == (4, 2)


def test_invalid_completion_receipt_does_not_suppress_collection(tmp_path, monkeypatch):
    path, datasets, now, window, calls = _store(tmp_path, monkeypatch)
    canary.run(db_path=path, lock_path=tmp_path / 'collect.lock', execute=True, now=now)
    with sqlite3.connect(path) as conn:
        conn.execute('UPDATE market_ingest_runs SET rows_written = 999 WHERE source = ?', (datasets[0],))
    backup = canary.run(db_path=path, lock_path=tmp_path / 'collect.lock', execute=True,
                        now=now + timedelta(seconds=70), backup_wake=True)
    assert Counter(calls) == Counter(['BTCUSDT', 'ETHUSDT', 'BTCUSDT'])
    assert backup['skipped_completed_dataset_count'] == 1


def test_another_window_does_not_suppress_collection(tmp_path, monkeypatch):
    path, datasets, now, window, calls = _store(tmp_path, monkeypatch)
    canary.run(db_path=path, lock_path=tmp_path / 'collect.lock', execute=True, now=now)
    older = {key: canary._utc(datetime.fromisoformat(value.replace('Z', '+00:00')) - timedelta(minutes=5))
             for key, value in window.items()}
    monkeypatch.setattr(canary, 'latest_closed_window', lambda clock: older)
    backup = canary.run(db_path=path, lock_path=tmp_path / 'collect.lock', execute=True,
                        now=now + timedelta(seconds=70), backup_wake=True)
    assert Counter(calls) == Counter(['BTCUSDT', 'ETHUSDT', 'BTCUSDT', 'ETHUSDT'])
    assert backup['skipped_completed_dataset_count'] == 0
