#!/bin/bash
set -euo pipefail

export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
umask 077

python_runtime=/opt/tradingdatas/venv/bin/python3
implementation=/usr/local/lib/tradingdatas-release/production_core_release.py
installed_helper=/usr/local/sbin/tradingdatas-core-release

[[ "$EUID" -eq 0 ]] || {
  echo "tradingdatas-core-release wrapper must run as root" >&2
  exit 1
}
[[ $# -eq 0 ]] || {
  echo "tradingdatas-core-release wrapper accepts no arguments" >&2
  exit 1
}
[[ "$(/usr/bin/readlink -f -- "$0")" == "$installed_helper" ]] || {
  echo "tradingdatas-core-release wrapper must run from $installed_helper" >&2
  exit 1
}
[[ "$(/usr/bin/stat -c '%U:%G %a %h' -- "$installed_helper")" == 'root:root 755 1' ]] || {
  echo "installed wrapper ownership/mode is unsafe" >&2
  exit 1
}
[[ "$(/usr/bin/stat -c '%U:%G %a %h' -- "$implementation")" == 'root:root 444 1' ]] || {
  echo "installed Python implementation ownership/mode is unsafe" >&2
  exit 1
}

python_real="$(/usr/bin/readlink -f -- "$python_runtime")"
[[ -n "$python_real" && -f "$python_real" ]] || {
  echo "trusted Python runtime is missing" >&2
  exit 1
}
python_meta="$(/usr/bin/stat -c '%U:%G %a' -- "$python_real")"
python_owner_mode="${python_meta% *}"
python_mode="${python_meta##* }"
[[ "$python_owner_mode" == 'root:root' ]] || {
  echo "trusted Python runtime must be root:root" >&2
  exit 1
}
(( (8#$python_mode & 0022) == 0 )) || {
  echo "trusted Python runtime must not be group/other writable" >&2
  exit 1
}

exec "$python_runtime" -I -S -c '
import sys
from pathlib import Path

implementation = Path("/usr/local/lib/tradingdatas-release/production_core_release.py")
source = implementation.read_bytes()
sys.argv = ["/usr/local/sbin/tradingdatas-core-release"]
namespace = {
    "__name__": "__main__",
    "__file__": str(implementation),
    "__package__": None,
    "__cached__": None,
}
exec(compile(source, str(implementation), "exec"), namespace, namespace)
'
