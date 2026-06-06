from html import escape
from pathlib import Path
import re


ARTICLE_DIR = Path(__file__).resolve().parent
source = (ARTICLE_DIR / "medium-draft.md").read_text(encoding="utf-8")


def inline(text):
    rendered = escape(text)
    rendered = re.sub(
        r"\[([^\]]+)\]\((https?://[^)]+)\)",
        r'<a href="\2" target="_blank" rel="noreferrer">\1</a>',
        rendered,
    )
    rendered = re.sub(r"`([^`]+)`", r"<code>\1</code>", rendered)
    rendered = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", rendered)
    return rendered


def render_table(lines):
    rows = [
        [cell.strip() for cell in line.strip().strip("|").split("|")]
        for line in lines
    ]
    html = ["<table>", "<thead><tr>"]
    html.extend(f"<th>{inline(cell)}</th>" for cell in rows[0])
    html.append("</tr></thead><tbody>")
    for row in rows[2:]:
        html.append("<tr>")
        html.extend(f"<td>{inline(cell)}</td>" for cell in row)
        html.append("</tr>")
    html.append("</tbody></table>")
    return "\n".join(html)


def render(markdown):
    lines = markdown.splitlines()
    output = []
    index = 0
    code = None
    code_language = "text"
    list_type = None

    def close_list():
        nonlocal list_type
        if list_type:
            output.append(f"</{list_type}>")
            list_type = None

    while index < len(lines):
        line = lines[index]

        if line.startswith("```"):
            close_list()
            if code is None:
                code = []
                code_language = line[3:].strip() or "text"
            else:
                output.append(
                    f'<pre data-lang="{escape(code_language)}"><code>'
                    f'{escape(chr(10).join(code))}</code></pre>'
                )
                code = None
            index += 1
            continue

        if code is not None:
            code.append(line)
            index += 1
            continue

        if not line.strip():
            close_list()
            index += 1
            continue

        if (
            line.startswith("| ")
            and index + 1 < len(lines)
            and lines[index + 1].startswith("| ---")
        ):
            close_list()
            table_lines = [line, lines[index + 1]]
            index += 2
            while index < len(lines) and lines[index].startswith("| "):
                table_lines.append(lines[index])
                index += 1
            output.append(render_table(table_lines))
            continue

        image = re.fullmatch(r"!\[(.*?)\]\((.*?)\)", line)
        if image:
            close_list()
            alt, path = image.groups()
            output.append(
                f'<figure><img src="{escape(path)}" alt="{escape(alt)}">'
                f"<figcaption>{escape(alt)}</figcaption></figure>"
            )
            index += 1
            continue

        if line.startswith("# "):
            close_list()
            output.append(f"<h1>{inline(line[2:])}</h1>")
            index += 1
            continue

        if line.startswith("## "):
            close_list()
            output.append(f"<h2>{inline(line[3:])}</h2>")
            index += 1
            continue

        if line.startswith("- "):
            if list_type != "ul":
                close_list()
                output.append("<ul>")
                list_type = "ul"
            output.append(f"<li>{inline(line[2:])}</li>")
            index += 1
            continue

        numbered = re.match(r"\d+\. (.*)", line)
        if numbered:
            if list_type != "ol":
                close_list()
                output.append("<ol>")
                list_type = "ol"
            output.append(f"<li>{inline(numbered.group(1))}</li>")
            index += 1
            continue

        close_list()
        output.append(f"<p>{inline(line)}</p>")
        index += 1

    close_list()
    return "\n".join(output)


article_html = render(source)
markdown_json = (
    source.replace("\\", "\\\\")
    .replace("`", "\\`")
    .replace("${", "\\${")
)

page = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Kestra Retry Storm Medium Draft</title>
  <style>
    :root {{
      color-scheme: light;
      --ink: #17191f;
      --muted: #5d6573;
      --line: #dfe3ea;
      --surface: #ffffff;
      --code: #f6f7f9;
      --accent: #6d36d8;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: #f1f3f6;
      color: var(--ink);
      font-family: Arial, Helvetica, sans-serif;
      line-height: 1.65;
    }}
    .topbar {{
      position: sticky;
      top: 0;
      z-index: 5;
      display: flex;
      gap: 16px;
      align-items: center;
      justify-content: space-between;
      padding: 14px 24px;
      background: rgba(255, 255, 255, 0.96);
      border-bottom: 1px solid var(--line);
      backdrop-filter: blur(10px);
    }}
    .topbar strong {{ font-size: 15px; }}
    .actions {{ display: flex; gap: 10px; flex-wrap: wrap; }}
    button, a.button {{
      border: 1px solid #c9ced8;
      background: #fff;
      color: var(--ink);
      border-radius: 7px;
      padding: 9px 13px;
      font: 600 14px Arial, Helvetica, sans-serif;
      cursor: pointer;
      text-decoration: none;
    }}
    button.primary {{
      background: var(--accent);
      border-color: var(--accent);
      color: white;
    }}
    main {{
      max-width: 900px;
      margin: 32px auto 80px;
      padding: 58px 68px;
      background: var(--surface);
      border: 1px solid var(--line);
      box-shadow: 0 18px 54px rgba(30, 34, 45, 0.08);
    }}
    h1 {{
      margin: 0 0 28px;
      font-family: Georgia, "Times New Roman", serif;
      font-size: 44px;
      line-height: 1.14;
      letter-spacing: 0;
    }}
    h2 {{
      margin: 44px 0 14px;
      font-size: 27px;
      line-height: 1.28;
      letter-spacing: 0;
    }}
    h1 + h2 {{
      margin-top: 0;
      color: var(--muted);
      font-size: 22px;
      font-weight: 500;
    }}
    p {{ margin: 0 0 20px; font-size: 18px; }}
    a {{ color: #5430b5; }}
    code {{
      font-family: Menlo, Monaco, Consolas, "Liberation Mono", monospace;
      font-size: 0.91em;
      background: #edf0f5;
      border-radius: 4px;
      padding: 1px 4px;
    }}
    pre {{
      margin: 22px 0 28px;
      padding: 20px 22px;
      background: var(--code);
      border: 1px solid var(--line);
      border-radius: 7px;
      overflow-x: auto;
      line-height: 1.5;
    }}
    pre code {{ background: transparent; padding: 0; font-size: 14px; }}
    figure {{ margin: 32px 0; }}
    figure img {{
      width: 100%;
      height: auto;
      border: 1px solid var(--line);
      display: block;
    }}
    figcaption {{
      color: var(--muted);
      font-size: 14px;
      margin-top: 8px;
      text-align: center;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      margin: 24px 0 30px;
      font-size: 14px;
    }}
    th, td {{
      border: 1px solid var(--line);
      padding: 10px 11px;
      vertical-align: top;
      text-align: left;
    }}
    th {{ background: #f4f5f8; }}
    ul, ol {{ margin: 0 0 24px 24px; padding: 0; font-size: 18px; }}
    li {{ margin: 7px 0; }}
    .toast {{
      position: fixed;
      right: 20px;
      bottom: 20px;
      background: #1d2027;
      color: white;
      padding: 10px 13px;
      border-radius: 6px;
      opacity: 0;
      transform: translateY(8px);
      transition: opacity .18s ease, transform .18s ease;
    }}
    .toast.show {{ opacity: 1; transform: translateY(0); }}
    @media (max-width: 760px) {{
      .topbar {{ align-items: flex-start; flex-direction: column; }}
      main {{ margin: 0; padding: 30px 20px 56px; border: 0; }}
      h1 {{ font-size: 34px; }}
      table {{ display: block; overflow-x: auto; }}
    }}
  </style>
</head>
<body>
  <div class="topbar">
    <strong>Kestra Engineering Medium draft</strong>
    <div class="actions">
      <button class="primary" id="copyRendered">Copy rendered article</button>
      <button id="copyMarkdown">Copy markdown</button>
      <a class="button" href="architecture.png" download>Architecture PNG</a>
      <a class="button" href="results.png" download>Results PNG</a>
    </div>
  </div>
  <main id="article" contenteditable="true">
{article_html}
  </main>
  <div class="toast" id="toast">Copied</div>
  <script>
    const markdown = `{markdown_json}`;
    const article = document.getElementById("article");
    const toast = document.getElementById("toast");

    function showToast(message) {{
      toast.textContent = message;
      toast.classList.add("show");
      setTimeout(() => toast.classList.remove("show"), 1600);
    }}

    async function copyRendered() {{
      const html = article.innerHTML;
      const text = article.innerText;
      try {{
        await navigator.clipboard.write([
          new ClipboardItem({{
            "text/html": new Blob([html], {{ type: "text/html" }}),
            "text/plain": new Blob([text], {{ type: "text/plain" }})
          }})
        ]);
        showToast("Rendered article copied");
      }} catch (error) {{
        const range = document.createRange();
        range.selectNodeContents(article);
        const selection = window.getSelection();
        selection.removeAllRanges();
        selection.addRange(range);
        document.execCommand("copy");
        selection.removeAllRanges();
        showToast("Rendered article copied");
      }}
    }}

    async function copyMarkdown() {{
      await navigator.clipboard.writeText(markdown);
      showToast("Markdown copied");
    }}

    document.getElementById("copyRendered").addEventListener("click", copyRendered);
    document.getElementById("copyMarkdown").addEventListener("click", copyMarkdown);
  </script>
</body>
</html>
"""

(ARTICLE_DIR / "index.html").write_text(page, encoding="utf-8")
