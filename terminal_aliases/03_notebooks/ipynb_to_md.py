#!/usr/bin/env python3
"""
=============================================================================
Module: ipynb_to_md.py
Description: Production-Grade Jupyter Notebook (.ipynb) to Markdown (.md) Converter
=============================================================================
Features:
  1. Dynamic Language Detection: Extracts language from metadata (Java, Python, C++, etc.)
     with cell-magic override support (%%java, %%python, %%sql, %%sh, etc.).
  2. Custom Heading Formatting: Guarantees clean newline separation before Second-Level
     headings ('## ') and standardizes markdown structural flow.
  3. Comprehensive Output Handling: Captures standard streams (stdout/stderr), execution
     results, display data, and sanitized error tracebacks (stripping ANSI color escapes).
  4. Robust CLI & Batch Processing: Supports individual files, recursive directories,
     custom output targets, and configurable output styling.
=============================================================================
"""

import os
import sys
import re
import json
import argparse
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple


# Regex pattern to strip ANSI terminal escape color codes
ANSI_ESCAPE_PATTERN = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")

# Common cell magic language mappings
MAGIC_LANG_MAP = {
    "%%python": "python",
    "%%python3": "python",
    "%%py": "python",
    "%%java": "java",
    "%%js": "javascript",
    "%%javascript": "javascript",
    "%%html": "html",
    "%%css": "css",
    "%%bash": "bash",
    "%%sh": "bash",
    "%%sql": "sql",
    "%%r": "r",
    "%%c": "c",
    "%%cpp": "cpp",
    "%%rust": "rust",
    "%%go": "go",
    "%%scala": "scala",
    "%%kotlin": "kotlin",
}


def strip_ansi(text: str) -> str:
    """Removes ANSI terminal escape color and control sequences from output text."""
    return ANSI_ESCAPE_PATTERN.sub("", text)


def normalize_source(source: Any) -> str:
    """
    Normalizes notebook cell source which can be a single string or a list of strings.
    """
    if isinstance(source, list):
        return "".join(source)
    elif isinstance(source, str):
        return source
    return ""


def detect_notebook_language(metadata: Dict[str, Any]) -> str:
    """
    Detects the primary programming language from notebook metadata.
    Checks 'language_info', 'kernelspec', or defaults to 'python'.
    """
    # Check language_info first
    lang_info = metadata.get("language_info", {})
    if isinstance(lang_info, dict) and "name" in lang_info:
        lang = lang_info["name"].strip().lower()
        if lang:
            return lang

    # Check kernelspec
    kernelspec = metadata.get("kernelspec", {})
    if isinstance(kernelspec, dict):
        lang = kernelspec.get("language", "")
        if lang:
            return lang.strip().lower()
        name = kernelspec.get("name", "").lower()
        if "java" in name:
            return "java"
        if "python" in name or "py" in name:
            return "python"
        if "julia" in name:
            return "julia"
        if "r" in name:
            return "r"

    return "python"


def detect_cell_language(code_content: str, default_lang: str) -> Tuple[str, str]:
    """
    Inspects cell source code for magic commands (e.g. %%java, %%bash) and strips
    or overrides the language tag accordingly.
    
    Returns:
        (language_name, cleaned_code_content)
    """
    lines = code_content.splitlines(keepends=True)
    if not lines:
        return default_lang, code_content

    first_line = lines[0].strip()
    for magic, lang in MAGIC_LANG_MAP.items():
        if first_line.startswith(magic):
            # Strip the magic line from code block
            rest_of_code = "".join(lines[1:])
            return lang, rest_of_code

    # Heuristic fallback if language is ambiguous
    if default_lang in ("text", "", None):
        if "public class" in code_content or "System.out.print" in code_content:
            return "java", code_content
        if "def " in code_content or "import numpy" in code_content:
            return "python", code_content

    return default_lang, code_content


def format_markdown_cell(content: str, ensure_h2_spacing: bool = True) -> str:
    """
    Formats a markdown cell with custom transformation rules.
    Rule 1: Ensure exactly one empty line before Second-Level headings ('## ').
    """
    if not ensure_h2_spacing:
        return content.strip()

    lines = content.split("\n")
    formatted_lines: List[str] = []

    for line in lines:
        is_h2 = line.strip().startswith("## ") or line.strip() == "##"
        if is_h2:
            # If formatted_lines already has content and the last line is not empty, prepend blank line
            if formatted_lines and formatted_lines[-1].strip() != "":
                formatted_lines.append("")
        formatted_lines.append(line)

    return "\n".join(formatted_lines).strip()


def extract_cell_outputs(outputs: List[Dict[str, Any]], strip_colors: bool = True) -> str:
    """
    Extracts and aggregates all outputs from a code cell into a unified textual representation.
    Handles stream (stdout/stderr), execute_result, display_data, and errors.
    """
    collected_outputs: List[str] = []

    for out in outputs:
        output_type = out.get("output_type", "")

        if output_type == "stream":
            text = normalize_source(out.get("text", ""))
            if text:
                collected_outputs.append(text)

        elif output_type in ("execute_result", "display_data"):
            data = out.get("data", {})
            if isinstance(data, dict):
                # Priority 1: text/plain
                if "text/plain" in data:
                    collected_outputs.append(normalize_source(data["text/plain"]))
                # Priority 2: text/markdown
                elif "text/markdown" in data:
                    collected_outputs.append(normalize_source(data["text/markdown"]))
                # Priority 3: HTML / image notifications
                elif "image/png" in data:
                    collected_outputs.append("[Output: Embedded PNG Image]")
                elif "image/jpeg" in data:
                    collected_outputs.append("[Output: Embedded JPEG Image]")

        elif output_type == "error":
            ename = out.get("ename", "Error")
            evalue = out.get("evalue", "")
            traceback = out.get("traceback", [])
            if traceback:
                tb_text = "\n".join(traceback)
                collected_outputs.append(f"{ename}: {evalue}\n{tb_text}")
            else:
                collected_outputs.append(f"{ename}: {evalue}")

    aggregated = "\n".join(collected_outputs).strip()
    if strip_colors and aggregated:
        aggregated = strip_ansi(aggregated)
    return aggregated


def convert_ipynb_to_markdown(
    notebook_path: Path,
    override_lang: Optional[str] = None,
    ensure_h2_spacing: bool = True,
    include_outputs: bool = True,
    output_label: str = "**Output:**"
) -> str:
    """
    Converts a Jupyter Notebook (.ipynb) file into a customized Markdown string.
    """
    with open(notebook_path, "r", encoding="utf-8") as f:
        nb_data = json.load(f)

    metadata = nb_data.get("metadata", {})
    default_lang = override_lang or detect_notebook_language(metadata)

    cells = nb_data.get("cells", [])
    markdown_sections: List[str] = []

    for cell in cells:
        cell_type = cell.get("cell_type", "")
        source_raw = normalize_source(cell.get("source", ""))

        if not source_raw.strip():
            continue

        if cell_type == "markdown":
            formatted_md = format_markdown_cell(source_raw, ensure_h2_spacing=ensure_h2_spacing)
            if formatted_md:
                markdown_sections.append(formatted_md)

        elif cell_type == "code":
            cell_lang, cleaned_code = detect_cell_language(source_raw, default_lang)
            cleaned_code_str = cleaned_code.strip("\n")

            # Format the code block
            code_block = f"```{cell_lang}\n{cleaned_code_str}\n```"

            # Check for outputs
            outputs = cell.get("outputs", [])
            output_str = extract_cell_outputs(outputs) if (include_outputs and outputs) else ""

            if output_str:
                code_and_output = f"{code_block}\n\n{output_label}\n```text\n{output_str}\n```"
                markdown_sections.append(code_and_output)
            else:
                markdown_sections.append(code_block)

        elif cell_type == "raw":
            markdown_sections.append(f"```text\n{source_raw.strip()}\n```")

    # Combine sections with clean double newline spacing
    final_markdown = "\n\n".join(markdown_sections)

    # Global pass to guarantee second-level heading spacing throughout document
    if ensure_h2_spacing:
        # Replace occurrences where '## ' is preceded immediately by non-empty line
        final_markdown = re.sub(r"([^\n])\n(##\s+)", r"\1\n\n\2", final_markdown)

    return final_markdown + "\n"


def process_path(
    input_path: Path,
    output_path: Optional[Path] = None,
    override_lang: Optional[str] = None,
    ensure_h2_spacing: bool = True,
    include_outputs: bool = True
) -> List[Tuple[Path, Path]]:
    """
    Processes single file or directory recursively.
    Returns list of (source_path, target_md_path).
    """
    conversions: List[Tuple[Path, Path]] = []

    if input_path.is_file():
        if input_path.suffix.lower() != ".ipynb":
            raise ValueError(f"Input file '{input_path}' is not a .ipynb file.")
        
        target_md = output_path if output_path else input_path.with_suffix(".md")
        conversions.append((input_path, target_md))

    elif input_path.is_dir():
        ipynb_files = sorted(list(input_path.rglob("*.ipynb")))
        if not ipynb_files:
            print(f"No .ipynb files found in directory: {input_path}")
            return []

        for ipynb_file in ipynb_files:
            if output_path:
                rel_path = ipynb_file.relative_to(input_path)
                target_md = (output_path / rel_path).with_suffix(".md")
            else:
                target_md = ipynb_file.with_suffix(".md")
            conversions.append((ipynb_file, target_md))
    else:
        raise FileNotFoundError(f"Input path does not exist: {input_path}")

    # Execute conversions
    for src, dst in conversions:
        dst.parent.mkdir(parents=True, exist_ok=True)
        md_content = convert_ipynb_to_markdown(
            notebook_path=src,
            override_lang=override_lang,
            ensure_h2_spacing=ensure_h2_spacing,
            include_outputs=include_outputs
        )
        with open(dst, "w", encoding="utf-8") as f:
            f.write(md_content)
        print(f"✅ Converted: {src} -> {dst}")

    return conversions


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Convert Jupyter Notebooks (.ipynb) to Markdown (.md) with custom rules."
    )
    parser.add_argument(
        "input",
        type=str,
        help="Path to .ipynb file or directory containing .ipynb notebooks."
    )
    parser.add_argument(
        "-o", "--output",
        type=str,
        default=None,
        help="Optional destination path for the generated .md file or output directory."
    )
    parser.add_argument(
        "--lang",
        type=str,
        default=None,
        help="Force a specific code block language (e.g. 'java', 'python', 'cpp'). Default: Auto-detected."
    )
    parser.add_argument(
        "--no-h2-spacing",
        action="store_true",
        help="Disable enforced blank line spacing before second-level headings ('## ')."
    )
    parser.add_argument(
        "--no-output",
        action="store_true",
        help="Exclude code cell execution outputs from the generated markdown."
    )
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    input_p = Path(args.input).resolve()
    output_p = Path(args.output).resolve() if args.output else None

    try:
        results = process_path(
            input_path=input_p,
            output_path=output_p,
            override_lang=args.lang,
            ensure_h2_spacing=not args.no_h2_spacing,
            include_outputs=not args.no_output
        )
        print(f"\n🎉 Successfully processed {len(results)} file(s).")
    except Exception as e:
        print(f"❌ Error during conversion: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
