"""
Extract Mermaid blocks from markdown files and generate image URLs via mermaid.ink.

Usage:
    python mermaid_to_img.py                    # Process all .md files in docs/
    python mermaid_to_img.py path/to/file.md    # Process specific file
    python mermaid_to_img.py --html             # Generate HTML preview file
"""

import re
import base64
import urllib.parse
import sys
import os
from pathlib import Path


def mermaid_to_url(mermaid_code: str, theme: str = "default") -> str:
    """Convert mermaid code to mermaid.ink image URL using standard base64."""
    encoded = base64.b64encode(mermaid_code.encode("utf-8")).decode("utf-8")
    encoded = urllib.parse.quote(encoded, safe="")
    return f"https://mermaid.ink/img/{encoded}?theme={theme}"


def extract_mermaid_blocks(content: str) -> list[dict]:
    """Extract all mermaid code blocks from markdown content."""
    pattern = r"```mermaid\n(.*?)```"
    blocks = []
    for match in re.finditer(pattern, content, re.DOTALL):
        blocks.append({
            "code": match.group(1).strip(),
            "start": match.start(),
            "end": match.end(),
        })
    return blocks


def get_diagram_title(code: str) -> str:
    """Try to extract a title from the mermaid code (first comment or graph type)."""
    for line in code.split("\n"):
        line = line.strip()
        if line.startswith("%%") and len(line) > 2:
            return line[2:].strip()
    first_line = code.split("\n")[0].strip()
    if "graph" in first_line or "sequenceDiagram" in first_line or "classDiagram" in first_line:
        return first_line
    return "Diagram"


def process_file(filepath: str, generate_html: bool = False) -> list[dict]:
    """Process a single markdown file and return mermaid image info."""
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    blocks = extract_mermaid_blocks(content)
    if not blocks:
        return []

    results = []
    for i, block in enumerate(blocks, 1):
        title = get_diagram_title(block["code"])
        url = mermaid_to_url(block["code"])
        results.append({
            "file": filepath,
            "index": i,
            "title": title,
            "url": url,
            "code": block["code"],
        })

    return results


def generate_html_report(all_results: list[dict], output_path: str):
    """Generate an HTML file with all mermaid images for easy preview."""
    html = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Mermaid Diagrams - Beekid</title>
    <style>
        body { font-family: -apple-system, sans-serif; max-width: 1200px; margin: 0 auto; padding: 20px; background: #f5f5f5; }
        .diagram { background: white; border-radius: 8px; padding: 20px; margin: 20px 0; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
        .diagram h3 { color: #333; margin-top: 0; }
        .diagram .file { color: #666; font-size: 14px; }
        .diagram img { max-width: 100%; border: 1px solid #eee; border-radius: 4px; }
        .diagram .url { word-break: break-all; font-size: 12px; color: #888; margin-top: 10px; }
        .diagram .url a { color: #4A90D9; }
        .copy-btn { background: #4A90D9; color: white; border: none; padding: 6px 12px; border-radius: 4px; cursor: pointer; font-size: 12px; }
        .copy-btn:hover { background: #357ABD; }
        h1 { color: #333; }
    </style>
</head>
<body>
    <h1>Mermaid Diagrams - Beekid Project</h1>
    <p>Tổng hợp tất cả diagrams từ docs. Copy URL để paste vào Lark Docs.</p>
"""

    for r in all_results:
        html += f"""
    <div class="diagram">
        <p class="file">{r["file"]} — Diagram #{r["index"]}</p>
        <h3>{r["title"]}</h3>
        <img src="{r["url"]}" alt="{r["title"]}" loading="lazy">
        <div class="url">
            <button class="copy-btn" onclick="navigator.clipboard.writeText('{r["url"]}')">Copy URL</button>
            <a href="{r["url"]}" target="_blank">{r["url"][:80]}...</a>
        </div>
    </div>
"""

    html += """
</body>
</html>"""

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)


def main():
    generate_html = "--html" in sys.argv
    args = [a for a in sys.argv[1:] if not a.startswith("--")]

    docs_dir = Path(__file__).parent.parent / "docs"

    if args:
        files = [Path(f) for f in args]
    else:
        files = sorted(docs_dir.rglob("*.md"))

    if not files:
        print("No markdown files found in", docs_dir)
        return

    all_results = []
    for filepath in files:
        results = process_file(str(filepath), generate_html)
        if results:
            all_results.extend(results)
            print("\n" + str(filepath))
            for r in results:
                print("   Diagram #{}: {}".format(r['index'], r['title']))
                print("   URL: {}".format(r['url'][:100]))

    if not all_results:
        print("No mermaid blocks found.")
        return

    print("\n" + "=" * 60)
    print("Total: {} diagrams from {} files".format(len(all_results), len(files)))

    if generate_html:
        output_path = str(docs_dir.parent / "mermaid_preview.html")
        generate_html_report(all_results, output_path)
        print("\nHTML preview saved to:", output_path)
        print("   Open in browser to preview all diagrams and copy URLs.")

    # Also save URLs to a text file for easy copying
    urls_path = str(docs_dir.parent / "mermaid_urls.txt")
    with open(urls_path, "w", encoding="utf-8") as f:
        for r in all_results:
            f.write("# {} -- Diagram #{}: {}\n".format(r['file'], r['index'], r['title']))
            f.write("{}\n\n".format(r['url']))
    print("URLs saved to:", urls_path)


if __name__ == "__main__":
    main()
