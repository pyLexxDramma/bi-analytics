# -*- coding: utf-8 -*-
"""Совместимость: раньше код жил здесь; сейчас реализация в ``ui_quiet`` (деплой без потерянного файла)."""
from .ui_quiet import filters_panel, inject_unified_filters_css

__all__ = ["filters_panel", "inject_unified_filters_css"]
