"""
Production UI: скрытие «серых» служебных подписей Streamlit (`st.caption`) в дашбордах.

См. `mapping_spec_v2` — раздел про отсутствие дебаг/сервисных подсказок в UI.
"""


def suppress_caption(*_args, **_kwargs) -> None:
    """No-op вместо `st.caption` — не рендерить мелкий серый текст под виджетами."""
    return None
