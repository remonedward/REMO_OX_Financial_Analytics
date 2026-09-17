"""
REMO_OX Financial Analytics - MCP Server
FastMCP server exposing financial analysis tools over SSE transport.

Tools:
  1. analyze_data  - Statistical analysis of Excel data
  2. generate_chart - Chart generation (bar, line, pie, scatter, hist)
  3. export_pdf_report - Professional PDF report generation
"""

import json
import traceback
from datetime import datetime
from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # Non-interactive backend for server use
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import pandas as pd
from fastmcp import FastMCP
from fpdf import FPDF
import arabic_reshaper
from bidi.algorithm import get_display

# ---------------------------------------------------------------------------
# Arabic text handling helpers
# ---------------------------------------------------------------------------
FONTS_DIR = Path(__file__).parent / "fonts"
AMIRI_REGULAR = FONTS_DIR / "Amiri-Regular.ttf"
AMIRI_BOLD = FONTS_DIR / "Amiri-Bold.ttf"

if AMIRI_REGULAR.exists():
    try:
        fm.fontManager.addfont(str(AMIRI_REGULAR))
    except Exception:
        pass


def _has_arabic(text: str) -> bool:
    """Check if a string contains Arabic Unicode characters."""
    if not text or not isinstance(text, str):
        return False
    return any(
        '\u0600' <= ch <= '\u06FF' or '\u0750' <= ch <= '\u077F' or '\u08A0' <= ch <= '\u08FF'
        for ch in text
    )


def _bidi_arabic(text: str) -> str:
    """Reshape and reorder Arabic text for correct RTL display in PDF & charts."""
    if not text or not isinstance(text, str):
        return ""
    if _has_arabic(text):
        try:
            return get_display(arabic_reshaper.reshape(text))
        except Exception:
            return text
    return text

# ---------------------------------------------------------------------------
# Initialize FastMCP server
# ---------------------------------------------------------------------------
mcp = FastMCP(
    name="REMO_OX Financial Analytics",
    instructions=(
        "Financial data analysis tools: analyze Excel data, "
        "generate charts, and export PDF reports."
    ),
)


# ---------------------------------------------------------------------------
# Tool 1: analyze_data
# ---------------------------------------------------------------------------
@mcp.tool()
def analyze_data(
    file_path: str,
    query_type: str,
    column: str = "",
    n_rows: int = 5,
) -> str:
    """
    Analyze financial data from an Excel file.

    Args:
        file_path: Absolute path to the .xlsx file to analyze.
        query_type: Type of analysis to perform. One of:
            - "summary"      : Complete overview (shape, dtypes, basic stats, missing values)
            - "columns"      : List all column names with data types
            - "head"         : First N rows of data
            - "tail"         : Last N rows of data
            - "describe"     : Statistical summary (all columns or a single column)
            - "shape"        : Number of rows and columns
            - "dtypes"       : Data types of each column
            - "value_counts" : Frequency counts for a specific column (requires 'column')
            - "unique"       : Unique values in a specific column (requires 'column')
            - "missing"      : Count and percentage of missing values per column
            - "corr"         : Correlation matrix for numeric columns
        column: Target column name. Required for value_counts and unique.
                Optional for describe (filters to one column).
        n_rows: Number of rows to return for head/tail (default 5).

    Returns:
        JSON string with the analysis results or an error message.
    """
    try:
        path = Path(file_path)
        if not path.exists():
            return _error(f"File not found: {file_path}")

        df = pd.read_excel(path, engine="openpyxl")
        all_columns = list(df.columns)

        # --- Column validation helper ---
        def _check_column(col_name: str) -> str | None:
            if not col_name:
                return _error(
                    f"Parameter 'column' is required for '{query_type}'. "
                    f"Available columns: {all_columns}"
                )
            if col_name not in df.columns:
                return _error(
                    f"Column '{col_name}' not found. "
                    f"Available columns: {all_columns}"
                )
            return None

        # --- Dispatch by query_type ---
        if query_type == "summary":
            result = {
                "shape": {"rows": len(df), "columns": len(df.columns)},
                "columns": {str(c): str(df[c].dtype) for c in df.columns},
                "numeric_summary": json.loads(
                    df.describe(include="all").fillna("N/A").to_json()
                ),
                "missing_values": df.isnull().sum().to_dict(),
            }

        elif query_type == "columns":
            result = {
                "columns": [
                    {"name": str(c), "dtype": str(df[c].dtype)}
                    for c in df.columns
                ]
            }

        elif query_type == "head":
            n = min(max(1, n_rows), len(df))
            result = {
                "data": json.loads(
                    df.head(n).to_json(orient="records", date_format="iso")
                ),
                "showing": f"First {n} of {len(df)} rows",
            }

        elif query_type == "tail":
            n = min(max(1, n_rows), len(df))
            result = {
                "data": json.loads(
                    df.tail(n).to_json(orient="records", date_format="iso")
                ),
                "showing": f"Last {n} of {len(df)} rows",
            }

        elif query_type == "describe":
            if column:
                err = _check_column(column)
                if err:
                    return err
                result = {"describe": json.loads(df[column].describe().to_json())}
            else:
                result = {
                    "describe": json.loads(
                        df.describe(include="all").fillna("N/A").to_json()
                    )
                }

        elif query_type == "shape":
            result = {"rows": len(df), "columns": len(df.columns)}

        elif query_type == "dtypes":
            result = {str(c): str(df[c].dtype) for c in df.columns}

        elif query_type == "value_counts":
            err = _check_column(column)
            if err:
                return err
            vc = df[column].value_counts().head(30)
            result = {
                "column": column,
                "value_counts": vc.to_dict(),
                "total_unique": int(df[column].nunique()),
            }

        elif query_type == "unique":
            err = _check_column(column)
            if err:
                return err
            unique_vals = df[column].dropna().unique().tolist()
            result = {
                "column": column,
                "unique_count": len(unique_vals),
                "unique_values": unique_vals[:50],
                "truncated": len(unique_vals) > 50,
            }

        elif query_type == "missing":
            missing = df.isnull().sum()
            result = {
                "missing_counts": missing.to_dict(),
                "total_rows": len(df),
                "missing_percentages": (missing / len(df) * 100).round(2).to_dict(),
            }

        elif query_type == "corr":
            numeric_df = df.select_dtypes(include="number")
            if numeric_df.empty:
                return _error("No numeric columns found for correlation analysis.")
            result = {
                "correlation": json.loads(numeric_df.corr().round(4).to_json())
            }

        else:
            valid = [
                "summary", "columns", "head", "tail", "describe",
                "shape", "dtypes", "value_counts", "unique", "missing", "corr",
            ]
            return _error(
                f"Unknown query_type: '{query_type}'. Valid types: {valid}"
            )

        return json.dumps(result, ensure_ascii=False, default=str)

    except Exception as e:
        return _error(str(e), traceback.format_exc())


# ---------------------------------------------------------------------------
# Tool 2: generate_chart
# ---------------------------------------------------------------------------
@mcp.tool()
def generate_chart(
    file_path: str,
    x_column: str,
    y_column: str = "",
    chart_type: str = "bar",
    title: str = "",
    output_path: str = "",
) -> str:
    """
    Generate a chart from Excel data and save it as a PNG image.

    Args:
        file_path: Absolute path to the .xlsx file.
        x_column: Column name for X-axis (or labels for pie chart).
        y_column: Column name for Y-axis (or values for pie chart).
                  Not required for histogram.
        chart_type: Chart type: "bar", "line", "pie", "scatter", or "hist".
        title: Optional chart title. Auto-generated if empty.
        output_path: Path where the PNG file will be saved. Required.

    Returns:
        JSON string with the output path on success, or error details.
    """
    try:
        path = Path(file_path)
        if not path.exists():
            return _error(f"File not found: {file_path}")
        if not output_path:
            return _error("output_path is required.")

        df = pd.read_excel(path, engine="openpyxl")

        # Validate x_column
        if x_column not in df.columns:
            return _error(
                f"X column '{x_column}' not found. "
                f"Available: {list(df.columns)}"
            )
        # Validate y_column (not needed for hist)
        if chart_type != "hist":
            if not y_column:
                return _error(
                    f"y_column is required for '{chart_type}' chart."
                )
            if y_column not in df.columns:
                return _error(
                    f"Y column '{y_column}' not found. "
                    f"Available: {list(df.columns)}"
                )

        valid_types = ["bar", "line", "pie", "scatter", "hist"]
        if chart_type not in valid_types:
            return _error(
                f"Invalid chart_type '{chart_type}'. Valid: {valid_types}"
            )

        # --- Generate chart ---
        fig, ax = plt.subplots(figsize=(10, 6))

        # Check if Arabic font is available
        font_prop = fm.FontProperties(fname=str(AMIRI_REGULAR)) if AMIRI_REGULAR.exists() else None

        clean_x = _bidi_arabic(x_column)
        clean_y = _bidi_arabic(y_column) if y_column else ""
        auto_title = _bidi_arabic(title or (f"{y_column} by {x_column}" if y_column else f"Distribution of {x_column}"))

        if chart_type == "bar":
            data = df.dropna(subset=[x_column, y_column])
            x_vals = [_bidi_arabic(str(v)) for v in data[x_column]]
            ax.bar(
                x_vals,
                data[y_column],
                color="#2196F3",
                edgecolor="white",
            )
            ax.set_xlabel(clean_x, fontproperties=font_prop, fontsize=11)
            ax.set_ylabel(clean_y, fontproperties=font_prop, fontsize=11)
            plt.xticks(rotation=45, ha="right", fontproperties=font_prop)
            ax.grid(axis="y", alpha=0.3)

        elif chart_type == "line":
            data = df.dropna(subset=[x_column, y_column])
            ax.plot(
                data[x_column], data[y_column],
                marker="o", color="#4CAF50", linewidth=2, markersize=5,
            )
            ax.set_xlabel(clean_x, fontproperties=font_prop, fontsize=11)
            ax.set_ylabel(clean_y, fontproperties=font_prop, fontsize=11)
            ax.grid(True, alpha=0.3)

        elif chart_type == "pie":
            data = df.dropna(subset=[x_column, y_column])
            pie_data = data.groupby(x_column)[y_column].sum()
            labels = [_bidi_arabic(str(idx)) for idx in pie_data.index]
            wedges, texts, autotexts = ax.pie(
                pie_data.values,
                labels=labels,
                autopct="%1.1f%%",
                startangle=90,
                colors=plt.cm.Set3.colors,
            )
            if font_prop:
                for t in texts:
                    t.set_fontproperties(font_prop)
            ax.axis("equal")

        elif chart_type == "scatter":
            data = df.dropna(subset=[x_column, y_column])
            ax.scatter(
                data[x_column], data[y_column],
                color="#FF9800", alpha=0.7, edgecolors="white", s=60,
            )
            ax.set_xlabel(clean_x, fontproperties=font_prop, fontsize=11)
            ax.set_ylabel(clean_y, fontproperties=font_prop, fontsize=11)
            ax.grid(True, alpha=0.3)

        elif chart_type == "hist":
            data = df[x_column].dropna()
            ax.hist(
                data, bins=min(20, max(5, len(data) // 5)),
                color="#9C27B0", edgecolor="white", alpha=0.85,
            )
            ax.set_xlabel(clean_x, fontproperties=font_prop, fontsize=11)
            ax.set_ylabel("Frequency", fontsize=11)
            ax.grid(axis="y", alpha=0.3)

        ax.set_title(auto_title, fontproperties=font_prop, fontsize=14, fontweight="bold", pad=15)
        fig.tight_layout()

        # Save output
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(output_path, dpi=150, bbox_inches="tight", facecolor="white")
        plt.close(fig)

        return json.dumps({
            "success": True,
            "output_path": output_path,
            "chart_type": chart_type,
            "title": auto_title,
        })

    except Exception as e:
        return _error(str(e), traceback.format_exc())


# ---------------------------------------------------------------------------
# Tool 3: export_pdf_report
# ---------------------------------------------------------------------------
@mcp.tool()
def export_pdf_report(
    summary_text: str,
    output_path: str,
    chart_path: str = "",
    title: str = "REMO_OX Financial Report",
) -> str:
    """
    Generate a professional PDF report with text summary and optional chart.

    Args:
        summary_text: The main text content / analysis summary for the report body.
        output_path: Path where the PDF file will be saved. Required.
        chart_path: Optional path to a chart image (PNG) to embed in the report.
        title: Report title (default: "REMO_OX Financial Report").

    Returns:
        JSON string with the output path on success, or error details.
    """
    try:
        if not output_path:
            return _error("output_path is required.")
        if not summary_text.strip():
            return _error("summary_text cannot be empty.")

        pdf = FPDF()
        pdf.set_auto_page_break(auto=True, margin=20)

        # Setup font: Prefer Amiri Arabic TrueType font if available
        font_family = "Helvetica"
        if AMIRI_REGULAR.exists() and AMIRI_BOLD.exists():
            try:
                pdf.add_font("Amiri", "", str(AMIRI_REGULAR))
                pdf.add_font("Amiri", "B", str(AMIRI_BOLD))
                font_family = "Amiri"
            except Exception:
                pass

        pdf.add_page()

        # --- Header banner ---
        pdf.set_fill_color(33, 150, 243)  # Material Blue
        pdf.rect(0, 0, 210, 35, "F")
        pdf.set_text_color(255, 255, 255)
        pdf.set_font(font_family, "B", 20)
        pdf.set_y(8)
        pdf.cell(
            0, 12, "REMO_OX Financial Analytics",
            align="C", new_x="LMARGIN", new_y="NEXT",
        )
        pdf.set_font(font_family, "", 10)
        pdf.cell(
            0, 8,
            f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            align="C", new_x="LMARGIN", new_y="NEXT",
        )

        # Reset to black text
        pdf.set_text_color(0, 0, 0)
        pdf.ln(15)

        # --- Report title ---
        pdf.set_font(font_family, "B", 16)
        is_title_arabic = _has_arabic(title)
        title_text = _bidi_arabic(title) if is_title_arabic else title
        title_align = "R" if is_title_arabic else "L"
        pdf.cell(0, 10, title_text, align=title_align, new_x="LMARGIN", new_y="NEXT")
        pdf.ln(3)

        # Divider
        pdf.set_draw_color(200, 200, 200)
        pdf.line(10, pdf.get_y(), 200, pdf.get_y())
        pdf.ln(8)

        # --- Summary text body ---
        pdf.set_font(font_family, "", 12 if font_family == "Amiri" else 11)
        # Handle multi-line text properly
        for paragraph in summary_text.split("\n\n"):
            paragraph = paragraph.strip()
            if paragraph:
                is_p_arabic = _has_arabic(paragraph)
                p_text = _bidi_arabic(paragraph) if is_p_arabic else paragraph
                p_align = "R" if is_p_arabic else "L"
                pdf.multi_cell(0, 8, p_text, align=p_align)
                pdf.ln(4)

        # --- Embed chart if provided ---
        if chart_path:
            chart_file = Path(chart_path)
            if chart_file.exists():
                pdf.ln(5)
                pdf.set_font(font_family, "B", 13)
                pdf.cell(0, 10, "Chart / الرسم البياني", new_x="LMARGIN", new_y="NEXT")
                pdf.ln(3)
                # Scale to fit page width (max ~180mm with margins)
                pdf.image(str(chart_file), x=15, w=180)
            else:
                pdf.ln(5)
                pdf.set_font(font_family, "I", 10)
                pdf.set_text_color(180, 0, 0)
                pdf.cell(
                    0, 8,
                    f"[Chart not found: {chart_path}]",
                    new_x="LMARGIN", new_y="NEXT",
                )
                pdf.set_text_color(0, 0, 0)

        # --- Footer ---
        pdf.set_y(-25)
        pdf.set_font(font_family, "", 9)
        pdf.set_text_color(128, 128, 128)
        pdf.cell(
            0, 10,
            "REMO_OX Financial Analytics  |  Confidential  |  تقرير مالي سري",
            align="C",
        )

        # Save PDF
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        pdf.output(output_path)

        return json.dumps({"success": True, "output_path": output_path})

    except Exception as e:
        return _error(str(e), traceback.format_exc())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _error(message: str, tb: str = "") -> str:
    """Return a JSON error string."""
    result = {"error": message}
    if tb:
        result["traceback"] = tb
    return json.dumps(result, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    mcp.run(transport="sse", host="0.0.0.0", port=8000)
