# Copyright 2026 Gentian Authors. Licensed under LGPL-3.0.

"""A summary as it is written -- plain text or Markdown -- as HTML.

Recorders and models write a summary with bullets, ticked boxes, headings
and bold text. Odoo keeps a summary as HTML, and plain text given to it
loses its line breaks. So a summary that is not HTML already is turned into
HTML here, the same way every time, whoever files it. The text is escaped
first: nothing in it becomes markup of its own.
"""

import re
from html import escape

_HTML = re.compile(r"^\s*<(p|div|ul|ol|h[1-6]|table|br|span|strong|em|b|i)\b", re.IGNORECASE)
_EMPTY_LINK = re.compile(r"\s*\[\]\([^)]*\)")
_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_BOLD = re.compile(r"\*\*(.+?)\*\*")
_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_BOX = re.compile(r"^[-*]\s+\[([ xX])\]\s+(.*)$")
_ITEM = re.compile(r"^[-*]\s+(.*)$")


def is_html(text):
    return bool(_HTML.match(text or ""))


def _inline(line):
    line = _EMPTY_LINK.sub("", line)
    line = _LINK.sub(r"\1", line)
    line = escape(line, quote=False)
    return _BOLD.sub(r"<strong>\1</strong>", line)


def to_html(text):
    """The summary as HTML; HTML given is kept as it is."""
    if not text or is_html(text):
        return text
    out = []
    items = []
    lines = []

    def close():
        if items:
            out.append("<ul>" + "".join(items) + "</ul>")
            items.clear()
        if lines:
            out.append("<p>" + "<br>".join(lines) + "</p>")
            lines.clear()

    for raw in text.splitlines():
        line = raw.strip()
        if not _EMPTY_LINK.sub("", line).strip():
            close()
            continue
        heading = _HEADING.match(line)
        box = _BOX.match(line)
        item = _ITEM.match(line)
        if heading:
            close()
            level = min(len(heading.group(1)) + 2, 6)
            out.append(f"<h{level}>{_inline(heading.group(2))}</h{level}>")
        elif box:
            if lines:
                close()
            mark = "☑" if box.group(1) in "xX" else "☐"
            items.append(f"<li>{mark} {_inline(box.group(2))}</li>")
        elif item:
            if lines:
                close()
            items.append(f"<li>{_inline(item.group(1))}</li>")
        else:
            if items:
                close()
            lines.append(_inline(line))
    close()
    return "".join(out)
