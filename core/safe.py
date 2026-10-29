"""Helpers for showing text typed by other users (listing descriptions, messages,
reviews, cooperative names) without letting it act as markdown: no links,
images, headings or formatting injected into the page."""

import re

_MD_SPECIALS = re.compile(r"([\\`*_{}\[\]()#+\-.!|>~<$:&])")


def md_escape(text) -> str:
    """Escape markdown/HTML-significant characters so `text` renders literally in st.markdown."""
    return _MD_SPECIALS.sub(r"\\\1", str(text or ""))
