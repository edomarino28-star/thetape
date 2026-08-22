r"""Render collected filings into a self-contained HTML dashboard."""
import json
import os
import webbrowser

from .collect import OUT, collect

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(HERE, "template.html")


STANDALONE_HEAD = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
</head>
<body>
"""


def render(data=None, path=None, open_browser=False, standalone=True):
    """Write the dashboard.

    standalone=True wraps the page in a real document so a double-clicked file
    renders in standards mode. The Artifact host supplies its own doctype and
    head, so the copy published there is written with standalone=False.
    """
    if data is None:
        with open(os.path.join(OUT, "data.json"), encoding="utf-8") as fh:
            data = json.load(fh)
    with open(TEMPLATE, encoding="utf-8") as fh:
        html = fh.read()
    blob = json.dumps(data, default=str).replace("</", "<\\/")
    html = html.replace("__DATA__", blob)
    if standalone:
        html = STANDALONE_HEAD + html + "\n</body>\n</html>\n"

    os.makedirs(OUT, exist_ok=True)
    path = path or os.path.join(OUT, "dashboard.html")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(html)
    if open_browser:
        webbrowser.open("file:///" + path.replace("\\", "/"))
    return path


def build(days=14, max_filings=600, congress_days=60, max_ptrs=60,
          funds=("1067983", "1336528", "1649339"), refresh=True,
          open_browser=True, log=print):
    data = None
    if refresh:
        data = collect(days=days, max_filings=max_filings,
                       congress_days=congress_days, max_ptrs=max_ptrs,
                       funds=funds, log=log)
    # artifact-ready fragment (host supplies doctype/head)
    render(data, path=os.path.join(OUT, "artifact.html"),
           standalone=False, open_browser=False)
    path = render(data, open_browser=open_browser)
    log(f"dashboard -> {path}")

    try:
        from . import shortcut
        link = shortcut.create(path)
        if link:
            log(f"desktop   -> {link}")
    except Exception as e:                       # a missing Desktop is not fatal
        log(f"(no desktop shortcut: {e})")
    return path
