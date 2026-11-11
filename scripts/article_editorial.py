"""Reviewed reader compositions. Original content nodes are copied, never rewritten."""
from __future__ import annotations

from html import unescape
import re

KINDS = {'source-note': 1, 'verse-pictures': 2, 'quote-frame': 2,
         'quote-portrait': 1, 'prose-pair': 2, 'reduced-prose': 1, 'poem-heading': 1}


def validate_editorial_rules(identity, rule):
    """Reject ambiguous registry entries before generating reader markup."""
    names = rule.get('list_flow', [])
    if not isinstance(names, list):
        raise ValueError(f'Invalid list flow rule: {identity}')
    positions = rule.get('list_positions', {})
    if (not isinstance(positions, dict) or
            any(type(number) is not int or number < 1 for number in positions.values()) or
            len(set(positions.values())) != len(positions)):
        raise ValueError(f'Invalid list image positions: {identity}')
    names = [*names, *positions]
    enlargements = rule.get('enlarged_standalone', {})
    if not isinstance(enlargements, dict):
        raise ValueError(f'Invalid standalone enlargement: {identity}')
    for name, size in enlargements.items():
        if (name not in rule.get('standalone', []) or not isinstance(size, dict) or
                set(size) != {'width', 'source_size'} or
                not isinstance(size['source_size'], list) or len(size['source_size']) != 2 or
                any(type(value) is not int or value <= 0 for value in size['source_size']) or
                type(size['width']) is not int or not size['source_size'][0] < size['width'] <= size['source_size'][0] * 2):
            raise ValueError(f'Invalid standalone enlargement: {identity}')
    names.extend(enlargements)
    gallery = rule.get('paragraph_gallery')
    continuous = rule.get('continuous_verse')
    protected = {*rule.get('standalone', []), *rule.get('wrap', []),
                 *rule.get('verse_quote', []), *rule.get('paragraph_positions', {}),
                 *rule.get('list_positions', {}), *rule.get('opening_order', []),
                 *rule.get('transparent_padding', {})}
    protected.update(name for pair in rule.get('paired', []) for name in pair)
    for setting, keys in [(gallery, {'images', 'widths', 'after_paragraph'}),
                          (continuous, {'images'})]:
        if setting is None:
            continue
        if (not isinstance(setting, dict) or set(setting) != keys or
                not isinstance(setting['images'], list) or len(setting['images']) < 2 or
                any(not isinstance(name, str) for name in setting['images']) or
                len(set(setting['images'])) != len(setting['images']) or
                protected.intersection(setting['images'])):
            raise ValueError(f'Invalid reviewed image composition: {identity}')
        names.extend(setting['images'])
        protected.update(setting['images'])
    if gallery is not None and (len(gallery['images']) != 2 or
            type(gallery['after_paragraph']) is not int or gallery['after_paragraph'] < 1 or
            not isinstance(gallery['widths'], list) or len(gallery['widths']) != 2 or
            any(type(width) is not int or width <= 0 for width in gallery['widths'])):
        raise ValueError(f'Invalid paragraph gallery: {identity}')
    if continuous is not None and (gallery is not None or rule.get('editorial') is not None):
        raise ValueError(f'Conflicting continuous verse: {identity}')
    if set(positions).intersection(rule.get('paragraph_positions', {})):
        raise ValueError(f'Conflicting list image positions: {identity}')
    composition = rule.get('editorial')
    if composition is not None:
        if not isinstance(composition, dict) or composition.get('kind') not in KINDS:
            raise ValueError(f'Invalid editorial composition: {identity}')
        kind, images = composition['kind'], composition.get('images')
        keys = {'kind', 'images'} | ({'width', 'source_size'} if kind == 'reduced-prose' else set())
        if (set(composition) != keys or not isinstance(images, list) or
                len(images) != KINDS[kind] or any(not isinstance(name, str) for name in images) or
                len(set(images)) != len(images)):
            raise ValueError(f'Invalid editorial images: {identity}')
        names = [*names, *images]
        protected = {*rule.get('standalone', []), *rule.get('wrap', []), *rule.get('verse_quote', []),
                     *rule.get('transparent_padding', {}), *rule.get('opening_order', [])}
        protected.update(name for pair in rule.get('paired', []) for name in pair)
        if protected.intersection(images):
            raise ValueError(f'Conflicting editorial composition: {identity}')
        if kind == 'reduced-prose':
            size, width = composition['source_size'], composition['width']
            if (not isinstance(size, list) or len(size) != 2 or
                    any(type(value) is not int or value <= 0 for value in size) or
                    type(width) is not int or not 100 <= width < size[0]):
                raise ValueError(f'Invalid reviewed display size: {identity}')
    if any(not isinstance(name, str) or not name or name in {'.', '..'} or
           '/' in name or '\\' in name for name in names):
        raise ValueError(f'Editorial rules require image basenames: {identity}')


def arrange_editorial(source, rules, parser):
    """Apply only complete, unique, direct-child compositions with safe boundaries.

    Passing the existing offset parser avoids a second HTML serialization policy.
    Missing, hidden, repeated or changed structures retain their original layout.
    """
    parsed = parser(source)
    changes = []
    empty = lambda text: not re.sub(r'<!--.*?-->', '', text, flags=re.S).strip()
    raw = lambda node: source[node.start:node.end]
    verse = lambda node: bool({'poem', 'lyrics'} & set(node.attrs.get('class', '').split()))

    def safe(node):
        return node.end and node.closing_start and not any(
            'hidden' in child.attrs or child.attrs.get('aria-hidden') == 'true'
            for child in parsed.elements if node.start <= child.start < node.end)

    def paragraph(node):
        return (node.tag == 'p' and safe(node) and not verse(node) and
                not re.search(r'<(?:br|img|figure|table|ul|ol)\b', raw(node), re.I))

    def contiguous(nodes):
        return all(empty(source[a.end:b.start]) for a, b in zip(nodes, nodes[1:]))

    for article in [node for node in parsed.elements if node.tag == 'article']:
        rule = rules.get(article.attrs.get('data-article-id'), {})
        if not safe(article):
            continue
        children = article.children
        images = [node for node in parsed.elements if node.tag == 'img' and article.start < node.start < article.end]

        def find_figure(name):
            matches = [node for node in images if node.attrs.get('src', '').rsplit('/', 1)[-1] == name]
            if len(matches) != 1:
                return None
            image, figure = matches[0], matches[0].parent
            if (figure.tag != 'figure' or figure.parent is not article or not safe(figure) or
                    [node.tag for node in figure.children] not in (['img'], ['img', 'figcaption'])):
                return None
            return figure

        continuous = rule.get('continuous_verse')
        if continuous and 'data-reader-continuous-verse' not in article.attrs:
            expected = [find_figure(name) for name in continuous['images']]
            actual = [node for node in children if node.tag == 'figure']
            if (None not in expected and actual == expected and len(images) == len(expected) and
                    all(len(figure.children) == 1 for figure in actual) and
                    all(safe(node) and (node in actual or (node.tag == 'p' and verse(node))) for node in children) and
                    contiguous(children) and empty(source[article.opening_end:children[0].start]) and
                    empty(source[children[-1].end:article.closing_start])):
                changes.append((article.opening_end - 1, article.opening_end - 1,
                                ' data-reader-continuous-verse=""'))

        for name, setting in rule.get('enlarged_standalone', {}).items():
            figure = find_figure(name)
            if figure and 'data-reader-enlarge' not in figure.attrs:
                width, height = setting['source_size']
                changes.append((figure.opening_end - 1, figure.opening_end - 1,
                                f' data-reader-enlarge="{setting["width"]}"'
                                f' data-source-width="{width}" data-source-height="{height}"'))

        for name, number in rule.get('list_positions', {}).items():
            figure = find_figure(name)
            lists = [node for node in children if node.tag in {'ul', 'ol'}]
            if not figure or number > len(lists):
                continue
            listing = lists[number - 1]
            if not safe(listing) or figure.end > listing.start:
                continue
            next_index = children.index(figure) + 1
            next_node = children[next_index] if next_index < len(children) else None
            if next_node is listing or not next_node or not empty(source[figure.end:next_node.start]):
                continue
            changes.extend([(figure.start, next_node.start, ''),
                            (listing.start, listing.start, raw(figure) + '\n  ')])

        gallery = rule.get('paragraph_gallery')
        if gallery:
            panels = [find_figure(name) for name in gallery['images']]
            paragraphs = [node for node in children if paragraph(node)]
            if None not in panels and gallery['after_paragraph'] <= len(paragraphs):
                target = paragraphs[gallery['after_paragraph'] - 1]
                # Do not detach content from an intervening nested container or
                # silently move unnamed figures as part of this reviewed pair.
                if all(contiguous([node, children[children.index(node) + 1]])
                       if children.index(node) + 1 < len(children) else
                       empty(source[node.end:article.closing_start]) for node in panels):
                    artwork = ''.join(f'<div class="article-native-panel" style="--panel-width:{width}px">{raw(node)}</div>'
                                      for node, width in zip(panels, gallery['widths']))
                    block = f'\n  <div class="article-gallery article-gallery--native">{artwork}</div>'
                    changes.extend((node.start, node.end, '') for node in panels)
                    changes.append((target.end, target.end, block))

        for name in rule.get('list_flow', []):
            figure = find_figure(name)
            if not figure:
                continue
            position = children.index(figure) + 1
            if position < len(children) and paragraph(children[position]):
                position += 1
            if position < len(children) and children[position].tag in {'ul', 'ol'}:
                listing = children[position]
                if safe(listing) and 'data-reader-list-flow' not in listing.attrs:
                    changes.append((listing.opening_end - 1, listing.opening_end - 1, ' data-reader-list-flow=""'))

        setting = rule.get('editorial')
        if not setting:
            continue
        figures = [find_figure(name) for name in setting['images']]
        if any(figure is None for figure in figures):
            continue
        kind = setting['kind']
        first = figures[0]
        index = children.index(first)
        if children[index:index + len(figures)] != figures:
            continue
        following = children[index + len(figures):]
        if not following:
            continue
        target = following[0]
        if not contiguous([*figures, target]):
            continue
        art = source[first.start:figures[-1].end]
        replacement = None
        end = target.end
        if kind == 'source-note':
            if index or len(following) < 3 or any(node.tag != 'p' or not safe(node) for node in following[:3]):
                continue
            notes = following[:2]
            if (not paragraph(following[2]) or not contiguous(following[:3]) or
                    any(not re.search(r'<br\b', raw(note), re.I) or not re.search(r'<em\b', raw(note), re.I)
                        for note in notes)):
                continue
            note = source[notes[0].start:notes[-1].end]
            replacement = f'<aside class="article-source-note">{note}</aside>\n  {art}\n  '
            end = following[2].start
        elif kind in {'verse-pictures', 'poem-heading'}:
            if index or not verse(target) or not safe(target):
                continue
            if kind == 'poem-heading':
                replacement = f'<div class="article-poem-heading">{art}\n  {raw(target)}</div>'
            else:
                replacement = (f'<div class="article-editorial-verse"><div class="article-editorial-art">{art}</div>'
                               f'<div class="article-editorial-text">{raw(target)}</div></div>')
        elif kind == 'quote-portrait':
            if index or len(following) < 2 or not paragraph(target):
                continue
            quote = following[1]
            if quote.tag != 'blockquote' or not safe(quote) or not contiguous([target, quote]):
                continue
            replacement = (f'{raw(target)}\n  <div class="article-editorial-verse article-editorial-verse--native">'
                           f'<div class="article-editorial-art">{art}</div>'
                           f'<div class="article-editorial-text">{raw(quote)}</div></div>')
            end = quote.end
        elif kind == 'quote-frame':
            if (index or target.tag != 'blockquote' or not safe(target) or
                    any(len(figure.children) != 1 for figure in figures)):
                continue
            replacement = (f'<div class="article-quote-frame">{raw(figures[0])}'
                           '<span class="article-quote-edge article-quote-edge--left" aria-hidden="true"></span>'
                           '<span class="article-quote-edge article-quote-edge--right" aria-hidden="true"></span>'
                           f'{raw(target)}{raw(figures[1])}</div>')
        elif kind in {'prose-pair', 'reduced-prose'}:
            if not paragraph(target):
                continue
            attrs = ''
            if kind == 'reduced-prose':
                width, height = setting['source_size']
                attrs = (f' data-display-width="{setting["width"]}" data-source-width="{width}"'
                         f' data-source-height="{height}" style="--editorial-art-width:{setting["width"]}px"')
            replacement = (f'<div class="article-editorial-prose"{attrs}><div class="article-editorial-art'
                           f'{" article-editorial-art--pair" if kind == "prose-pair" else ""}">{art}</div>'
                           f'{raw(target)}</div>')
        if replacement is not None:
            changes.append((first.start, end, replacement))
    for start, end, replacement in sorted(changes, reverse=True):
        source = source[:start] + replacement + source[end:]
    return source
