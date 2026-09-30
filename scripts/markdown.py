"""Faithful UTF-8 reader Markdown, using only the Python standard library.

CommonMark text is emitted for common structures. Semantic HTML without a
portable Markdown equivalent (tables with spans, superscripts, underline, typed
lists, IDs and the exact AI notice) remains HTML rather than losing meaning.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from html.parser import HTMLParser
import re
from urllib.parse import urljoin


@dataclass
class Node:
    tag: str
    attrs: dict = field(default_factory=dict)
    children: list = field(default_factory=list)
    start: int = 0
    end: int = 0


class Tree(HTMLParser):
    VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self, source: str):
        super().__init__(convert_charrefs=True)
        self.source = source
        self.offsets = [0]
        for line in source.splitlines(keepends=True):
            self.offsets.append(self.offsets[-1] + len(line))
        self.root = Node("root")
        self.stack = [self.root]
        self.feed(source)
        self.close()
        if len(self.stack) != 1:
            raise ValueError("Unclosed article HTML")

    def position(self):
        line, column = self.getpos()
        return self.offsets[line - 1] + column

    def handle_starttag(self, tag, attrs):
        start = self.position()
        node = Node(tag, dict(attrs), start=start, end=start + len(self.get_starttag_text()))
        self.stack[-1].children.append(node)
        if tag not in self.VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in self.VOID:
            self.stack.pop()

    def handle_endtag(self, tag):
        if len(self.stack) <= 1 or self.stack[-1].tag != tag:
            raise ValueError(f"Mismatched article HTML closing tag: {tag}")
        node = self.stack.pop()
        node.end = self.source.index(">", self.position()) + 1

    def handle_data(self, data):
        self.stack[-1].children.append(data)

    def raw(self, node):
        return self.source[node.start:node.end]


def escape_text(text: str) -> str:
    # Escape literal Markdown/HTML punctuation so source wording isn't parsed as
    # an accidental list, link, heading or entity. Reader-rendered text is exact.
    text = text.replace("&", "&amp;")
    return re.sub(r"([\\`*_{}\[\]<>#!|~.()+\-=])", r"\\\1", text)


def _text(node) -> str:
    if isinstance(node, str):
        return node
    return "".join(_text(child) for child in node.children)


def html_to_markdown(source: str, canonical_url: str = "") -> str:
    tree = Tree(source)
    protected = []

    def raw_html(node):
        marker = f"\x00RAW{len(protected)}\x00"
        protected.append(tree.raw(node))
        return marker

    def inline_emphasis(value, marker):
        leading = value[:len(value) - len(value.lstrip())]
        trailing = value[len(value.rstrip()):]
        return leading + marker + value.strip() + marker + trailing

    def render(node):
        if isinstance(node, str):
            return escape_text(re.sub(r"\s+", " ", node))
        tag, attrs = node.tag, node.attrs
        # Preserve exact application-owned notice markup, including original
        # authoritative-English compatibility URL, model and localized wording.
        if attrs.get("data-translation-notice") == "ai":
            return "\n\n" + raw_html(node) + "\n\n"
        if tag in {"table", "dl", "pre", "u", "sup", "sub", "mark", "cite", "kbd", "samp", "del", "ins", "abbr", "ruby"} or "id" in attrs or (tag == "ol" and attrs.get("type")):
            raw = raw_html(node)
            return "\n\n" + raw + "\n\n" if tag in {"table", "dl", "pre", "ol"} or tag.startswith("h") else raw
        if tag == "img":
            alt = escape_text(attrs.get("alt", ""))
            url = urljoin(canonical_url, attrs.get("src", ""))
            title = attrs.get("title")
            suffix = ' "' + title.replace('"', '&quot;') + '"' if title else ""
            return f"![{alt}](<{url}>{suffix})"
        if tag == "br":
            return "  \n"
        if tag == "hr":
            return "\n\n---\n\n"
        value = "".join(render(child) for child in node.children)
        if tag in {"root", "article"}:
            return value
        if tag in {"strong", "b"}:
            return inline_emphasis(value, "**")
        if tag in {"em", "i"}:
            return inline_emphasis(value, "*")
        if tag == "code":
            backticks = "`" * (max([len(x) for x in re.findall(r"`+", _text(node))] or [0]) + 1)
            return backticks + " " + _text(node) + " " + backticks
        if tag == "a":
            href = attrs.get("href", "")
            target = href if href.startswith("#") else urljoin(canonical_url, href)
            return f"[{value.strip()}](<{target}>)"
        if re.fullmatch(r"h[1-6]", tag):
            return "\n\n" + "#" * int(tag[1]) + " " + value.strip() + "\n\n"
        if tag == "blockquote":
            value = re.sub(r"\n{3,}", "\n\n", value.strip())
            return "\n\n" + "\n".join("> " + line if line else ">" for line in value.splitlines()) + "\n\n"
        if tag in {"ol", "ul"}:
            start = int(attrs.get("start", 1))
            lines = []
            for child in node.children:
                if not isinstance(child, Node) or child.tag != "li":
                    continue
                body = "".join(render(grandchild) for grandchild in child.children).strip()
                marker = f"{start}. " if tag == "ol" else "- "
                parts = body.splitlines() or [""]
                lines.append(marker + parts[0] + "".join("\n" + " " * len(marker) + line for line in parts[1:]))
                start += 1
            return "\n\n" + "\n".join(lines) + "\n\n"
        if tag == "figcaption":
            # Caption is its own exact paragraph, not misleading invented credit.
            return "\n\n" + value.strip() + "\n\n"
        if tag in {"p", "div", "section", "aside", "figure", "footer", "header", "li", "address"}:
            return "\n\n" + value.strip() + "\n\n"
        if tag == "span":
            return value
        if tag == "wbr":
            return ""
        # Never silently flatten unsupported semantics.
        return raw_html(node)

    markdown = render(tree.root)
    # Trim indentation whitespace introduced between source block tags. Do not
    # strip the two trailing spaces that represent original intentional <br>s.
    markdown = re.sub(r"\n[ \t]+\n", "\n\n", markdown)
    markdown = re.sub(r"\n{3,}", "\n\n", markdown)
    markdown = markdown.strip()
    for position, raw in enumerate(protected):
        markdown = markdown.replace(f"\x00RAW{position}\x00", raw)
    return markdown + "\n"


def generate_markdown(article: dict, canonical_url: str, issue_label: str) -> str:
    """Reader-facing metadata + all semantic article content and attribution.

    Labels may be localized with article['markdown_labels']; source text and
    publication/byline identifiers are never translated or editorially rewritten.
    """
    labels = {"language": "Language", "byline": "Byline", "issue": "Original magazine issue", "pages": "Source pages", "canonical": "Read online", "source": "Original source", "credits": "Image credits", "untitled": "Untitled article", "issue_number": "Issue number"}
    labels.update(article.get("markdown_labels", {}))
    title = article.get("title")
    heading = escape_text(title) if title else "[" + escape_text(labels["untitled"]) + "]"
    lines = ["# " + heading, ""]
    if article.get("subtitle"):
        lines.extend([escape_text(article["subtitle"]), ""])
    if article.get("section"):
        lines.extend([escape_text(article["section"]), ""])
    lines.append(f"{escape_text(labels['language'])}: {escape_text(article['locale'])}  ")
    byline_metadata = article.get("byline") or {}
    byline = byline_metadata if isinstance(byline_metadata, str) else byline_metadata.get("raw")
    if byline:
        lines.append(f"{escape_text(labels['byline'])}: " + "  \n".join(escape_text(part) for part in byline.splitlines()) + "  ")
    issue = article.get("issue", {})
    publication = issue.get("publication", "")
    citation = issue_label if publication and issue_label.startswith(publication) else ((publication + ", " if publication else "") + issue_label)
    if issue.get("issue_number") is not None:
        citation += f", {labels['issue_number']} {issue['issue_number']}"
    lines.append(f"{escape_text(labels['issue'])}: {escape_text(citation)}  ")
    pages = article.get("source_pages", {})
    if pages:
        if pages.get("pages"):
            value = ", ".join(map(str, pages["pages"]))
        else:
            first, last = pages.get("start"), pages.get("end")
            value = str(first) if first == last else f"{first}–{last}"
        lines.append(f"{escape_text(labels['pages'])}: {value}  ")
    lines.append(f"{escape_text(labels['canonical'])}: <{canonical_url}>")
    # PDF filenames are attribution, never guessed public download URLs.
    source = issue.get("source", {})
    if source.get("filename"):
        lines.append(f"{escape_text(labels['source'])}: {escape_text(source['filename'])}")
    if article.get("issue_url"):
        lines.append(f"[{escape_text(issue_label)}](<{urljoin(canonical_url, article['issue_url'])}>)")
    lines.extend(["", html_to_markdown(article["html"], canonical_url).rstrip()])
    credits = []
    for image in article.get("images", []):
        credit = image.get("credit")
        if credit:
            link = urljoin(canonical_url, image["public_path"])
            label = image.get("alt") or image["public_path"].rsplit("/", 1)[-1]
            credits.append(f"- [{escape_text(label)}](<{link}>): {escape_text(credit)}")
    if credits:
        lines.extend(["", "## " + escape_text(labels["credits"]), "", *credits])
    return "\n".join(lines).rstrip() + "\n"
