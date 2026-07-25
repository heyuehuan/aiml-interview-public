"""Design system for the portal + admin (no frontend build).

GitHub-Primer-inspired: token-driven light/dark theming (system preference by
default, per-user toggle persisted in localStorage), one shared component sheet,
and a common page shell. Everything is server-rendered; the only JS is the theme
toggle and per-page behaviour inlined by the views.
"""
from __future__ import annotations

import html


def esc(s):
    return html.escape(str(s if s is not None else ""))


# --- theme tokens -----------------------------------------------------------
_LIGHT = """
  --bg: #ffffff; --bg-subtle: #f6f8fa; --bg-inset: #f6f8fa; --overlay: #ffffff;
  --border: #d0d7de; --border-muted: #d8dee4;
  --fg: #1f2328; --fg-muted: #656d76;
  --accent: #0969da; --accent-subtle: #ddf4ff;
  --success: #1a7f37; --success-subtle: #dafbe1;
  --danger: #cf222e; --danger-subtle: #ffebe9;
  --attention: #9a6700; --attention-subtle: #fff8c5;
  --severe: #bc4c00; --done: #8250df;
  --btn-bg: #f6f8fa; --btn-hover: #eef1f4; --btn-active-border: #a8b1bb;
  --btn-primary-bg: #1f883d; --btn-primary-hover: #1a7f37;
  --focus-ring: rgba(9,105,218,.3);
  --shadow: 0 1px 3px rgba(31,35,40,.06), 0 8px 24px rgba(31,35,40,.1);
  --code-bg: rgba(175,184,193,.2);
"""

_DARK = """
  --bg: #0d1117; --bg-subtle: #161b22; --bg-inset: #010409; --overlay: #161b22;
  --border: #30363d; --border-muted: #21262d;
  --fg: #e6edf3; --fg-muted: #8d96a0;
  --accent: #4493f8; --accent-subtle: rgba(56,139,253,.15);
  --success: #3fb950; --success-subtle: rgba(46,160,67,.15);
  --danger: #f85149; --danger-subtle: rgba(248,81,73,.15);
  --attention: #d29922; --attention-subtle: rgba(187,128,9,.15);
  --severe: #db6d28; --done: #a371f7;
  --btn-bg: #21262d; --btn-hover: #30363d; --btn-active-border: #8b949e;
  --btn-primary-bg: #238636; --btn-primary-hover: #2ea043;
  --focus-ring: rgba(68,147,248,.35);
  --shadow: 0 0 0 1px #30363d, 0 16px 32px rgba(1,4,9,.85);
  --code-bg: rgba(110,118,129,.25);
"""

CSS = f"""
:root {{ {_LIGHT} color-scheme: light; }}
:root[data-theme="dark"] {{ {_DARK} color-scheme: dark; }}
@media (prefers-color-scheme: dark) {{
  :root:not([data-theme="light"]) {{ {_DARK} color-scheme: dark; }}
}}

* {{ box-sizing: border-box; }}
html, body {{ margin: 0; padding: 0; }}
body {{
  min-height: 100vh; display: flex; flex-direction: column;
  background: var(--bg); color: var(--fg);
  font: 14px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans",
        Helvetica, Arial, sans-serif;
  -webkit-font-smoothing: antialiased;
}}
a {{ color: var(--accent); text-decoration: none; }}
a:hover {{ text-decoration: underline; }}
.mono, code, pre, kbd {{
  font-family: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace;
}}
.muted {{ color: var(--fg-muted); }}
.small {{ font-size: 12px; }}

/* --- page shell ---------------------------------------------------------- */
.app-header {{
  display: flex; align-items: center; justify-content: space-between; gap: 16px;
  padding: 12px 24px; background: var(--bg-subtle);
  border-bottom: 1px solid var(--border-muted);
}}
.app-header .hleft, .app-header .hright {{ display: flex; align-items: center; gap: 12px; min-width: 0; }}
.brand {{ display: flex; align-items: center; gap: 8px; color: var(--fg);
  font-weight: 600; font-size: 14px; white-space: nowrap; }}
.brand:hover {{ text-decoration: none; color: var(--fg); }}
.brand svg {{ width: 22px; height: 22px; display: block; color: var(--fg); }}
.header-ctx {{ color: var(--fg-muted); font-size: 14px; overflow: hidden;
  text-overflow: ellipsis; white-space: nowrap; }}
.header-ctx b {{ color: var(--fg); font-weight: 600; }}

.underline-nav {{
  display: flex; gap: 8px; padding: 0 24px; background: var(--bg-subtle);
  border-bottom: 1px solid var(--border-muted); overflow-x: auto;
}}
.underline-nav a {{
  display: inline-flex; align-items: center; gap: 6px; padding: 8px 12px 10px;
  color: var(--fg); font-size: 14px; border-bottom: 2px solid transparent;
  margin-bottom: -1px; white-space: nowrap;
}}
.underline-nav a:hover {{ text-decoration: none; border-bottom-color: var(--border); }}
.underline-nav a[aria-current] {{ font-weight: 600; border-bottom-color: #fd8c73; }}
.underline-nav a .counter {{
  background: var(--code-bg); border-radius: 999px; padding: 0 6px;
  font-size: 12px; line-height: 18px; color: var(--fg);
}}

main {{ width: 100%; max-width: 1012px; margin: 0 auto; padding: 24px; flex: 1; }}
main.narrow {{ max-width: 380px; }}
main.medium {{ max-width: 640px; }}
main.full {{ max-width: none; padding: 0; display: flex; min-height: 0; }}
body.layout-full {{ height: 100vh; overflow: hidden; }}

footer {{ color: var(--fg-muted); font-size: 12px; text-align: center;
  padding: 24px 0 32px; }}

/* --- typography ---------------------------------------------------------- */
.page-title {{ font-size: 20px; font-weight: 600; margin: 0; }}
.subhead {{
  display: flex; align-items: center; justify-content: space-between; gap: 12px;
  border-bottom: 1px solid var(--border-muted); padding-bottom: 8px; margin: 24px 0 16px;
}}
.subhead:first-child {{ margin-top: 0; }}
.subhead h2 {{ font-size: 16px; font-weight: 600; margin: 0; }}
.subhead .desc {{ color: var(--fg-muted); font-size: 12px; margin: 2px 0 0; }}

/* --- buttons ------------------------------------------------------------- */
.btn {{
  display: inline-flex; align-items: center; justify-content: center; gap: 6px;
  padding: 5px 16px; font: inherit; font-weight: 500; line-height: 20px;
  border-radius: 6px; border: 1px solid var(--border);
  background: var(--btn-bg); color: var(--fg); cursor: pointer;
  text-decoration: none; white-space: nowrap; transition: background .12s;
}}
.btn:hover {{ background: var(--btn-hover); text-decoration: none; }}
.btn:active {{ border-color: var(--btn-active-border); }}
.btn:disabled {{ opacity: .55; cursor: default; }}
.btn-primary {{ background: var(--btn-primary-bg); color: #fff; border-color: rgba(31,35,40,.15); }}
.btn-primary:hover {{ background: var(--btn-primary-hover); }}
.btn-danger {{ color: var(--danger); }}
.btn-danger:hover {{ background: var(--danger); border-color: var(--danger); color: #fff; }}
.btn-sm {{ padding: 3px 12px; font-size: 12px; line-height: 20px; }}
.btn-invisible {{ background: transparent; border-color: transparent; color: var(--accent); }}
.btn-invisible:hover {{ background: var(--btn-bg); }}
.btn-icon {{ padding: 5px 8px; background: transparent; border-color: transparent;
  color: var(--fg-muted); }}
.btn-icon:hover {{ background: var(--btn-bg); border-color: var(--border); color: var(--fg); }}
.btn-block {{ width: 100%; }}
.btn svg {{ width: 16px; height: 16px; display: block; fill: currentColor; }}

/* --- forms --------------------------------------------------------------- */
label {{ display: block; font-weight: 600; font-size: 14px; margin: 16px 0 6px; }}
label:first-child {{ margin-top: 0; }}
.field-hint {{ color: var(--fg-muted); font-size: 12px; margin: 4px 0 0; }}
input[type=text], input[type=password], input[type=number], select, textarea {{
  width: 100%; padding: 5px 12px; font: inherit; line-height: 20px;
  border-radius: 6px; border: 1px solid var(--border);
  background: var(--bg); color: var(--fg);
}}
input:focus, select:focus, textarea:focus, .btn:focus-visible {{
  outline: none; border-color: var(--accent);
  box-shadow: 0 0 0 3px var(--focus-ring);
}}
.btn:focus-visible {{ border-color: transparent; }}
textarea {{ min-height: 96px; resize: vertical; }}
select {{ appearance: auto; }}
input[type=checkbox], input[type=radio] {{ width: auto; accent-color: var(--accent); }}
.checkrow {{ display: flex; align-items: center; gap: 8px; font-weight: 400;
  margin: 6px 0; cursor: pointer; }}
.input-code {{
  text-transform: uppercase; letter-spacing: .45em; text-indent: .45em;
  text-align: center; font-size: 24px; padding: 10px;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
}}

/* --- box / table --------------------------------------------------------- */
.box {{ background: var(--bg); border: 1px solid var(--border); border-radius: 6px; }}
.box + .box {{ margin-top: 16px; }}
.box-header {{
  display: flex; align-items: center; justify-content: space-between; gap: 12px;
  padding: 12px 16px; background: var(--bg-subtle);
  border-bottom: 1px solid var(--border); border-radius: 6px 6px 0 0;
}}
.box-header h2 {{ font-size: 14px; font-weight: 600; margin: 0; }}
.box-body {{ padding: 16px; }}
.box-row {{ padding: 12px 16px; border-top: 1px solid var(--border-muted); }}
.box-row:first-child {{ border-top: 0; }}

table.table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
.table th {{
  text-align: left; padding: 8px 16px; color: var(--fg-muted);
  font-size: 12px; font-weight: 600; background: var(--bg-subtle);
  border-bottom: 1px solid var(--border);
}}
.table td {{ padding: 8px 16px; border-top: 1px solid var(--border-muted);
  vertical-align: middle; }}
.table tr:first-child td {{ border-top: 0; }}
.box > .table th:first-child, .box > .table td:first-child {{ padding-left: 16px; }}
.box .table {{ border-radius: 6px; overflow: hidden; }}

.blankslate {{ text-align: center; padding: 32px 16px; color: var(--fg-muted); }}

/* --- labels / state ------------------------------------------------------ */
.label {{
  display: inline-flex; align-items: center; gap: 6px; padding: 0 10px;
  height: 20px; border-radius: 999px; font-size: 12px; font-weight: 500;
  border: 1px solid var(--border); color: var(--fg-muted); white-space: nowrap;
}}
.label.mono {{ font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }}
.state-dot {{ width: 8px; height: 8px; border-radius: 50%; display: inline-block;
  background: currentColor; flex: none; }}
.st-created {{ color: var(--attention); border-color: var(--attention); }}
.st-active {{ color: var(--success); border-color: var(--success); }}
.st-closed {{ color: var(--severe); border-color: var(--severe); }}
.st-exported {{ color: var(--done); border-color: var(--done); }}
.st-reset {{ color: var(--fg-muted); }}

/* --- flash banners ------------------------------------------------------- */
.flash {{ padding: 12px 16px; border-radius: 6px; border: 1px solid; margin-bottom: 16px;
  font-size: 14px; }}
.flash-ok {{ background: var(--success-subtle); border-color: var(--success); }}
.flash-err {{ background: var(--danger-subtle); border-color: var(--danger); }}
.flash-info {{ background: var(--accent-subtle); border-color: var(--accent); }}

/* --- code / key display --------------------------------------------------- */
pre.code-block {{
  background: var(--bg-inset); border: 1px solid var(--border-muted);
  border-radius: 6px; padding: 12px 16px; overflow-x: auto; margin: 8px 0 0;
  font-size: 12px; line-height: 1.55; color: var(--fg);
}}
.code-label {{ margin: 16px 0 0; font-size: 12px; color: var(--fg-muted);
  font-weight: 600; text-transform: uppercase; letter-spacing: .04em; }}
.token-box {{
  display: flex; align-items: center; gap: 8px;
  background: var(--bg-inset); border: 1px solid var(--border);
  border-radius: 6px; padding: 6px 8px 6px 12px;
}}
.token-box code {{ flex: 1; font-size: 13px; overflow-x: auto; white-space: nowrap;
  user-select: all; scrollbar-width: none; }}

/* --- layout helpers ------------------------------------------------------ */
.row {{ display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }}
.row-split {{ justify-content: space-between; }}
.grid {{ display: grid; gap: 16px; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); }}
form.inline {{ display: inline; margin: 0; }}
.dl-grid {{ display: grid; grid-template-columns: minmax(120px, max-content) 1fr;
  gap: 8px 24px; margin: 0; font-size: 14px; }}
.dl-grid dt {{ color: var(--fg-muted); }}
.dl-grid dd {{ margin: 0; overflow-wrap: anywhere; }}

/* --- home tiles ----------------------------------------------------------- */
a.tile {{ display: block; color: inherit; background: var(--bg);
  border: 1px solid var(--border); border-radius: 6px; padding: 16px;
  transition: border-color .12s, box-shadow .12s; }}
a.tile:hover {{ text-decoration: none; border-color: var(--accent);
  box-shadow: 0 0 0 1px var(--accent); }}
a.tile .ico {{ height: 36px; display: flex; align-items: center; }}
a.tile .ico svg {{ width: 30px; height: 30px; display: block; }}
a.tile h2 {{ margin: 10px 0 2px; font-size: 14px; font-weight: 600; }}
a.tile p {{ margin: 0; color: var(--fg-muted); font-size: 12px; }}

/* --- dialog --------------------------------------------------------------- */
.dialog-overlay {{ position: fixed; inset: 0; background: rgba(1,4,9,.5);
  display: flex; align-items: center; justify-content: center; z-index: 90;
  padding: 16px; }}
.dialog-overlay[hidden] {{ display: none; }}
.dialog {{ background: var(--overlay); border: 1px solid var(--border);
  border-radius: 12px; box-shadow: var(--shadow); width: 100%; max-width: 440px;
  max-height: 90vh; overflow: auto; }}
.dialog-header {{ display: flex; align-items: center; justify-content: space-between;
  padding: 12px 16px; border-bottom: 1px solid var(--border-muted); font-weight: 600; }}
.dialog-body {{ padding: 16px; }}
.dialog-footer {{ display: flex; justify-content: flex-end; gap: 8px;
  padding: 12px 16px; border-top: 1px solid var(--border-muted); }}

/* --- rendered problem statements (.md) ------------------------------------ */
.md {{ font-size: 16px; line-height: 1.6; }}
.md h2, .md h3, .md h4, .md h5, .md h6 {{ line-height: 1.3; margin: 24px 0 8px;
  font-weight: 600; }}
.md h2 {{ font-size: 1.25em; border-bottom: 1px solid var(--border-muted);
  padding-bottom: 6px; }}
.md h3 {{ font-size: 1.1em; }} .md h4 {{ font-size: 1em; }}
.md > :first-child {{ margin-top: 0; }}
.md p {{ margin: 10px 0; }}
.md ul, .md ol {{ margin: 8px 0 8px 24px; padding: 0; }}
.md li {{ margin: 4px 0; }}
.md code {{ background: var(--code-bg); border-radius: 6px; padding: .1em .35em;
  font-size: .85em; }}
.md pre.code {{ background: var(--bg-inset); border: 1px solid var(--border-muted);
  border-radius: 6px; padding: 12px 16px; overflow-x: auto; margin: 12px 0;
  font-size: 13px; line-height: 1.5; }}
.md pre.code code {{ background: none; padding: 0; font-size: inherit; }}
.md table {{ border-collapse: collapse; margin: 12px 0; display: block;
  overflow-x: auto; }}
.md th, .md td {{ border: 1px solid var(--border); padding: 6px 12px;
  vertical-align: top; }}
.md th {{ background: var(--bg-subtle); }}
.md hr {{ border: 0; border-top: 1px solid var(--border-muted); margin: 20px 0; }}
.md blockquote {{ margin: 12px 0; padding: 0 1em; color: var(--fg-muted);
  border-left: 3px solid var(--border); }}

/* --- selectable multiple-choice options -------- */
.mcq {{ margin: 12px 0 20px; }}
.mcq-opts {{ display: flex; flex-direction: column; gap: 6px; }}
.mcq-opt {{ display: flex; align-items: flex-start; gap: 10px; cursor: pointer;
  padding: 10px 12px; border: 1px solid var(--border); border-radius: 6px;
  background: var(--bg); font-size: 15px; line-height: 1.5; }}
.mcq-opt:hover {{ border-color: var(--accent); }}
.mcq-opt.is-on {{ border-color: var(--accent); background: var(--accent-subtle); }}
.mcq-opt input {{ margin-top: 3px; flex: none; }}
.mcq-key {{ font-weight: 600; flex: none; }}
.mcq-text code {{ background: var(--code-bg); border-radius: 6px; padding: .1em .35em;
  font-size: .85em; }}
.mcq-foot {{ display: flex; align-items: center; gap: 10px; margin-top: 10px; }}
.mcq-status {{ color: var(--fg-muted); }}
.mcq-status.ok {{ color: var(--success); }}
.mcq-status.err {{ color: var(--danger); }}
"""

# --- brand + icon SVGs ------------------------------------------------------
BRAND_MARK = (
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" '
    'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
    '<path d="M12 2.5 4.5 5.2v5.6c0 4.7 3.2 8.1 7.5 9.7 4.3-1.6 7.5-5 7.5-9.7V5.2z"/>'
    '<path d="m9 11.8 2 2 4-4"/></svg>'
)
ICON_SUN = (
    '<svg class="i-sun" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">'
    '<path d="M8 12a4 4 0 1 1 0-8 4 4 0 0 1 0 8Zm0-1.5a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5Z'
    'M8 0a.75.75 0 0 1 .75.75v1.5a.75.75 0 0 1-1.5 0V.75A.75.75 0 0 1 8 0ZM8 13a.75.75 0 0 1 '
    '.75.75v1.5a.75.75 0 0 1-1.5 0v-1.5A.75.75 0 0 1 8 13ZM2.343 2.343a.75.75 0 0 1 1.061 0l1.06 '
    '1.061a.75.75 0 0 1-1.06 1.06l-1.06-1.06a.75.75 0 0 1 0-1.06Zm9.193 9.193a.75.75 0 0 1 1.06 0l'
    '1.061 1.06a.75.75 0 0 1-1.06 1.061l-1.061-1.06a.75.75 0 0 1 0-1.061ZM16 8a.75.75 0 0 1-.75.75'
    'h-1.5a.75.75 0 0 1 0-1.5h1.5A.75.75 0 0 1 16 8ZM3 8a.75.75 0 0 1-.75.75H.75a.75.75 0 0 1 '
    '0-1.5h1.5A.75.75 0 0 1 3 8Zm10.657-5.657a.75.75 0 0 1 0 1.061l-1.061 1.06a.75.75 0 1 1-1.06-'
    '1.06l1.06-1.06a.75.75 0 0 1 1.061 0Zm-9.193 9.193a.75.75 0 0 1 0 1.06l-1.06 1.061a.75.75 0 1 '
    '1-1.061-1.06l1.06-1.061a.75.75 0 0 1 1.061 0Z"/></svg>'
)
ICON_MOON = (
    '<svg class="i-moon" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">'
    '<path d="M9.598 1.591a.749.749 0 0 1 .785-.175 7.001 7.001 0 1 1-8.967 8.967.75.75 0 0 1 '
    '.961-.96 5.5 5.5 0 0 0 7.046-7.046.75.75 0 0 1 .175-.786Zm1.616 1.945a7 7 0 0 1-7.678 '
    '7.678 5.499 5.499 0 1 0 7.678-7.678Z"/></svg>'
)
ICON_COPY = (
    '<svg viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">'
    '<path d="M0 6.75C0 5.784.784 5 1.75 5h1.5a.75.75 0 0 1 0 1.5h-1.5a.25.25 0 0 0-.25.25v7.5c0 '
    '.138.112.25.25.25h7.5a.25.25 0 0 0 .25-.25v-1.5a.75.75 0 0 1 1.5 0v1.5A1.75 1.75 0 0 1 9.25 '
    '16h-7.5A1.75 1.75 0 0 1 0 14.25Z"/><path d="M5 1.75C5 .784 5.784 0 6.75 0h7.5C15.216 0 16 '
    '.784 16 1.75v7.5A1.75 1.75 0 0 1 14.25 11h-7.5A1.75 1.75 0 0 1 5 9.25Zm1.75-.25a.25.25 0 0 '
    '0-.25.25v7.5c0 .138.112.25.25.25h7.5a.25.25 0 0 0 .25-.25v-7.5a.25.25 0 0 0-.25-.25Z"/></svg>'
)
ICON_CHECK = (
    '<svg viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">'
    '<path d="M13.78 4.22a.75.75 0 0 1 0 1.06l-7.25 7.25a.75.75 0 0 1-1.06 0L2.22 9.28a.751.751 '
    '0 0 1 .018-1.042.751.751 0 0 1 1.042-.018L6 10.94l6.72-6.72a.75.75 0 0 1 1.06 0Z"/></svg>'
)
# Gemini four-point spark (self-contained; brand gradient).
GEMINI_MARK = (
    '<svg viewBox="0 0 24 24" aria-hidden="true">'
    '<defs><linearGradient id="gem" x1="0" y1="0" x2="24" y2="24" '
    'gradientUnits="userSpaceOnUse">'
    '<stop offset="0" stop-color="#4285f4"/><stop offset="0.5" stop-color="#9b72cb"/>'
    '<stop offset="1" stop-color="#d96570"/></linearGradient></defs>'
    '<path fill="url(#gem)" d="M12 0c.34 6.35 5.65 11.66 12 12-6.35.34-11.66 5.65-12 12'
    '-.34-6.35-5.65-11.66-12-12C6.35 11.66 11.66 6.35 12 0z"/></svg>'
)

# Set the resolved theme before first paint: explicit choice from localStorage,
# else the OS preference; keep following the OS while no explicit choice is made.
_THEME_INIT = """<script>
(function(){
  var mq = window.matchMedia('(prefers-color-scheme: dark)');
  function apply(){
    var t; try { t = localStorage.getItem('theme'); } catch(e){}
    if (t !== 'light' && t !== 'dark') t = mq.matches ? 'dark' : 'light';
    document.documentElement.setAttribute('data-theme', t);
  }
  apply();
  mq.addEventListener('change', apply);
})();
</script>"""

_THEME_TOGGLE_CSS = """
#theme-toggle .i-sun { display: none; }
:root[data-theme="dark"] #theme-toggle .i-sun { display: block; }
:root[data-theme="dark"] #theme-toggle .i-moon { display: none; }
"""

_THEME_TOGGLE_SCRIPT = """<script>
(function(){
  var b = document.getElementById('theme-toggle');
  if (!b) return;
  b.addEventListener('click', function(){
    var next = document.documentElement.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', next);
    try { localStorage.setItem('theme', next); } catch(e){}
  });
})();
</script>"""


def theme_toggle():
    return (f'<button type="button" class="btn btn-icon" id="theme-toggle" '
            f'aria-label="Toggle theme" title="Toggle theme">{ICON_SUN}{ICON_MOON}</button>')


def page(title, body, *, brand="Technical Interview Platform", brand_href="/", header_ctx="",
         header_right="", nav="", width="", full=False, head_extra="", footer=True):
    """Common shell. ``width``: '' (default 1012px) | 'narrow' | 'medium'.
    ``full``: viewport-height app layout (no footer, main is a flex row).
    ``nav``: pre-rendered <a> items for an underline tab nav under the header."""
    nav_html = f'<nav class="underline-nav">{nav}</nav>' if nav else ""
    main_cls = "full" if full else width
    foot = "" if (full or not footer) else "<footer>&copy; 2026 Technical Interview Platform</footer>"
    return f"""<!doctype html><html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<style>{CSS}{_THEME_TOGGLE_CSS}</style>{_THEME_INIT}{head_extra}</head>
<body{' class="layout-full"' if full else ''}>
<header class="app-header">
  <div class="hleft">
    <a class="brand" href="{esc(brand_href)}">{BRAND_MARK}<span>{esc(brand)}</span></a>
    {f'<span class="header-ctx">{header_ctx}</span>' if header_ctx else ''}
  </div>
  <div class="hright">{header_right}{theme_toggle()}</div>
</header>
{nav_html}
<main class="{main_cls}">{body}</main>
{foot}
{_THEME_TOGGLE_SCRIPT}
</body></html>"""


# --- shared components ------------------------------------------------------
def nav_item(href, label, current=False, counter=None):
    cur = ' aria-current="page"' if current else ""
    extra = f'<span class="counter">{esc(counter)}</span>' if counter is not None else ""
    return f'<a href="{esc(href)}"{cur}>{esc(label)}{extra}</a>'


def flash(text, kind="ok"):
    return f'<div class="flash flash-{kind}">{esc(text)}</div>' if text else ""


def state_label(state):
    return (f'<span class="label st-{esc(state)}"><span class="state-dot"></span>'
            f'{esc(state)}</span>')


def copy_button(value, label="Copy", small=True):
    """A copy-to-clipboard button (event delegation wired by COPY_SCRIPT)."""
    cls = "btn btn-sm" if small else "btn"
    return (f'<button type="button" class="{cls} js-copy" data-copy="{esc(value)}">'
            f'{ICON_COPY}<span>{esc(label)}</span></button>')


COPY_SCRIPT = """<script>
document.addEventListener('click', function(e){
  var b = e.target.closest('.js-copy');
  if (!b) return;
  navigator.clipboard.writeText(b.getAttribute('data-copy')).then(function(){
    var s = b.querySelector('span'), old = s.textContent;
    s.textContent = 'Copied!';
    setTimeout(function(){ s.textContent = old; }, 1200);
  });
});
</script>"""


def confirm_dialog():
    """Confirmation dialog for destructive actions: buttons with `.js-confirm` +
    `data-confirm` open it; Confirm submits the button's enclosing form."""
    return """
<div id="confirm-overlay" class="dialog-overlay" hidden>
  <div class="dialog">
    <div class="dialog-header">Are you sure?</div>
    <div class="dialog-body"><p id="confirm-msg" style="margin:0"></p></div>
    <div class="dialog-footer">
      <button class="btn" id="confirm-cancel" type="button">Cancel</button>
      <button class="btn btn-danger" id="confirm-ok" type="button">Confirm</button>
    </div>
  </div>
</div>
<script>
(function(){
  var overlay = document.getElementById('confirm-overlay'),
      msg = document.getElementById('confirm-msg'),
      ok = document.getElementById('confirm-ok'),
      cancel = document.getElementById('confirm-cancel'), pending = null;
  function hide(){ overlay.hidden = true; pending = null; }
  document.addEventListener('click', function(e){
    var btn = e.target.closest('.js-confirm');
    if (!btn) return;
    e.preventDefault();
    pending = btn.closest('form');
    msg.textContent = btn.getAttribute('data-confirm') || 'Are you sure?';
    overlay.hidden = false;
  });
  ok.addEventListener('click', function(){ if (pending) pending.submit(); });
  cancel.addEventListener('click', hide);
  overlay.addEventListener('click', function(e){ if (e.target === overlay) hide(); });
  document.addEventListener('keydown', function(e){ if (e.key === 'Escape') hide(); });
})();
</script>"""


def confirm_attrs(cls, confirm):
    """class + data-confirm attributes for a confirm-through-dialog button."""
    cls_attr = f"{cls} js-confirm".strip() if confirm else cls
    extra = f' data-confirm="{esc(confirm)}"' if confirm else ""
    return cls_attr, extra
