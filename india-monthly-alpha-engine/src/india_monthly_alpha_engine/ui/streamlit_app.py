"""Phase 18: minimal Streamlit read-only dashboard.

Per architecture.md section 2 the UI is read-only over the DB and
generated reports; it does NOT invoke engines directly. Decisions are
persisted by `imae monthly` (Phase 12 deployment engine) and surfaced
here.

Run with: `streamlit run -m india_monthly_alpha_engine.ui.streamlit_app`.
Streamlit is NOT a hard dependency — pyproject lists it as an optional
extra. This module imports it lazily so unit tests do not require it.
"""

from __future__ import annotations


def main() -> None:
    try:
        import streamlit as st
    except ImportError as e:
        raise SystemExit(
            "streamlit is not installed. Install via: pip install streamlit"
        ) from e

    st.set_page_config(page_title="india-monthly-alpha-engine", layout="wide")
    st.title("India Monthly Alpha Engine")
    st.caption(
        "Personal-use Indian equity monthly capital deployment. "
        "Read-only dashboard. Decisions are computed by `imae monthly`."
    )

    st.markdown(
        "## Phase 18 placeholder\n\n"
        "Full dashboard wiring is the last Phase 18 task: it surfaces the "
        "latest monthly deployment plan, the portfolio review report, and "
        "a backtest summary. The engines and reports modules already produce "
        "this content; the UI consumes them."
    )


if __name__ == "__main__":
    main()
