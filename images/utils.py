"""
Utility functions for the images app.
Includes markdown rendering and HTML sanitization.
"""

import markdown
from markdown.extensions import Extension
from markdown.inlinepatterns import InlineProcessor
from xml.etree import ElementTree as etree
import nh3
from django.urls import reverse


# Allowed HTML tags for sanitized content
ALLOWED_TAGS = {
    'p', 'br', 'strong', 'em', 'u',
    'ul', 'ol', 'li', 'blockquote', 'a'
}

# Allowed attributes per tag
ALLOWED_ATTRIBUTES = {
    'a': {'href', 'title'},
}


class ImageReferenceProcessor(InlineProcessor):
    """
    Processor for converting #1234 image references to links.
    Pattern: #DIGITS (e.g., #1234)
    Works at start of lines, in the middle of text, and after whitespace.
    """
    def __init__(self, pattern, markdown_instance):
        super().__init__(pattern, markdown_instance)

    def handleMatch(self, m, data):
        """Handle matches of image reference pattern."""
        image_id = m.group(1)

        # Create an anchor element
        el = etree.Element('a')
        el.text = f'#{image_id}'

        # Generate URL to image detail page
        try:
            el.set('href', reverse('images:image_detail', kwargs={'image_id': image_id}))
            el.set('title', f'Image #{image_id}')
        except Exception:
            # If URL generation fails, just return the text as-is
            el.text = f'#{image_id}'

        return el, m.start(0), m.end(0)


class ImageReferenceExtension(Extension):
    """
    Extension to convert #DIGITS to links to image detail pages.
    """
    def extendMarkdown(self, md):
        """Register the image reference processor with markdown."""
        pattern = r'#(\d+)'
        processor = ImageReferenceProcessor(pattern, md)
        md.inlinePatterns.register(processor, 'image_reference', 190)


class NoHeadersExtension(Extension):
    """
    Extension to disable heading parsing.
    This allows #1234 to be treated as content, not as heading syntax.
    """
    def extendMarkdown(self, md):
        """Remove the heading processors to allow # in content."""
        # Deregister hash-style heading processor (#, ##, etc.)
        md.parser.blockprocessors.deregister('hashheader')
        # Deregister setext-style heading processor (underline style)
        md.parser.blockprocessors.deregister('setextheader')


def render_markdown(text):
    """
    Convert markdown text to HTML.

    Disables heading syntax to allow #1234 image references.

    Args:
        text (str): Markdown text to render

    Returns:
        str: HTML string (not yet sanitized)
    """
    if not text:
        return ''

    # Convert markdown to HTML with custom extensions
    html = markdown.markdown(
        text,
        extensions=[
            NoHeadersExtension(),
            ImageReferenceExtension(),
        ]
    )

    return html


def sanitize_html(html_string):
    """
    Sanitize HTML by removing potentially dangerous elements and attributes.
    Uses nh3 for safe HTML filtering.

    Args:
        html_string (str): HTML to sanitize

    Returns:
        str: Sanitized HTML
    """
    if not html_string:
        return ''

    # Sanitize using nh3 with our allowed tags and attributes
    sanitized = nh3.clean(
        html_string,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
    )

    return sanitized


def render_markdown_safe(text):
    """
    Render markdown to HTML and sanitize the result.
    Safe wrapper combining render_markdown and sanitize_html.

    Args:
        text (str): Markdown text to render

    Returns:
        str: Sanitized HTML
    """
    if not text:
        return ''

    # First convert markdown to HTML
    html = render_markdown(text)

    # Then sanitize the result
    sanitized = sanitize_html(html)

    return sanitized
