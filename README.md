# 📊 REMO_OX Financial Analytics

> AI-Powered Financial Data Analysis — Upload Excel, Chat with Any LLM, Visualize & Report

REMO_OX is a cloud-ready financial analytics platform built on the **Model Context Protocol (MCP)**. It combines an MCP tool server with a Streamlit web interface, letting users upload Excel data and interact with any LLM to get instant statistical analysis, charts, and PDF reports.

---

## ✨ Features

- **📤 Upload Any Excel File** — Works with any `.xlsx` file, any columns, any structure
- **🤖 Universal LLM Support** — OpenAI, Anthropic, Google Gemini, Groq, Ollama (local), Azure, OpenRouter, and any OpenAI-compatible API
- **📊 Smart Data Analysis** — Statistical summaries, correlations, missing values, value counts, and more
- **📈 Chart Generation** — Bar, line, pie, scatter, and histogram charts via Matplotlib
- **📄 PDF Reports** — Professional branded reports with embedded charts
- **💾 Persistent Sessions** — Resume any session by ID — chat history, data, and generated files are preserved
- **🔒 Secure** — API keys are never stored/logged, file uploads are triple-validated, paths are sandboxed
- **🐳 Docker Ready** — One-command deployment with `docker-compose`

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Docker Compose                          │
│                                                                │
│  ┌─────────────────────┐      ┌──────────────────────────┐     │
│  │  Streamlit (8501)   │      │   MCP Server (8000)      │     │
│  │                     │ SSE  │                          │     │
│  │  • Chat UI          │◄────►│  • analyze_data          │     │
│  │  • File Upload      │      │  • generate_chart        │     │
│  │  • Session Manager  │      │  • export_pdf_report     │     │
│  │  • LiteLLM Client   │      │                          │     │
│  └─────────┬───────────┘      └────────────┬─────────────┘     │
│            │                               │                   │
│            └───────────┬───────────────────┘                   │
│                        ▼                                       │
│              📁 sessions/ (shared volume)                      │
│              ├── session_abc123/                                │
│              │   ├── meta.json                                 │
│              │   ├── chat_history.json                         │
│              │   ├── data.xlsx                                 │
│              │   ├── chart_*.png                               │
│              │   └── report_*.pdf                              │
│              └── session_def456/                                │
└─────────────────────────────────────────────────────────────────┘
                         │
                         ▼
                   Any LLM Provider
           (OpenAI / Anthropic / Gemini /
            Ollama / Groq / Azure / ...)
```

---

## 🚀 Quick Start

### Option 1: Docker (Recommended)

```bash
# Clone the repository
git clone <your-repo-url>
cd tools_mcp_analysis

# Build and start both services
docker-compose up --build

# Open in browser
# → http://localhost:8501
```

### Option 2: Local Development

```bash
# 1. Create virtual environment
uv venv
# Windows:
.venv\Scripts\activate
# Linux/macOS:
source .venv/bin/activate

# 2. Install dependencies
uv pip install -r requirements.txt

# 3. Start MCP Server (Terminal 1)
python mcp_server.py

# 4. Start Streamlit App (Terminal 2)
streamlit run app.py

# 5. Open http://localhost:8501
```

---

## 📖 Usage Guide

### Step 1: Create a Session
Click **🆕 New** in the sidebar. You'll get a unique session ID (e.g., `a1b2c3d4e5f6`). **Save this ID** to resume your session later.

### Step 2: Configure Your LLM
In the sidebar under **🤖 LLM Provider**:
1. Select your provider from the dropdown
2. Enter/adjust the model name
3. Enter your API key (masked, never stored)
4. For Ollama or custom endpoints, enter the Base URL

### Step 3: Upload Your Data
Click **📤 Upload Data** and select your `.xlsx` file. The system will:
- ✅ Validate the file extension
- ✅ Check the MIME type
- ✅ Verify it's a readable Excel file
- 📋 Display column names and row count

### Step 4: Chat!
Use the chat input to ask questions about your data:

| Example Prompt | What Happens |
|---|---|
| "Show me a summary of my data" | Calls `analyze_data` → returns statistics |
| "What columns do I have?" | Calls `analyze_data` → lists columns with types |
| "Generate a bar chart of Revenue by Month" | Calls `generate_chart` → shows chart inline |
| "Show me the correlation between columns" | Calls `analyze_data` → correlation matrix |
| "Export a PDF report with the analysis" | Calls `export_pdf_report` → download from sidebar |
| "Are there any missing values?" | Calls `analyze_data` → missing value analysis |

### Step 5: Download Results
Generated charts and PDF reports appear in the sidebar under **📥 Downloads**.

### Resuming a Session
Enter your session ID in the **Resume Session ID** field and click **📂 Resume**. Your chat history, uploaded file, and generated files will be restored.

---

## 🤖 Supported LLM Providers

| Provider | Model Format | API Key | Base URL |
|----------|-------------|---------|----------|
| **OpenAI** | `gpt-4o`, `gpt-4o-mini` | ✅ Required | — |
| **Anthropic** | `claude-3-5-sonnet-20241022` | ✅ Required | — |
| **Google Gemini** | `gemini/gemini-pro` | ✅ Required | — |
| **Groq** | `groq/llama-3.1-70b-versatile` | ✅ Required | — |
| **Ollama (Local)** | `ollama/llama3` | ❌ | `http://localhost:11434` |
| **Azure OpenAI** | `azure/gpt-4o` | ✅ Required | ✅ Required |
| **OpenRouter** | `openrouter/auto` | ✅ Required | — |
| **Together AI** | `together_ai/meta-llama/...` | ✅ Required | — |
| **Custom** | Any model name | ✅ Required | ✅ Required |

> Powered by [LiteLLM](https://docs.litellm.ai/) — supports 100+ providers with a unified API.

---

## ☁️ Cloud Deployment

### Google Cloud Run

```bash
# Build and push the images
gcloud builds submit --tag gcr.io/PROJECT_ID/remo-ox-mcp --dockerfile Dockerfile.mcp
gcloud builds submit --tag gcr.io/PROJECT_ID/remo-ox-app --dockerfile Dockerfile.app

# Deploy MCP server (internal only)
gcloud run deploy remo-ox-mcp \
  --image gcr.io/PROJECT_ID/remo-ox-mcp \
  --port 8000 \
  --no-allow-unauthenticated

# Deploy Streamlit app (public)
gcloud run deploy remo-ox-app \
  --image gcr.io/PROJECT_ID/remo-ox-app \
  --port 8501 \
  --set-env-vars MCP_SERVER_URL=https://remo-ox-mcp-HASH.run.app/sse \
  --allow-unauthenticated
```

### Railway / Render / Fly.io

These platforms support `docker-compose.yml` natively or can deploy each Dockerfile as a separate service. Set the environment variable `MCP_SERVER_URL` on the Streamlit service to point to the MCP server's internal URL.

---

## 🔒 Security

| Feature | Implementation |
|---------|---------------|
| **API Key Protection** | Masked input (`type="password"`), held only in browser session state, never logged or written to disk |
| **File Validation** | Triple check: extension (`.xlsx`), MIME type, and actual Pandas readability |
| **Path Sanitization** | `werkzeug.secure_filename()` on all user inputs; file paths are server-generated |
| **Session Isolation** | Each session has its own directory; session IDs are validated against path traversal |
| **Auto-Cleanup** | Sessions older than 72 hours are automatically removed |

---

## 🛠️ MCP Tools Reference

### `analyze_data`
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `file_path` | string | ✅ | Path to the Excel file |
| `query_type` | string | ✅ | One of: `summary`, `columns`, `head`, `tail`, `describe`, `shape`, `dtypes`, `value_counts`, `unique`, `missing`, `corr` |
| `column` | string | ❌ | Target column (required for `value_counts`, `unique`) |
| `n_rows` | integer | ❌ | Rows to show for `head`/`tail` (default: 5) |

### `generate_chart`
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `file_path` | string | ✅ | Path to the Excel file |
| `x_column` | string | ✅ | X-axis column name |
| `y_column` | string | ⚠️ | Y-axis column (not needed for `hist`) |
| `chart_type` | string | ✅ | One of: `bar`, `line`, `pie`, `scatter`, `hist` |
| `title` | string | ❌ | Custom chart title |
| `output_path` | string | ✅ | Output PNG path |

### `export_pdf_report`
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `summary_text` | string | ✅ | Report body text |
| `output_path` | string | ✅ | Output PDF path |
| `chart_path` | string | ❌ | Chart image to embed |
| `title` | string | ❌ | Report title |

---

## 📁 Project Structure

```
tools_mcp_analysis/
├── mcp_server.py          # FastMCP server — 3 analysis tools over SSE
├── app.py                 # Streamlit web UI — chat interface
├── session_manager.py     # Session CRUD — persistent storage
├── llm_client.py          # LiteLLM wrapper — universal LLM + MCP loop
├── requirements.txt       # Python dependencies
├── Dockerfile.mcp         # MCP server container
├── Dockerfile.app         # Streamlit app container
├── docker-compose.yml     # Orchestration
├── .gitignore
├── README.md
└── sessions/              # Runtime session data (git-ignored)
```

---

## 📄 License

MIT License — see [LICENSE](LICENSE) for details.
