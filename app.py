"""
REMO_OX Financial Analytics - Streamlit Web Interface

Cloud-hosted AI-powered financial analytics tool.
Upload Excel data, chat with any LLM, generate charts and PDF reports.
"""

import asyncio
import json
import logging
import os
from pathlib import Path

import streamlit as st

from session_manager import (
    cleanup_old_sessions,
    create_session,
    get_data_file_path,
    get_session_path,
    list_sessions,
    load_session,
    save_chat,
    save_upload,
)
from llm_client import chat_with_tools, MCP_SERVER_URL

# ---------------------------------------------------------------------------
# Logging — never log API keys
# ---------------------------------------------------------------------------
logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Page configuration
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="REMO_OX Financial Analytics",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Custom CSS
# ---------------------------------------------------------------------------
st.markdown(
    """
<style>
    .main-header {
        background: linear-gradient(135deg, #1a237e 0%, #0d47a1 50%, #2196F3 100%);
        padding: 1.5rem 2rem;
        border-radius: 12px;
        margin-bottom: 1.5rem;
        color: white;
        text-align: center;
    }
    .main-header h1 { margin: 0; font-size: 2rem; }
    .main-header p  { margin: 0.3rem 0 0; opacity: 0.85; font-size: 0.95rem; }
    .session-badge {
        background: #e3f2fd;
        display: inline-block;
        padding: 0.3rem 0.8rem;
        border-radius: 20px;
        font-family: monospace;
        font-size: 0.9rem;
        color: #1565c0;
        margin-top: 0.3rem;
    }
</style>
""",
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _run_async(coro):
    """Run an async coroutine from synchronous Streamlit code."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(asyncio.run, coro).result()
        else:
            return loop.run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)


def _init_session_state():
    """Initialize Streamlit session-state variables on first load."""
    defaults = {
        "session_id": None,
        "messages": [],
        "file_info": None,
        "generated_files": [],
    }
    for key, val in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = val


# ---------------------------------------------------------------------------
# UI Components
# ---------------------------------------------------------------------------
def _render_header():
    st.markdown(
        """
    <div class="main-header">
        <h1>📊 REMO_OX Financial Analytics</h1>
        <p>AI-Powered Financial Data Analysis &bull; Upload Excel &bull;
           Chat &bull; Visualize &bull; Report</p>
    </div>
    """,
        unsafe_allow_html=True,
    )


def _render_sidebar() -> tuple[str, str, str | None]:
    """
    Render the full sidebar: LLM config, session management, file upload,
    and downloads.  Returns (model, api_key, api_base).
    """
    with st.sidebar:
        st.header("⚙️ Configuration")

        # ── LLM Configuration ──────────────────────────────────────────
        st.subheader("🤖 LLM Provider")

        provider_presets = {
            "Google Gemini": {"placeholder": "gemini-1.5-flash"},
            "OpenAI": {"placeholder": "gpt-4o-mini"},
            "Anthropic": {"placeholder": "claude-3-5-sonnet-20241022"},
            "Groq": {"placeholder": "groq/llama-3.3-70b-versatile"},
            "OpenRouter": {"placeholder": "openrouter/auto"},
            "Ollama (Local)": {"placeholder": "ollama/llama3"},
            "Azure OpenAI": {"placeholder": "azure/gpt-4o"},
            "Custom (OpenAI-compatible)": {"placeholder": "model-name"},
        }

        provider = st.selectbox("Provider", list(provider_presets.keys()))
        preset = provider_presets[provider]

        model_input = st.text_input(
            "Model Name",
            value=preset["placeholder"],
            help="Model identifier (e.g. gemini-1.5-flash, gemini-2.0-flash, gpt-4o-mini).",
        )

        # Normalize model string for litellm if needed
        model = model_input.strip()
        if provider == "Google Gemini":
            if model.startswith("models/"):
                model = model.replace("models/", "")
            if not model.startswith("gemini/"):
                model = f"gemini/{model}"

        api_key = st.text_input(
            "API Key",
            type="password",
            help="Your API key — never stored or logged.",
            placeholder="sk-… or provider key",
        )

        api_base: str | None = None
        if provider in ("Ollama (Local)", "Azure OpenAI", "Custom (OpenAI-compatible)"):
            default_base = (
                "http://host.docker.internal:11434"
                if provider == "Ollama (Local)"
                else ""
            )
            api_base = st.text_input(
                "API Base URL",
                value=default_base,
                help="Custom API endpoint.",
            )

        needs_key = provider not in ("Ollama (Local)",)
        if needs_key and not api_key:
            st.warning("⚠️ Enter your API key to start chatting.")

        st.divider()

        # ── Session Management ─────────────────────────────────────────
        st.subheader("📁 Sessions")

        col1, col2 = st.columns(2)
        with col1:
            if st.button("🆕 New", use_container_width=True):
                sid = create_session()
                st.session_state.session_id = sid
                st.session_state.messages = []
                st.session_state.file_info = None
                st.session_state.generated_files = []
                st.rerun()

        resume_id = st.text_input(
            "Resume Session ID",
            placeholder="e.g. a1b2c3d4e5f6",
        )
        if st.button("📂 Resume", use_container_width=True) and resume_id:
            data = load_session(resume_id.strip())
            if data:
                st.session_state.session_id = resume_id.strip()
                st.session_state.messages = data["chat_history"]
                meta = data["meta"]
                if meta.get("file_original_name"):
                    st.session_state.file_info = {
                        "original_name": meta["file_original_name"],
                        "columns": meta.get("columns", []),
                        "row_count": meta.get("row_count", 0),
                    }
                else:
                    st.session_state.file_info = None
                st.session_state.generated_files = []
                st.success("✅ Session restored!")
                st.rerun()
            else:
                st.error(f"❌ Session '{resume_id}' not found.")

        # Current session indicator
        if st.session_state.session_id:
            st.markdown(
                f'<div class="session-badge">'
                f"🔑 {st.session_state.session_id}</div>",
                unsafe_allow_html=True,
            )

        # List recent sessions
        with st.expander("📋 Recent Sessions"):
            sessions = list_sessions()
            if sessions:
                for s in sessions[:10]:
                    label = (
                        f"**{s['session_id']}** — "
                        f"{s.get('file_original_name') or 'No file'} — "
                        f"{s.get('created_at', '')[:16]}"
                    )
                    st.markdown(label)
            else:
                st.caption("No sessions yet.")

        st.divider()

        # ── File Upload ────────────────────────────────────────────────
        st.subheader("📤 Upload Data")

        if not st.session_state.session_id:
            st.info("Create or resume a session first.")
        else:
            uploaded = st.file_uploader(
                "Upload Excel file",
                type=["xlsx"],
                help="Only .xlsx files are accepted.",
            )

            if uploaded is not None and st.button(
                "📥 Process File", use_container_width=True
            ):
                with st.spinner("Validating and processing…"):
                    try:
                        info = save_upload(
                            session_id=st.session_state.session_id,
                            file_bytes=uploaded.getvalue(),
                            original_name=uploaded.name,
                            mime_type=uploaded.type or "",
                        )
                        st.session_state.file_info = info
                        st.success(
                            f"✅ **{uploaded.name}** loaded!  \n"
                            f"📋 {info['row_count']} rows, "
                            f"{len(info['columns'])} columns"
                        )
                    except ValueError as exc:
                        st.error(f"❌ {exc}")

            # Show current file info
            fi = st.session_state.file_info
            if fi and isinstance(fi, dict) and fi.get("columns"):
                st.markdown(
                    f"📄 **{fi.get('original_name', 'data.xlsx')}** — "
                    f"{fi.get('row_count', '?')} rows"
                )
                cols_str = ", ".join(
                    f"`{c['name']}`" for c in fi["columns"]
                )
                st.markdown(f"**Columns:** {cols_str}")

        st.divider()

        # ── Downloads ──────────────────────────────────────────────────
        st.subheader("📥 Downloads")
        if st.session_state.session_id:
            sdir = get_session_path(st.session_state.session_id)
            if sdir.exists():
                charts = sorted(list(sdir.glob("*.png")) + list(sdir.glob("*.jpg")))
                for cp in charts:
                    with open(cp, "rb") as f:
                        st.download_button(
                            f"📊 {cp.name}",
                            f.read(),
                            file_name=cp.name,
                            mime="image/png",
                            use_container_width=True,
                            key=f"sb_chart_{cp.name}",
                        )
                pdfs = sorted(sdir.glob("*.pdf"))
                for pp in pdfs:
                    with open(pp, "rb") as f:
                        st.download_button(
                            f"📄 {pp.name}",
                            f.read(),
                            file_name=pp.name,
                            mime="application/pdf",
                            use_container_width=True,
                            key=f"sb_pdf_{pp.name}",
                        )
                if not charts and not pdfs:
                    st.caption(
                        "No files generated yet. Chat to create charts and reports!"
                    )
        else:
            st.caption("Start a session to see downloads.")

    return model, api_key, api_base


def _render_chat(model: str, api_key: str, api_base: str | None):
    """Render the main chat interface."""

    if not st.session_state.session_id:
        st.info(
            "👈 **Create a new session** or **resume an existing one** "
            "from the sidebar to get started."
        )
        st.markdown(
            """
            ### Quick Start
            1. Click **🆕 New** in the sidebar to create a session
            2. Upload your `.xlsx` data file
            3. Configure your LLM provider and API key
            4. Start chatting! Ask questions like:
               - *"Show me a summary of my data"*
               - *"Generate a bar chart of Revenue by Month"*
               - *"Export a PDF report with the analysis"*
            """
        )
        return

    # Display chat history
    for idx, msg in enumerate(st.session_state.messages):
        role = msg.get("role", "")
        if role not in ("user", "assistant"):
            continue
        with st.chat_message(role):
            st.markdown(msg["content"])
            # Show inline images if any
            for img_path in msg.get("images", []):
                if Path(img_path).exists():
                    st.image(img_path, use_container_width=True)
            # Show inline PDF download buttons if any
            for p_idx, pdf_path in enumerate(msg.get("pdfs", [])):
                pp = Path(pdf_path)
                if pp.exists():
                    with open(pp, "rb") as f:
                        st.download_button(
                            f"📄 Download {pp.name}",
                            f.read(),
                            file_name=pp.name,
                            mime="application/pdf",
                            key=f"chat_pdf_{idx}_{p_idx}",
                        )

    # Chat input
    prompt = st.chat_input(
        "Ask about your data… (e.g., 'Show me a summary')"
    )
    if not prompt:
        return

    # Pre-flight checks
    needs_key = model and not model.startswith("ollama/")
    if needs_key and not api_key:
        st.error("⚠️ Please enter your API key in the sidebar.")
        return

    data_file = get_data_file_path(st.session_state.session_id)
    if not data_file:
        st.warning("📤 Please upload a data file first (sidebar).")
        return

    # Display user message
    with st.chat_message("user"):
        st.markdown(prompt)
    st.session_state.messages.append({"role": "user", "content": prompt})

    # Get LLM + MCP response
    with st.chat_message("assistant"):
        with st.spinner("🔍 Analyzing…"):
            try:
                session_dir = str(
                    get_session_path(st.session_state.session_id)
                )

                response_text, updated_msgs, gen_files = _run_async(
                    chat_with_tools(
                        messages=[
                            {"role": m["role"], "content": m["content"]}
                            for m in st.session_state.messages
                        ],
                        model=model,
                        api_key=api_key or None,
                        api_base=api_base or None,
                        session_dir=session_dir,
                        server_url=MCP_SERVER_URL,
                        file_info=st.session_state.file_info,
                    )
                )

                st.markdown(response_text)

                # Show generated charts and pdfs inline
                new_images: list[str] = []
                new_pdfs: list[str] = []
                for fpath in gen_files:
                    p = Path(fpath)
                    if p.suffix in (".png", ".jpg") and p.exists():
                        st.image(str(p), use_container_width=True)
                        new_images.append(fpath)
                    elif p.suffix == ".pdf" and p.exists():
                        new_pdfs.append(fpath)
                        with open(p, "rb") as f:
                            st.download_button(
                                f"📥 Download PDF: {p.name}",
                                f.read(),
                                file_name=p.name,
                                mime="application/pdf",
                                key=f"chat_pdf_direct_{p.name}",
                            )

                # Persist to session state + disk
                st.session_state.messages.append(
                    {
                        "role": "assistant",
                        "content": response_text,
                        "images": new_images,
                        "pdfs": new_pdfs,
                    }
                )
                save_chat(
                    st.session_state.session_id,
                    st.session_state.messages,
                )

                # Refresh sidebar to show new download buttons
                if gen_files:
                    st.rerun()

            except Exception as exc:
                logger.exception("Chat error")
                st.error(f"❌ Error: {exc}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def _ensure_mcp_server_running():
    """Ensure MCP server runs in the background when hosted on Streamlit Cloud."""
    import socket
    import subprocess
    import sys
    import time

    def _is_port_open(port=8000):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.5)
                return s.connect_ex(("127.0.0.1", port)) == 0
        except Exception:
            return False

    if not _is_port_open(8000):
        logger.info("Starting background MCP server...")
        server_script = Path(__file__).parent / "mcp_server.py"
        log_file = Path(__file__).parent / "mcp_server_output.log"
        with open(log_file, "a", encoding="utf-8") as out:
            subprocess.Popen(
                [sys.executable, str(server_script)],
                stdout=out,
                stderr=out,
                env=dict(os.environ),
            )
        # Wait up to 5 seconds for the server to bind
        for _ in range(10):
            time.sleep(0.5)
            if _is_port_open(8000):
                logger.info("MCP server is now listening on 8000.")
                break


def main():
    _init_session_state()
    _render_header()

    # Auto-cleanup old sessions (runs once per app boot, fast no-op usually)
    cleanup_old_sessions(max_age_hours=72)

    model, api_key, api_base = _render_sidebar()
    _render_chat(model, api_key, api_base)


if __name__ == "__main__":
    _ensure_mcp_server_running()
    main()
