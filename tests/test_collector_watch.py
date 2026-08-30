"""Exercise the deployed patrol without touching host services or logs."""
import json
import os
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / 'deploy/tradingdatas-collector-watch.sh'


@pytest.mark.parametrize('success_age,failures,expected', [(30, 6, 'ALERT'), (1, 6, 'WARN'), (1, 0, 'OK')])
def test_failed_receipts_do_not_refresh_successful_capture(tmp_path, success_age, failures, expected):
    pm = tmp_path / 'polymarket'
    for name in ('captures', 'receipts'):
        (pm / name).mkdir(parents=True)
    now = datetime.now(timezone.utc)
    receipt = {'capture_id': 'good', 'state': 'success', 'observed_at': (now - timedelta(hours=success_age)).isoformat(), 'market_count': 1, 'snapshot_count': 1}
    capture = {'receipt': receipt, 'market_records': [{}], 'snapshot_records': [{}]}
    (pm / 'captures/good.json').write_text(json.dumps(capture))
    for i in range(failures):
        bad = {'capture_id': f'bad{i}', 'state': 'failed', 'observed_at': (now - timedelta(minutes=i)).isoformat()}
        (pm / f'receipts/bad{i}.json').write_text(json.dumps(bad))
    # New file mtimes do not repair a 30-hour-old observation.
    result = _run_patrol(tmp_path, pm)
    pm_lines = [line for line in result.splitlines() if 'polymarket-snapshot' in line]
    assert len(pm_lines) == 1
    assert pm_lines[0].startswith(f'[{expected}]')


def test_malformed_capture_reports_inspection_alert(tmp_path):
    pm = tmp_path / 'polymarket'
    (pm / 'captures').mkdir(parents=True)
    (pm / 'captures/bad.json').write_text('{')
    assert '[ALERT] polymarket-snapshot reason=invalid-receipts' in _run_patrol(tmp_path, pm)


def _run_patrol(tmp_path, pm):
    log = tmp_path / 'patrol.log'
    re_dir = tmp_path / 'eval'
    re_dir.mkdir()
    (re_dir / 'entry-test.json').write_text('{}')
    bindir = tmp_path / 'bin'
    bindir.mkdir()
    for name, body in {
        'journalctl': 'echo \'{"state":"success"}\'',
        'systemctl': 'exit 0',
        'curl': 'printf 401',
        # The existing shell uses GNU stat; keep this test portable on macOS.
        'stat': 'date +%s',
    }.items():
        path = bindir / name
        path.write_text('#!/bin/sh\n' + body + '\n')
        path.chmod(0o755)
    text = SCRIPT.read_text().replace('/var/log/tradingdatas-collector-watch.log', str(log)).replace('/opt/investment-data/tradingdatas-crypto/polymarket', str(pm)).replace('/var/lib/tradingagent/crypto-40-symbol-rolling-eval', str(re_dir))
    script = tmp_path / 'watch.sh'
    script.write_text(text)
    proc = subprocess.run(['bash', str(script)], env={**os.environ, 'PATH': str(bindir) + os.pathsep + os.environ['PATH']}, capture_output=True, text=True, timeout=10)
    assert proc.returncode in (0, 1), proc.stderr
    return log.read_text()
