from html import escape
from math import ceil
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


def slugify(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


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
    first_h2 = True

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
            heading = line[3:]
            if first_h2:
                output.append(f'<h2 class="dek">{inline(heading)}</h2>')
                first_h2 = False
            else:
                output.append(
                    f'<h2 id="{slugify(heading)}">{inline(heading)}</h2>'
                )
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
section_headings = [
    line[3:]
    for line in source.splitlines()
    if line.startswith("## ")
][1:]
section_nav = "\n".join(
    (
        f'<a href="#{slugify(heading)}" '
        f'data-section="{slugify(heading)}">{escape(heading)}</a>'
    )
    for heading in section_headings
)
word_count = len(re.findall(r"\b[\w'-]+\b", source))
reading_minutes = max(1, ceil(word_count / 220))
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
      --ink: #12131a;
      --muted: #626776;
      --quiet: #8b90a0;
      --line: #e2e4e9;
      --line-strong: #cfd2da;
      --surface: #ffffff;
      --surface-soft: #f6f7f9;
      --code: #171922;
      --code-ink: #f4f2ff;
      --accent: #6e3bd0;
      --accent-soft: #f1ebff;
      --green: #18845b;
      --orange: #d96728;
    }}
    * {{ box-sizing: border-box; }}
    html {{ scroll-behavior: smooth; }}
    body {{
      margin: 0;
      background: var(--surface);
      color: var(--ink);
      font-family: Inter, ui-sans-serif, -apple-system, BlinkMacSystemFont,
        "Segoe UI", sans-serif;
      line-height: 1.62;
      letter-spacing: 0;
    }}
    .progress {{
      position: fixed;
      z-index: 20;
      top: 0;
      left: 0;
      width: 0;
      height: 3px;
      background: var(--accent);
    }}
    .workspace-bar {{
      position: sticky;
      top: 0;
      z-index: 15;
      display: flex;
      min-height: 70px;
      gap: 24px;
      align-items: center;
      justify-content: space-between;
      padding: 12px max(24px, calc((100vw - 1240px) / 2));
      background: rgba(255, 255, 255, 0.97);
      border-bottom: 1px solid var(--line);
      backdrop-filter: blur(14px);
    }}
    .brand {{
      display: flex;
      min-width: 250px;
      align-items: center;
      gap: 11px;
    }}
    .brand-mark {{
      position: relative;
      width: 26px;
      height: 26px;
      flex: 0 0 26px;
    }}
    .brand-mark span {{
      position: absolute;
      width: 8px;
      height: 8px;
      background: var(--accent);
      transform: rotate(45deg);
    }}
    .brand-mark span:nth-child(1) {{ left: 9px; top: 0; }}
    .brand-mark span:nth-child(2) {{ left: 0; top: 9px; background: #9f6cf0; }}
    .brand-mark span:nth-child(3) {{ left: 18px; top: 9px; background: #d9589b; }}
    .brand-mark span:nth-child(4) {{ left: 9px; top: 18px; background: #4931a8; }}
    .brand-copy strong {{
      display: block;
      font-size: 14px;
      line-height: 1.2;
    }}
    .brand-copy span {{
      display: block;
      margin-top: 3px;
      color: var(--muted);
      font-size: 12px;
    }}
    .actions {{ display: flex; gap: 10px; flex-wrap: wrap; }}
    button, a.button {{
      display: inline-flex;
      min-height: 38px;
      align-items: center;
      justify-content: center;
      border: 1px solid var(--line-strong);
      background: #fff;
      color: var(--ink);
      border-radius: 6px;
      padding: 8px 12px;
      font: 650 13px Inter, ui-sans-serif, sans-serif;
      cursor: pointer;
      text-decoration: none;
    }}
    button:hover, a.button:hover {{
      border-color: #aeb2bd;
      background: var(--surface-soft);
    }}
    button.primary {{
      background: var(--accent);
      border-color: var(--accent);
      color: white;
    }}
    button.primary:hover {{ background: #5f2fc2; }}
    .layout {{
      display: grid;
      max-width: 1240px;
      grid-template-columns: 210px minmax(0, 760px) 190px;
      gap: 40px;
      align-items: start;
      margin: 0 auto;
      padding: 52px 24px 100px;
    }}
    .section-index, .evidence {{
      position: sticky;
      top: 100px;
      max-height: calc(100vh - 130px);
      overflow-y: auto;
      scrollbar-width: thin;
    }}
    .rail-label {{
      margin: 0 0 14px;
      color: var(--quiet);
      font-size: 11px;
      font-weight: 750;
      letter-spacing: .08em;
      text-transform: uppercase;
    }}
    .section-index nav {{
      display: grid;
      gap: 2px;
      border-left: 1px solid var(--line);
    }}
    .section-index a {{
      display: block;
      margin-left: -1px;
      padding: 6px 0 6px 14px;
      border-left: 2px solid transparent;
      color: var(--muted);
      font-size: 12px;
      line-height: 1.35;
      text-decoration: none;
    }}
    .section-index a:hover {{ color: var(--ink); }}
    .section-index a.active {{
      border-left-color: var(--accent);
      color: var(--ink);
      font-weight: 700;
    }}
    .article {{
      min-width: 0;
    }}
    .article-meta {{
      display: flex;
      flex-wrap: wrap;
      gap: 9px 18px;
      align-items: center;
      margin-bottom: 24px;
      padding-bottom: 18px;
      border-bottom: 1px solid var(--line);
      color: var(--muted);
      font-size: 12px;
    }}
    .article-meta .publication {{
      color: var(--accent);
      font-weight: 750;
    }}
    .article-meta .validated {{
      color: var(--green);
      font-weight: 700;
    }}
    h1 {{
      max-width: 740px;
      margin: 0 0 20px;
      font-family: "Iowan Old Style", "Palatino Linotype", Georgia, serif;
      font-size: 54px;
      line-height: 1.02;
      letter-spacing: 0;
    }}
    h2 {{
      margin: 64px 0 18px;
      padding-top: 8px;
      font-size: 28px;
      line-height: 1.18;
      letter-spacing: 0;
    }}
    h2.dek {{
      max-width: 720px;
      margin: 0 0 34px;
      padding: 0;
      color: var(--muted);
      font-size: 23px;
      font-weight: 450;
      line-height: 1.42;
    }}
    h2.dek + p {{
      margin-top: 0;
      padding: 20px 0 20px 22px;
      border-left: 4px solid var(--accent);
      color: #2f243f;
      font-family: "Iowan Old Style", "Palatino Linotype", Georgia, serif;
      font-size: 24px;
      line-height: 1.42;
    }}
    p {{ margin: 0 0 22px; font-size: 18px; }}
    a {{ color: #5930b7; }}
    code {{
      font-family: Menlo, Monaco, Consolas, "Liberation Mono", monospace;
      font-size: 0.89em;
      background: #eef0f4;
      border-radius: 4px;
      padding: 2px 5px;
    }}
    pre {{
      position: relative;
      margin: 26px 0 32px;
      padding: 44px 24px 24px;
      background: var(--code);
      border: 1px solid #282b38;
      border-radius: 6px;
      overflow-x: auto;
      line-height: 1.5;
    }}
    pre::before {{
      content: attr(data-lang);
      position: absolute;
      top: 14px;
      left: 24px;
      color: #aaa5bd;
      font-family: Inter, ui-sans-serif, sans-serif;
      font-size: 10px;
      font-weight: 750;
      letter-spacing: .08em;
      text-transform: uppercase;
    }}
    pre code {{
      background: transparent;
      color: var(--code-ink);
      padding: 0;
      font-size: 13px;
    }}
    figure {{
      width: calc(100% + 96px);
      margin: 40px 0 42px -48px;
    }}
    figure img {{
      width: 100%;
      height: auto;
      border: 1px solid var(--line-strong);
      display: block;
    }}
    figcaption {{
      color: var(--muted);
      font-size: 12px;
      margin-top: 10px;
      text-align: left;
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
    ul, ol {{ margin: 0 0 26px 22px; padding: 0; font-size: 18px; }}
    li {{ margin: 9px 0; padding-left: 4px; }}
    .evidence {{
      border-left: 1px solid var(--line);
      padding-left: 18px;
    }}
    .evidence dl {{ margin: 0; }}
    .evidence div {{
      padding: 0 0 16px;
      margin: 0 0 16px;
      border-bottom: 1px solid var(--line);
    }}
    .evidence dt {{
      margin-bottom: 4px;
      color: var(--quiet);
      font-size: 10px;
      font-weight: 750;
      letter-spacing: .07em;
      text-transform: uppercase;
    }}
    .evidence dd {{
      margin: 0;
      font-size: 14px;
      font-weight: 700;
      line-height: 1.35;
    }}
    .evidence dd.good {{ color: var(--green); }}
    .evidence dd.alert {{ color: var(--orange); }}
    .repo-link {{
      display: block;
      margin-top: 18px;
      color: var(--accent);
      font-size: 12px;
      font-weight: 700;
      text-decoration: none;
    }}
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
    @media (max-width: 1080px) {{
      .layout {{
        max-width: 900px;
        grid-template-columns: 170px minmax(0, 1fr);
      }}
      .evidence {{ display: none; }}
    }}
    @media (max-width: 760px) {{
      .workspace-bar {{
        position: relative;
        align-items: flex-start;
        flex-direction: column;
        padding: 16px 18px;
      }}
      .brand {{ min-width: 0; }}
      .actions {{ width: 100%; }}
      button, a.button {{ flex: 1 1 auto; }}
      .layout {{
        display: block;
        padding: 34px 20px 70px;
      }}
      .section-index {{ display: none; }}
      h1 {{ font-size: 40px; }}
      h2 {{ margin-top: 52px; font-size: 25px; }}
      h2.dek {{ font-size: 20px; }}
      h2.dek + p {{ font-size: 21px; }}
      p, ul, ol {{ font-size: 17px; }}
      figure {{
        width: 100%;
        margin: 30px 0 34px;
      }}
      pre {{
        width: calc(100vw - 24px);
        margin-left: -8px;
        border-radius: 4px;
      }}
      table {{ display: block; overflow-x: auto; }}
    }}
  </style>
</head>
<body>
  <div class="progress" id="progress"></div>
  <header class="workspace-bar">
    <div class="brand">
      <div class="brand-mark" aria-hidden="true">
        <span></span><span></span><span></span><span></span>
      </div>
      <div class="brand-copy">
        <strong>Kestra Engineering</strong>
        <span>Medium draft workspace</span>
      </div>
    </div>
    <div class="actions">
      <button class="primary" id="copyRendered">Copy article</button>
      <button id="copyMarkdown">Markdown</button>
      <a class="button" href="architecture.png" download>Architecture</a>
      <a class="button" href="results.png" download>Results</a>
    </div>
  </header>
  <div class="layout">
    <aside class="section-index" aria-label="Article sections">
      <p class="rail-label">In this story</p>
      <nav>
{section_nav}
      </nav>
    </aside>
    <main class="article" id="article">
      <div class="article-meta">
        <span class="publication">Engineering</span>
        <span>{word_count:,} words</span>
        <span>{reading_minutes} min read</span>
        <span class="validated">Docker validated</span>
      </div>
{article_html}
    </main>
    <aside class="evidence" aria-label="Validation evidence">
      <p class="rail-label">Run evidence</p>
      <dl>
        <div>
          <dt>Workload</dt>
          <dd>30 client executions</dd>
        </div>
        <div>
          <dt>Independent</dt>
          <dd class="alert">231 requests</dd>
        </div>
        <div>
          <dt>Layered policy</dt>
          <dd class="good">44 requests</dd>
        </div>
        <div>
          <dt>Peak reduced</dt>
          <dd>30 to 4 RPS</dd>
        </div>
        <div>
          <dt>Overload</dt>
          <dd class="good">70 to 0</dd>
        </div>
        <div>
          <dt>Kestra</dt>
          <dd>1.3.21</dd>
        </div>
      </dl>
      <a class="repo-link"
         href="https://github.com/arjunarav/kestra-retry-storm-lab"
         target="_blank" rel="noreferrer">Open runnable repository</a>
    </aside>
  </div>
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

    const progress = document.getElementById("progress");
    const sectionLinks = [...document.querySelectorAll("[data-section]")];
    const sections = sectionLinks
      .map(link => document.getElementById(link.dataset.section))
      .filter(Boolean);

    function updateProgress() {{
      const scrollable = document.documentElement.scrollHeight - innerHeight;
      const ratio = scrollable > 0 ? scrollY / scrollable : 0;
      progress.style.width = `${{Math.min(1, Math.max(0, ratio)) * 100}}%`;
    }}

    const observer = new IntersectionObserver(entries => {{
      const visible = entries
        .filter(entry => entry.isIntersecting)
        .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)[0];
      if (!visible) return;
      sectionLinks.forEach(link => {{
        link.classList.toggle(
          "active",
          link.dataset.section === visible.target.id
        );
      }});
    }}, {{ rootMargin: "-18% 0px -70% 0px" }});

    sections.forEach(section => observer.observe(section));
    addEventListener("scroll", updateProgress, {{ passive: true }});
    updateProgress();
  </script>
</body>
</html>
"""

(ARTICLE_DIR / "index.html").write_text(page, encoding="utf-8")
