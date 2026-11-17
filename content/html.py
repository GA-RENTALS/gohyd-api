"""Safe rich text for blog posts.

Staff write posts in a small editor (paragraphs, headings, bold/italic, lists, quotes, links). The HTML is cleaned
when it is saved and again when the public API returns it, so the website can show it as formatted text without
trusting what is stored. Anything outside the allow-list (scripts, styles, event handlers, images, iframes) is removed.
"""
import html

import nh3

ALLOWED_TAGS = {'p', 'br', 'h2', 'h3', 'strong', 'em', 'u', 's', 'ul', 'ol', 'li', 'blockquote', 'a', 'hr'}
ALLOWED_ATTRIBUTES = {'a': {'href', 'title'}}
LINK_SCHEMES = {'http', 'https', 'mailto', 'tel'}

# Browsers' editors produce <b>/<i>/<div>; map them to the tags we keep so formatting isn't lost.
_EQUIVALENT = (('<b>', '<strong>'), ('</b>', '</strong>'), ('<i>', '<em>'), ('</i>', '</em>'),
               ('<div>', '<p>'), ('</div>', '</p>'), ('<h1>', '<h2>'), ('</h1>', '</h2>'))


def clean_html(value: str) -> str:
    """Allow-listed HTML. Plain text (older posts, or text typed in the Django admin) becomes paragraphs."""
    value = (value or '').strip()
    if not value:
        return ''
    if '<' not in value:
        paragraphs = [p.strip() for p in value.replace('\r\n', '\n').split('\n\n') if p.strip()]
        return ''.join(f'<p>{html.escape(p).replace(chr(10), "<br>")}</p>' for p in paragraphs)
    for old, new in _EQUIVALENT:
        value = value.replace(old, new)
    cleaned = nh3.clean(value, tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRIBUTES, url_schemes=LINK_SCHEMES,
                        link_rel='noopener noreferrer nofollow', strip_comments=True)
    # An editor leaves empty paragraphs behind when lines are deleted.
    for empty in ('<p></p>', '<p><br></p>'):
        cleaned = cleaned.replace(empty, '')
    return cleaned.strip()
