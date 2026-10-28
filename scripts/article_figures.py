"""Presentation-only image groups, inserted without reserializing source HTML.

The reader receives static galleries even with JavaScript disabled. Source image
tags, captions and article text remain unchanged. Reviewed caption-free split
artwork can be reunited by moving its exact figure bytes; all other changes are
layout wrapper/class insertions. The source model and Markdown are untouched.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from html.parser import HTMLParser
import json
from pathlib import Path
import re

VOID = set('area base br col embed hr img input link meta param source track wbr'.split())
ATTRIBUTES = re.compile(r'''([^\s=/>]+)(?:\s*=\s*("[^"]*"|'[^']*'|[^\s>]+))?''')


@dataclass(eq=False)
class Element:
    tag: str
    attrs: dict
    start: int
    opening_end: int
    parent: Element | None
    end: int = 0
    closing_start: int = 0
    children: list = field(default_factory=list)


class FigureElements(HTMLParser):
    """A small structural index whose offsets refer to the original characters."""
    def __init__(self, source):
        super().__init__(convert_charrefs=False)
        self.source = source
        self.lines = [0, *(match.end() for match in re.finditer('\n', source))]
        self.elements, self.stack = [], []
        self.feed(source)
        self.close()

    def position(self):
        line, column = self.getpos()
        return self.lines[line - 1] + column

    def handle_starttag(self, tag, attrs):
        start = self.position()
        parent = self.stack[-1] if self.stack else None
        node = Element(tag, dict(attrs), start, start + len(self.get_starttag_text()), parent)
        self.elements.append(node)
        if parent:
            parent.children.append(node)
        if tag in VOID:
            node.end = node.opening_end
        else:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID:
            self.stack.pop().end = self.position() + len(self.get_starttag_text())

    def handle_endtag(self, tag):
        if self.stack and self.stack[-1].tag == tag:
            node = self.stack.pop()
            node.closing_start = self.position()
            node.end = self.source.find('>', self.position()) + 1


def load_figure_rules(path):
    """Load the reviewed exceptions; invalid or missing policy fails the build."""
    document = json.loads(Path(path).read_text(encoding='utf-8'))
    if not isinstance(document, dict) or document.get('version') != 1 or not isinstance(document.get('articles'), dict):
        raise ValueError('Invalid article image layout rules')
    rules = document['articles']
    for identity, rule in rules.items():
        if not isinstance(identity, str) or not isinstance(rule, dict):
            raise ValueError('Invalid article image layout entry')
        standalone, paired = rule.get('standalone', []), rule.get('paired', [])
        names = list(standalone) if isinstance(standalone, list) else [None]
        if not isinstance(paired, list):
            raise ValueError(f'Invalid paired image rules: {identity}')
        for group in paired:
            if not isinstance(group, list) or len(group) != 2:
                raise ValueError(f'Invalid paired image group: {identity}')
            names.extend(group)
        padding = rule.get('transparent_padding', {})
        if not isinstance(padding, dict):
            raise ValueError(f'Invalid transparent padding rules: {identity}')
        names.extend(padding)
        for bounds in padding.values():
            if (not isinstance(bounds, dict) or
                set(bounds) != {'width', 'height', 'top', 'right', 'bottom', 'left'} or
                any(type(value) is not int or value < 0 for value in bounds.values()) or
                bounds['width'] <= bounds['left'] + bounds['right'] or
                bounds['height'] <= bounds['top'] + bounds['bottom']):
                raise ValueError(f'Invalid transparent padding dimensions: {identity}')
        if any(not isinstance(name, str) or not name or '/' in name or '\\' in name for name in names):
            raise ValueError(f'Image layout rules require image basenames: {identity}')
        if len(names) != len(set(names)):
            raise ValueError(f'Conflicting or repeated image layout rules: {identity}')
        dimensions = rule.get('dimensions')
        if dimensions is not None:
            paired_names = {name for pair in paired for name in pair}
            if not isinstance(dimensions, dict) or set(dimensions) != paired_names:
                raise ValueError(f'Image dimensions must describe every paired panel: {identity}')
            if any(not isinstance(size, list) or len(size) != 2 or
                   any(type(value) is not int or value <= 0 for value in size)
                   for size in dimensions.values()):
                raise ValueError(f'Invalid paired image dimensions: {identity}')
    return rules


def _empty_gap(source):
    return not re.sub(r'<!--.*?-->', '', source, flags=re.S).strip()


def _article_parent(figure):
    """Only article/section prose may acquire galleries or text wrapping."""
    node = figure.parent
    while node and node.tag == 'section':
        node = node.parent
    return node if node and node.tag == 'article' and node.attrs.get('data-article-id') else None


def _images(figure):
    return [node for node in figure.children if node.tag == 'img']


def _names(figure):
    return [image.attrs.get('src', '').rsplit('/', 1)[-1] for image in _images(figure)]


def _reunite_reviewed_pairs(source, rules):
    """Move only unambiguous, caption-free panels from reviewed compositions."""
    parsed = FigureElements(source)
    changes, used = [], set()
    for article in parsed.elements:
        if article.tag != 'article':
            continue
        pairs = rules.get(article.attrs.get('data-article-id'), {}).get('paired', [])
        if not pairs:
            continue
        figures = [node for node in parsed.elements if node.tag == 'figure' and _article_parent(node) is article]
        article_images = [node for node in parsed.elements if node.tag == 'img' and article.start < node.start < article.end]
        for pair in pairs:
            if any(sum(image.attrs.get('src', '').rsplit('/', 1)[-1] == name for image in article_images) != 1 for name in pair):
                continue
            matches = [[node for node in figures if name in _names(node)] for name in pair]
            if any(len(nodes) != 1 for nodes in matches):
                continue
            panels = [nodes[0] for nodes in matches]
            first = panels[0]
            if len(set(panels)) != len(panels) or any(panel in used for panel in panels):
                continue
            if any(panel.parent is not first.parent or len(panel.children) != 1 or
                   panel.children[0].tag != 'img' or not panel.closing_start or
                   not _empty_gap(source[panel.opening_end:panel.children[0].start]) or
                   not _empty_gap(source[panel.children[0].end:panel.closing_start]) for panel in panels):
                continue
            if any(left.end > right.start for left, right in zip(panels, panels[1:])):
                continue
            if any(first.end <= image.start < panels[-1].start and image not in [panel.children[0] for panel in panels] for image in article_images):
                continue
            if all(_empty_gap(source[left.end:right.start]) for left, right in zip(panels, panels[1:])):
                continue
            used.update(panels)
            changes.append((first.end, first.end, ''.join('\n' + source[panel.start:panel.end] for panel in panels[1:])))
            changes.extend((panel.start, panel.end, '') for panel in panels[1:])
    for start, end, replacement in sorted(changes, reverse=True):
        source = source[:start] + replacement + source[end:]
    return source


def arrange_article_figures(source, rules=None):
    """Group adjacent photographs and reviewed compositions in the reader only.

    Rules use permanent article UUIDs and exact ordered image basenames. Reviewed
    pairs stay distinct from ordinary responsive galleries. Generic grouping
    never crosses prose or structural boundaries. Reviewed caption-free panels
    can move together within the same parent without rearranging article text.
    """
    if '<figure' not in source.lower():
        return source
    rules = rules or {}
    if rules:
        source = _reunite_reviewed_pairs(source, rules)
    parsed = FigureElements(source)
    insertions, classes = defaultdict(list), defaultdict(list)

    def mark(node, name):
        if name not in (node.attrs.get('class') or '').split() and name not in classes[node]:
            classes[node].append(name)

    def wrap(nodes, class_name, rule=None, names=None):
        style = ''
        if rule and names and all(name in rule.get('dimensions', {}) for name in names):
            sizes = [rule['dimensions'][name] for name in names]
            height = min(384, *(natural_height for _, natural_height in sizes))
            ratios = [natural_width / natural_height for natural_width, natural_height in sizes]
            columns = ' '.join(f'{ratio:.6f}fr' for ratio in ratios)
            width = sum(ratio * height for ratio in ratios)
            style = f' style="--article-pair-columns:{columns};--article-pair-width:{width:.6f}px"'
        insertions[nodes[0].start].append(f'<div class="{class_name}"{style}>')
        insertions[nodes[-1].end].append('</div>')

    figures = [node for node in parsed.elements if node.tag == 'figure' and node.end and _article_parent(node)]
    eligible, parents, rules_by_parent = set(), set(), {}
    for figure in figures:
        article = _article_parent(figure)
        rule = rules.get(article.attrs['data-article-id'], {})
        pairs = rule.get('paired', [])
        names = _names(figure)
        if not names:
            continue
        mark(article, 'article-figures')
        mark(figure, 'article-figure')
        if figure.parent.tag == 'section':
            mark(figure.parent, 'article-figure-section')
        # Only explicitly reviewed, single-image figures lose transparent canvas
        # padding. Keep the original img tag/bytes and caption outside the viewport.
        padding = rule.get('transparent_padding', {}).get(names[0]) if len(names) == 1 else None
        if padding:
            image = _images(figure)[0]
            width = padding['width'] - padding['left'] - padding['right']
            height = padding['height'] - padding['top'] - padding['bottom']
            style = (f'--article-image-width:{width}px;--article-image-ratio:{width}/{height};'
                     f'--article-image-scale:{padding["width"] / width * 100:.8f}%;'
                     f'--article-image-top:{-padding["top"] / height * 100:.8f}%;'
                     f'--article-image-left:{-padding["left"] / width * 100:.8f}%')
            insertions[image.start].append(f'<span class="article-image-window" style="{style}">')
            insertions[image.end].append('</span>')
            mark(figure, 'article-figure--standalone')
            continue
        standalone = any(name in rule.get('standalone', []) for name in names)
        if standalone:
            mark(figure, 'article-figure--standalone')
            continue
        images = _images(figure)
        # A shared caption stays in its figure, outside the image row. Text or
        # structural elements between images are deliberate source boundaries.
        if len(images) > 1 and all(_empty_gap(source[left.end:right.start]) for left, right in zip(images, images[1:])):
            paired = names in pairs
            wrap(images, 'article-gallery__images' + (' article-gallery--paired' if paired else ''),
                 rule if paired else None, names if paired else None)
        if len(images) == 1:
            eligible.add(figure)
            parents.add(figure.parent)
            rules_by_parent[figure.parent] = rule

    for parent in sorted(parents, key=lambda node: node.start):
        rule = rules_by_parent[parent]
        pairs = rule.get('paired', [])
        pair_members = {name for pair in pairs for name in pair}
        run = []

        def flush():
            pending = []
            position = 0
            while position < len(run):
                pair = next((pair for pair in pairs if [_names(node)[0] for node in run[position:position + len(pair)]] == pair), None)
                if pair:
                    if len(pending) > 1:
                        wrap(pending, 'article-gallery')
                    pending = []
                    wrap(run[position:position + len(pair)], 'article-gallery article-gallery--paired', rule, pair)
                    position += len(pair)
                    continue
                node = run[position]
                # A removed or changed panel must not become a false composition
                # with its new neighbour. Repeated decorative images stay apart.
                repeated = any(previous is not node and _names(previous) == _names(node) for previous in run)
                if _names(node)[0] in pair_members or repeated:
                    mark(node, 'article-figure--standalone')
                    if len(pending) > 1:
                        wrap(pending, 'article-gallery')
                    pending = []
                else:
                    pending.append(node)
                position += 1
            if len(pending) > 1:
                wrap(pending, 'article-gallery')
            run.clear()

        for node in parent.children:
            if node not in eligible or (run and not _empty_gap(source[run[-1].end:node.start])):
                flush()
            if node in eligible:
                run.append(node)
        flush()

    for node, additions in classes.items():
        if not additions:
            continue
        opening = source[node.start:node.opening_end]
        class_attr = next((match for match in ATTRIBUTES.finditer(opening[1:-1]) if match[1].lower() == 'class'), None)
        if class_attr and class_attr[2]:
            value = class_attr[2]
            quoted = value[0] in {'"', "'"}
            offset = node.start + 1 + class_attr.start(2) + int(quoted)
            separator = ' ' if quoted else '&#32;'
            insertions[offset].append(separator.join(additions) + separator)
        else:
            offset = node.opening_end - (2 if opening.endswith('/>') else 1)
            insertions[offset].append(f' class="{" ".join(additions)}"')

    for offset in sorted(insertions, reverse=True):
        source = source[:offset] + ''.join(insertions[offset]) + source[offset:]
    return source
