"""
Административная панель (прямой URL). Перенаправление на pages/_analyst_params.py.
"""
import sys
from pathlib import Path

_here = Path(__file__).resolve().parent
_app_root = _here.parent
_p = _here.parent
while _p != _p.parent:
    if (_p / "auth.py").exists() and (_p / "config.py").exists():
        _app_root = _p
        break
    _p = _p.parent
sys.path.insert(0, str(_app_root))

from config import switch_page_app

switch_page_app("pages/_analyst_params.py")
