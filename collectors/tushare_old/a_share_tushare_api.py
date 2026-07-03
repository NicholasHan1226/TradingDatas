"""Compatibility re-export: migrated from /opt/investment/Ashare/tools/a_share_tushare_api.py."""
import os, sys
_current_dir = os.path.dirname(os.path.realpath(__file__))
if _current_dir not in sys.path:
    sys.path.insert(0, _current_dir)
from tushare_api import *  # noqa: F401 F403 E402
# _call starts with underscore, not included by import *
from tushare_api import _call  # noqa: F401 E402
