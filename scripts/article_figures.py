"""Presentation-only image groups, inserted without reserializing source HTML.

The reader receives static galleries even with JavaScript disabled. Source image
tags, captions and article text remain unchanged. Reviewed opening images, split
artwork and paragraph pairs can move as complete original figures; all other
changes are layout wrapper/class insertions. The source model and Markdown are
untouched.
"""
from __future__ import annotations

from article_editorial import arrange_editorial, validate_editorial_rules
from collections import defaultdict
from dataclasses import dataclass, field
from html import unescape
from html.parser import HTMLParser
import json
import math
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
        wrapping = rule.get('wrap', [])
        if not isinstance(wrapping, list):
            raise ValueError(f'Invalid prose wrapping rules: {identity}')
        names.extend(wrapping)
        verse_quotes = rule.get('verse_quote', [])
        if not isinstance(verse_quotes, list):
            raise ValueError(f'Invalid verse quotation rules: {identity}')
        names.extend(verse_quotes)
        paragraph_pair = rule.get('paragraph_pair', [])
        if 'paragraph_pair' in rule:
            if (not isinstance(paragraph_pair, list) or len(paragraph_pair) != 2 or
                    any(not isinstance(item, dict) or set(item) != {'image', 'side'} or
                        item['side'] not in ('start', 'end') for item in paragraph_pair)):
                raise ValueError(f'Invalid paragraph image pair: {identity}')
            names.extend(item['image'] for item in paragraph_pair)
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
        contour = rule.get('opening_contour')
        if 'opening_contour' in rule:
            if not isinstance(contour, dict) or set(contour) != {'image', 'width', 'height', 'text_start', 'edges'}:
                raise ValueError(f'Invalid opening contour rules: {identity}')
            if isinstance(contour['image'], str) and contour['image'] in {'.', '..'}:
                raise ValueError(f'Image layout rules require image basenames: {identity}')
            width, height, start = (contour[key] for key in ('width', 'height', 'text_start'))
            if (any(type(value) not in (int, float) or not math.isfinite(value)
                    for value in (width, height, start)) or
                    width <= 0 or height <= 0 or not 0 <= start < height):
                raise ValueError(f'Invalid opening contour dimensions: {identity}')
            edges = contour['edges']
            if (not isinstance(edges, list) or len(edges) < 2 or
                    any(not isinstance(row, list) or len(row) != 3 or
                        any(type(value) not in (int, float) or not math.isfinite(value) for value in row) or
                        not 0 <= row[0] <= height or not 0 <= row[1] <= width / 2 <= row[2] <= width
                        for row in edges) or
                    edges[0] != [0, width / 2, width / 2] or edges[-1] != [height, 0, width] or
                    any(left[0] >= right[0] for left, right in zip(edges, edges[1:]))):
                raise ValueError(f'Invalid opening contour edges: {identity}')
            names.append(contour['image'])
        opening_order = rule.get('opening_order', [])
        if not isinstance(opening_order, list) or len(opening_order) == 1:
            raise ValueError(f'Invalid opening image order: {identity}')
        if any(not isinstance(name, str) or not name or name in {'.', '..'} or '/' in name or '\\' in name
               for name in [*names, *opening_order]):
            raise ValueError(f'Image layout rules require image basenames: {identity}')
        if len(opening_order) != len(set(opening_order)):
            raise ValueError(f'Repeated opening image: {identity}')
        if contour and contour['image'] in opening_order:
            raise ValueError(f'Conflicting opening contour order: {identity}')
        if any(item['image'] in opening_order for item in paragraph_pair):
            raise ValueError(f'Conflicting paragraph pair order: {identity}')
        positions = rule.get('paragraph_positions', {})
        if (not isinstance(positions, dict) or
                any(not isinstance(name, str) or not name or name in {'.', '..'} or
                    '/' in name or '\\' in name or type(position) is not int or position < 1
                    for name, position in positions.items()) or
                len(set(positions.values())) != len(positions)):
            raise ValueError(f'Invalid paragraph image positions: {identity}')
        if (set(positions) & set(opening_order) or
                set(positions) & {item['image'] for item in paragraph_pair} or
                (contour and contour['image'] in positions)):
            raise ValueError(f'Conflicting paragraph image positions: {identity}')
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
        validate_editorial_rules(identity, rule)
    return rules


def _empty_gap(source):
    return not re.sub(r'<!--.*?-->', '', source, flags=re.S).strip()


def _article_parent(figure):
    """Only article prose and explicit verse containers acquire reader layouts."""
    node = figure.parent
    while node and (node.tag == 'section' or
                    (node.tag in {'div', 'blockquote'} and _verse_class(node))):
        node = node.parent
    return node if node and node.tag == 'article' and node.attrs.get('data-article-id') else None


def _verse_class(node):
    return bool({'poem', 'lyrics'} & set((node.attrs.get('class') or '').split()))


def _arrange_verse_figures(source):
    """Keep stanzas in a continuous column beside their own illustration.

    Insert wrappers only: neither source bytes nor reading order are changed.
    A closing illustration can accompany the final stanza, but groups never
    cross a heading, ordinary paragraph, gallery, or unrelated container.
    """
    parsed = FigureElements(source)
    insertions = defaultdict(list)

    def is_verse(node):
        if '<img' in source[node.opening_end:node.end].lower():
            return False
        if node.tag == 'p':
            return (_verse_class(node) or _verse_class(node.parent) or
                    sum(child.tag == 'br' for child in node.children) >= 2)
        return node.tag in {'div', 'section', 'blockquote', 'ol'} and _verse_class(node)

    def is_figure(node):
        return (node.tag == 'figure' and _article_parent(node) and
                len(_images(node)) == 1 and
                'article-figure--standalone' not in node.attrs.get('class', '').split())

    def wrap(figure, stanzas):
        nodes = sorted([figure, *stanzas], key=lambda node: node.start)
        insertions[nodes[0].start].append('<div class="article-verse-row">')
        insertions[stanzas[0].start].append('<div class="article-verse-text">')
        insertions[stanzas[-1].end].append('</div>')
        insertions[nodes[-1].end].append('</div>')

    def reviewed_epigraph(quote, figure, parent):
        # A reviewed opening quotation keeps its printed lines and original
        # order. It never turns unrelated quotations into prose floats.
        if (parent.tag != 'article' or quote.tag != 'blockquote' or
                not is_figure(figure) or
                'article-figure--native-verse' not in figure.attrs.get('class', '').split() or
                len(quote.children) != 1 or quote.children[0].tag != 'p' or
                len(figure.children) != 1 or 'hidden' in parent.attrs or
                not quote.closing_start or not quote.children[0].closing_start or
                not _empty_gap(source[parent.opening_end:quote.start]) or
                not _empty_gap(source[quote.end:figure.start])):
            return False
        descendants = [node for node in parsed.elements if quote.start <= node.start < quote.end]
        if (any('hidden' in node.attrs for node in [*descendants, figure, *_images(figure)]) or
                any(node.tag not in {'blockquote', 'p', 'br', 'em', 'strong', 'b', 'i', 'u',
                                     's', 'span', 'a', 'small', 'sup', 'sub', 'mark'}
                    for node in descendants) or
                sum(node.tag == 'br' for node in descendants) < 2 or
                sum(node.tag == 'p' for node in descendants) != 1 or
                sum(node.tag == 'blockquote' for node in descendants) != 1):
            return False
        paragraph = quote.children[0]
        return (bool(unescape(re.sub(r'<[^>]*>', '', source[paragraph.opening_end:paragraph.closing_start])).strip()) and
                _empty_gap(source[quote.opening_end:paragraph.start]) and
                _empty_gap(source[paragraph.end:quote.closing_start]))

    for parent in parsed.elements:
        if not (parent.tag == 'article' or parent.tag == 'section' or
                (parent.tag in {'div', 'blockquote'} and _verse_class(parent))):
            continue
        children, i = parent.children, 0
        while i < len(children):
            node = children[i]
            if i == 0 and len(children) > 1 and reviewed_epigraph(node, children[1], parent):
                wrap(children[1], [node])
                i = 2
                continue
            if is_figure(node):
                end = i + 1
                while end < len(children) and is_verse(children[end]) and _empty_gap(
                        source[children[end - 1].end:children[end].start]):
                    end += 1
                if end > i + 1:
                    # Leave the last stanza with a closing image, in source order.
                    if (end < len(children) and is_figure(children[end]) and
                            end == len(children) - 1 and end > i + 2):
                        end -= 1
                    wrap(node, children[i + 1:end])
                    i = end
                    continue
            if is_verse(node):
                end = i + 1
                while end < len(children) and is_verse(children[end]) and _empty_gap(
                        source[children[end - 1].end:children[end].start]):
                    end += 1
                if (end == len(children) - 1 and is_figure(children[end]) and
                        _empty_gap(source[children[end - 1].end:children[end].start])):
                    wrap(children[end], children[i:end])
                    i = end + 1
                    continue
            i += 1
    for offset in sorted(insertions, reverse=True):
        source = source[:offset] + ''.join(insertions[offset]) + source[offset:]
    return source


def _images(figure):
    return [node for node in figure.children if node.tag == 'img']


def _names(figure):
    return [image.attrs.get('src', '').rsplit('/', 1)[-1] for image in _images(figure)]


def _contour_paragraph(source, parsed, article, figure, contour):
    """A reviewed contour contains only its original opening figure and prose."""
    if (figure.parent is not article or len(article.children) < 2 or
            article.children[0] is not figure or len(figure.children) != 1 or
            figure.children[0].tag != 'img' or not figure.closing_start or
            _verse_class(article)):
        return None
    image, paragraph = figure.children[0], article.children[1]
    if (paragraph.tag != 'p' or not paragraph.closing_start or _verse_class(paragraph) or
            any('hidden' in node.attrs for node in (figure, image, paragraph)) or
            _names(figure) != [contour['image']]):
        return None
    if any(not _empty_gap(gap) for gap in (
            source[article.opening_end:figure.start], source[figure.opening_end:image.start],
            source[image.end:figure.closing_start], source[figure.end:paragraph.start])):
        return None
    article_images = [node for node in parsed.elements if node.tag == 'img' and article.start < node.start < article.end]
    if sum(node.attrs.get('src', '').rsplit('/', 1)[-1] == contour['image'] for node in article_images) != 1:
        return None
    descendants = [node for node in parsed.elements if paragraph.start < node.start < paragraph.end]
    if any(node.tag in {'br', 'img', 'picture', 'svg', 'figure', 'table', 'ul', 'ol',
                        'blockquote', 'div', 'section', 'script', 'style'} or _verse_class(node)
           for node in descendants):
        return None
    text = re.sub(r'<!--.*?-->|<[^>]*>', '', source[paragraph.opening_end:paragraph.closing_start], flags=re.S)
    return paragraph if unescape(text).strip() else None


def _contour_opening(contour):
    """Keep physical alpha edges in each half-width float's coordinate system."""
    width, height = contour['width'], contour['height']
    left = [(0, 0), *((edge * 200 / width, y * 100 / height) for y, edge, _ in contour['edges'])]
    right = [(100, 0), *(((edge * 2 / width - 1) * 100, y * 100 / height)
                         for y, _, edge in contour['edges'])]
    def polygon(points):
        return 'polygon(' + ', '.join(f'{x:.8f}% {y:.8f}%' for x, y in points) + ')'

    style = (f'--article-contour-max-width:{width:g}px;'
             f'--article-contour-left:{polygon(left)};--article-contour-right:{polygon(right)}')
    return (f'<div class="article-contour-opening" data-contour-width="{width:g}" '
            f'data-contour-height="{height:g}" data-contour-start="{contour["text_start"]:g}" style="{style}">')


def _order_reviewed_opening_figures(source, rules):
    """Reorder only a complete, reviewed image run before the opening paragraph."""
    parsed = FigureElements(source)
    changes = []
    for article in parsed.elements:
        if article.tag != 'article':
            continue
        order = rules.get(article.attrs.get('data-article-id'), {}).get('opening_order', [])
        if not order or len(article.children) <= len(order):
            continue
        figures = article.children[:len(order)]
        paragraph = article.children[len(order)]
        if paragraph.tag != 'p' or not _empty_gap(source[article.opening_end:figures[0].start]):
            continue
        # Captions, loose text, intervening content and additional opening images
        # make a changed source ambiguous. Keep its existing arrangement instead.
        if any(figure.tag != 'figure' or not figure.closing_start or len(figure.children) != 1 or
               figure.children[0].tag != 'img' or
               not _empty_gap(source[figure.opening_end:figure.children[0].start]) or
               not _empty_gap(source[figure.children[0].end:figure.closing_start]) for figure in figures):
            continue
        if any(not _empty_gap(source[left.end:right.start])
               for left, right in zip(figures, [*figures[1:], paragraph])):
            continue
        names = [_names(figure)[0] for figure in figures]
        article_names = [node.attrs.get('src', '').rsplit('/', 1)[-1] for node in parsed.elements
                         if node.tag == 'img' and article.start < node.start < article.end]
        if set(names) != set(order) or any(article_names.count(name) != 1 for name in order):
            continue
        if names == order:
            continue
        originals = {name: source[figure.start:figure.end] for name, figure in zip(names, figures)}
        replacement = originals[order[0]]
        for index in range(1, len(figures)):
            replacement += source[figures[index - 1].end:figures[index].start] + originals[order[index]]
        changes.append((figures[0].start, figures[-1].end, replacement))
    for start, end, replacement in sorted(changes, reverse=True):
        source = source[:start] + replacement + source[end:]
    return source


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


def _distribute_reviewed_paragraph_pair(source, rules):
    """Move one complete image pair beside its two original neighbouring paragraphs."""
    parsed = FigureElements(source)
    changes, applied = [], {}
    inline = {'a', 'abbr', 'b', 'cite', 'code', 'em', 'i', 'mark', 'q', 's',
              'small', 'span', 'strong', 'sub', 'sup', 'u'}

    def descendants(node):
        return [child for child in parsed.elements if node.start < child.start < node.end]

    def ordinary_paragraph(node):
        if (node.tag != 'p' or not node.closing_start or 'hidden' in node.attrs or _verse_class(node) or
                any(child.tag not in inline or 'hidden' in child.attrs or _verse_class(child)
                    for child in descendants(node))):
            return False
        text = re.sub(r'<!--.*?-->|<[^>]*>', '', source[node.opening_end:node.closing_start], flags=re.S)
        return bool(unescape(text).strip())

    def complete_figure(node):
        if (node.tag != 'figure' or not node.closing_start or len(_images(node)) != 1 or
                sorted(child.tag for child in node.children) not in (['img'], ['figcaption', 'img']) or
                'hidden' in node.attrs or _verse_class(node)):
            return False
        image = _images(node)[0]
        if any('hidden' in child.attrs or _verse_class(child) or
               (child is not image and child.tag not in inline | {'figcaption', 'br'})
               for child in descendants(node)):
            return False
        points = [node.opening_end, *(child.end for child in node.children)]
        ends = [*(child.start for child in node.children), node.closing_start]
        return all(_empty_gap(source[start:end]) for start, end in zip(points, ends))

    for article in parsed.elements:
        if article.tag != 'article' or _verse_class(article) or 'hidden' in article.attrs:
            continue
        identity = article.attrs.get('data-article-id')
        pair = rules.get(identity, {}).get('paragraph_pair', [])
        if not pair:
            continue
        names = [item['image'] for item in pair]
        article_images = [node.attrs.get('src', '').rsplit('/', 1)[-1] for node in descendants(article)
                          if node.tag == 'img']
        if any(article_images.count(name) != 1 for name in names):
            continue
        children = article.children
        for position in range(1, len(children) - 2):
            before, first, second, after = children[position - 1:position + 3]
            if (not ordinary_paragraph(before) or not ordinary_paragraph(after) or
                    not complete_figure(first) or not complete_figure(second) or
                    {_names(first)[0], _names(second)[0]} != set(names) or
                    (position > 1 and children[position - 2].tag == 'figure')):
                continue
            nodes = [before, first, second, after]
            gaps = [source[left.end:right.start] for left, right in zip(nodes, nodes[1:])]
            if not all(_empty_gap(gap) for gap in gaps):
                continue
            figures = {_names(node)[0]: source[node.start:node.end] for node in (first, second)}
            replacement = (figures[names[0]] + gaps[0] + source[before.start:before.end] + gaps[1] +
                           figures[names[1]] + gaps[2] + source[after.start:after.end])
            changes.append((before.start, after.end, replacement))
            applied[identity] = {item['image']: item['side'] for item in pair}
            break
    for start, end, replacement in sorted(changes, reverse=True):
        source = source[:start] + replacement + source[end:]
    return source, applied


def _position_reviewed_paragraph_figures(source, rules):
    """Move reviewed complete illustrations before a direct article paragraph.

    Image and paragraph contents are copied verbatim. Repeated assets, missing
    paragraphs, nested figures and unexpected figure contents stay in place.
    Positions count only direct article paragraphs, never epigraphs or captions.
    """
    parsed = FigureElements(source)
    changes = []
    for article in parsed.elements:
        if article.tag != 'article' or 'hidden' in article.attrs:
            continue
        positions = rules.get(article.attrs.get('data-article-id'), {}).get('paragraph_positions', {})
        paragraphs = [node for node in article.children if node.tag == 'p']
        for name, position in positions.items():
            if position > len(paragraphs):
                continue
            target = paragraphs[position - 1]
            matches = [node for node in parsed.elements if node.tag == 'img' and
                       article.start < node.start < article.end and
                       node.attrs.get('src', '').rsplit('/', 1)[-1] == name]
            if len(matches) != 1:
                continue
            image = matches[0]
            figure = image.parent
            if (figure.tag != 'figure' or figure.parent is not article or
                    len(_images(figure)) != 1 or not figure.closing_start or
                    not target.closing_start or 'hidden' in target.attrs or
                    any('hidden' in node.attrs for node in (figure, image)) or
                    any(node.tag not in {'img', 'figcaption'} for node in figure.children)):
                continue
            figure_nodes = figure.children
            boundaries = [(figure.opening_end, figure_nodes[0].start),
                          *((left.end, right.start) for left, right in zip(figure_nodes, figure_nodes[1:])),
                          (figure_nodes[-1].end, figure.closing_start)]
            if not all(_empty_gap(source[start:end]) for start, end in boundaries):
                continue
            figure_index = article.children.index(figure)
            next_node = article.children[figure_index + 1] if figure_index + 1 < len(article.children) else None
            if next_node is target:
                continue
            following = next_node.start if next_node else article.closing_start
            gap = source[figure.end:following]
            if not _empty_gap(gap):
                continue
            changes.extend([(figure.start, following, ''),
                            (target.start, target.start, source[figure.start:figure.end] + gap)])
    for start, end, replacement in sorted(changes, reverse=True):
        source = source[:start] + replacement + source[end:]
    return source


def arrange_article_figures(source, rules=None):
    """Group adjacent photographs and reviewed compositions in the reader only.

    Rules use permanent article UUIDs and exact ordered image basenames. Reviewed
    pairs stay distinct from ordinary responsive galleries. Generic grouping
    never crosses prose or structural boundaries. Reviewed opening figures,
    split panels and paragraph pairs can move without changing prose or captions.
    """
    if '<figure' not in source.lower():
        return source
    rules = rules or {}
    paragraph_sides = {}
    if rules:
        source = _order_reviewed_opening_figures(source, rules)
        source = _reunite_reviewed_pairs(source, rules)
        source = _position_reviewed_paragraph_figures(source, rules)
        source, paragraph_sides = _distribute_reviewed_paragraph_pair(source, rules)
    source = arrange_editorial(source, rules, FigureElements)
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
        contour = rule.get('opening_contour')
        paragraph = _contour_paragraph(source, parsed, article, figure, contour) if contour else None
        if paragraph:
            insertions[figure.start].append(_contour_opening(contour))
            insertions[paragraph.start].append(''.join(
                f'<span class="article-contour-edge article-contour-edge--{side}" aria-hidden="true"></span>'
                for side in ('left', 'right')))
            insertions[paragraph.end].append('</div>')
            mark(figure, 'article-figure--standalone')
            continue
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
        if len(names) == 1 and names[0] in rule.get('wrap', []):
            mark(figure, 'article-figure--reviewed-wrap')
        if len(names) == 1 and names[0] in rule.get('verse_quote', []):
            occurrences = sum(node.tag == 'img' and article.start < node.start < article.end and
                              node.attrs.get('src', '').rsplit('/', 1)[-1] == names[0]
                              for node in parsed.elements)
            if occurrences == 1:
                mark(figure, 'article-figure--native-verse')
        side = paragraph_sides.get(article.attrs['data-article-id'], {}).get(names[0]) if len(names) == 1 else None
        if side:
            mark(figure, f'article-figure--reviewed-{side}')
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
    return _arrange_verse_figures(source)
