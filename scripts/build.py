#!/usr/bin/env python3
"""Build the public reading archive. Python standard library, no client framework."""
from __future__ import annotations
import argparse
import gzip
import hashlib
import html
import json
import math
import re
import shutil
import subprocess
from collections import defaultdict
from pathlib import Path
from urllib.parse import quote
from xml.etree import ElementTree as ET

from content import load_content, ordered_issues
from authors import build_author_index, DETAIL_FIELDS
from publisher import issue_pdf_links, PUBLISHER_URL
from routes import initialize_routes
from markdown import generate_markdown
from scripture import Scripture
from i18n import load_locales, validate_locales, format_issue_date

ROOT = Path(__file__).resolve().parents[1]
ORIGIN = 'https://remnant.truechristian.church'
BRAND = 'The Heartbeat of the Remnant'
PAGE_SIZE = 24

def esc(value):
    return html.escape(str(value if value is not None else ''), quote=True)

def json_script(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':')).replace('<', '\\u003c').replace('&', '\\u0026')

def git_revision(path):
    try:
        return subprocess.check_output(['git', '-C', str(path), 'rev-parse', 'HEAD'], text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        return None

def issue_date(issue, locale):
    return format_issue_date(issue, locale)

def author_of(article):
    byline = article.get('byline') or {}
    if isinstance(byline, str):
        return byline
    return byline.get('raw') or ', '.join(a['name'] for a in byline.get('authors', []) if a.get('name'))

def article_categories(article):
    categories = article.get('categories') or {}
    return [categories.get('primary')] + categories.get('additional', [])

def source_pages(article):
    pages = article.get('source_pages') or {}
    if pages.get('pages'):
        return ', '.join(str(page) for page in pages['pages'])
    if not pages.get('start'):
        return ''
    return str(pages['start']) + (f"–{pages['end']}" if pages.get('end') and pages['end'] != pages['start'] else '')

class Site:
    def __init__(self, model, locales, routes, theme, output, covers, scripture=None):
        self.scripture = scripture
        self.scripture_ui = json.loads((ROOT/"data/scripture-ui.json").read_text()) if scripture else {}
        self.model, self.locales, self.routes = model, locales, routes
        self.theme, self.output, self.covers = theme, output, covers
        self.issues = ordered_issues(model)
        self.issue_map = {i['id']: i for i in self.issues}
        self.issue_pdfs = issue_pdf_links(self.issues)
        self.categories = model['categories']
        self.category_map = {c['id']: c for c in self.categories}
        self.topic_map = {t['id']: t for t in model['topics']}
        self.rank = {issue['id']: index for index, issue in enumerate(self.issues)}
        self.articles = {tag: sorted(model['articles'].get(tag, []), key=lambda a: (self.rank[a['issue_id']], a.get('sequence', 0))) for tag in locales}
        self.article_map = {tag: {a['id']: a for a in articles} for tag, articles in self.articles.items()}
        self.authors = build_author_index(model, aliases=routes.get('author_aliases'))
        self.author_map = {author['id']: author for author in self.authors}
        self.article_authors = defaultdict(list)
        for author in self.authors:
            for identity in author['article_ids']:
                self.article_authors[identity].append(author)
        self.author_articles = {tag: {author['id']: [] for author in self.authors} for tag in locales}
        for tag in locales:
            for article in self.articles[tag]:
                for author in self.article_authors[article['id']]:
                    self.author_articles[tag][author['id']].append(article)
        self.footer_template = (theme / 'src/html/site-footer.html').read_text()
        self.sitemap = []
        self.html_sizes = []
        self.search_sizes = {}
        self.written = set()

    def ui(self, tag, key, **kwargs):
        return self.locales[tag]['ui'][key].format(**kwargs)

    def issue_identity(self, tag, issue):
        parts = [issue_date(issue, self.locales[tag])]
        for key, field in [('volume', 'volume_number'), ('number', 'issue_number')]:
            if issue.get(field) is not None:
                parts.append(f"{self.ui(tag,key)} {issue[field]}")
        return ' · '.join(parts)

    def category(self, tag, uuid):
        return self.locales[tag]['categories'][uuid]

    def category_url(self, tag, uuid):
        return self.routes['categories'][tag][uuid]

    def issue_url(self, tag, uuid):
        return self.routes['issues'][tag][uuid]

    def author_url(self, tag, identity):
        return self.routes['authors'][tag][identity]

    def localized_paths(self, kind, uuid=None, suffix=''):
        if kind == 'author':
            return {tag: self.author_url(tag, uuid) for tag in self.locales}
        if kind == 'article':
            return {tag: self.routes['articles'][tag][uuid] for tag in self.locales}
        if kind in ('category', 'issue'):
            return {tag: self.routes[kind + ('ies' if kind == 'category' else 's')][tag][uuid] for tag in self.locales} if kind == 'issue' else {tag: self.category_url(tag, uuid) for tag in self.locales}
        return {tag: f'/{tag}/{suffix}' for tag in self.locales}

    def canonical_article_links(self, fragment):
        """Keep exported notice text intact while linking to readable originals."""
        def replacement(match):
            path = self.routes['articles']['en'].get(match.group('identity'))
            return f'href={match.group("quote")}{esc(path)}{match.group("quote")}' if path else match.group(0)
        return re.sub(r'''href=(?P<quote>["'])/en/articles/(?P<identity>[0-9a-f-]{36})/(?P=quote)''', replacement, fragment)

    def write(self, route, content):
        if route in self.written:
            raise ValueError(f'Duplicate output route: {route}')
        if not route.startswith('/') or '..' in route.split('/'):
            raise ValueError(f'Unsafe route: {route}')
        target = self.output / route.lstrip('/')
        if route.endswith('/'):
            target = target / 'index.html'
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding='utf-8')
        self.written.add(route)
        if target.suffix == '.html':
            self.html_sizes.append((route, len(content.encode())))

    def footer(self, tag):
        content = self.footer_template
        for label, translated in self.locales[tag]['chrome'].items():
            content = content.replace(f'>{html.escape(label)}<', f'>{esc(translated)}<')
            content = content.replace(f'aria-label="{esc(label)}"', f'aria-label="{esc(translated)}"')
        return content

    def shell(self, tag, route, title, body, *, description='', paths=None, indexed=True, current='', extra_config=None, article=None):
        locale = self.locales[tag]
        t = lambda key, **kw: esc(self.ui(tag, key, **kw))
        paths = paths or {code: f'/{code}/' for code in self.locales}
        equivalents = paths
        if article:
            equivalents = {code: self.article_map[code][article['id']]['url'] for code in self.locales if article['id'] in self.article_map[code]}
        alternate = ''.join(f'<link rel="alternate" hreflang="{esc(code)}" href="{ORIGIN}{esc(path)}">' for code, path in equivalents.items()) if indexed else ''
        if indexed:
            self.sitemap.append((route, equivalents))
        nav = ''.join(f'<li><a href="/{tag}/{suffix}"{(" aria-current=\"page\"" if current == key else "")}>{t(key)}</a></li>' for key, suffix in [('home',''),('articles','articles/'),('categories','categories/'),('issues','issues/'),('authors','authors/'),('search','search/')])
        languages = ''.join(f'<option value="{esc(paths[code])}" data-locale="{esc(code)}" lang="{esc(code)}" dir="{esc(info["meta"]["dir"])}"{(" selected" if code == tag else "")}>{esc(info["meta"]["native_name"])}</option>' for code, info in self.locales.items())
        nojs_languages = ' · '.join(f'<a href="{esc(paths[code])}" lang="{esc(code)}">{esc(info["meta"]["native_name"])}</a>' for code, info in self.locales.items())
        appearance = ''.join(f'<option value="{mode}">{t(mode)}</option>' for mode in ['system','light','dark'])
        client_keys = ('copied','copy_fallback','copy_error','play','pause','search_error','results_count','no_results','searching','search_hint','prev','next','search')
        config = {'locale': tag, 'ui': {key:locale['ui'][key] for key in client_keys}, 'searchIndex': f'/{tag}/search-index.json', **(extra_config or {})}
        article_assets = '<link rel="stylesheet" href="/assets/article-figures.css"><script type="module" src="/assets/article-figures.js"></script>' if article else ''
        scripture_assets = ''
        if article and self.scripture:
            config['scriptureUi'] = self.scripture_ui[tag]
            scripture_assets = '<link rel="stylesheet" href="/assets/scripture-popovers.css"><script type="module" src="/assets/scripture-popovers.js"></script>'
        script_font = {'ar':'Noto+Sans+Arabic','ur':'Noto+Sans+Arabic','he':'Noto+Sans+Hebrew','hi':'Noto+Sans+Devanagari','bn':'Noto+Sans+Bengali','zh-Hans':'Noto+Sans+SC','ko':'Noto+Sans+KR'}.get(tag)
        fonts = 'family=Montserrat:wght@400;500;600&family=Raleway:wght@400;500;600' + (f'&family={script_font}:wght@400;500;600' if script_font else '') + '&display=swap'
        doc_title = f'{title} · {BRAND}' if title != BRAND else BRAND
        structured = ''
        if article:
            issue = self.issue_map[article['issue_id']]
            data = {'@context':'https://schema.org','@type':'Article','headline':title,'inLanguage':tag,'url':ORIGIN+route,'isPartOf':{'@type':'PublicationIssue','name':f"{issue['publication']} · {issue_date(issue,locale)}",'url':ORIGIN+self.issue_url(tag,issue['id'])}}
            recorded_byline = article.get('source_metadata', article).get('byline')
            if self.article_authors[article['id']]:
                data['author'] = [{'@type':'Person', 'name':author['name'], 'url':ORIGIN+self.author_url(tag,author['id'])} for author in self.article_authors[article['id']]]
            elif author_of(article) and not (isinstance(recorded_byline, dict) and recorded_byline.get('authors')):
                # A role-only structured credit does not identify a Person.
                data['author'] = {'@type':'Person','name':author_of(article)}
            structured = f'<script type="application/ld+json">{json_script(data)}</script>'
        return f'''<!doctype html>
<html lang="{esc(tag)}" dir="{esc(locale['meta']['dir'])}"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(doc_title)}</title><meta name="description" content="{esc(description or self.ui(tag,'intro'))}">
<meta name="color-scheme" content="light dark"><meta name="theme-color" content="#00cadb">
<link rel="canonical" href="{ORIGIN}{esc(route)}">{alternate}
{('<meta name="robots" content="noindex,follow">' if not indexed else '')}
<meta property="og:type" content="{('article' if article else 'website')}"><meta property="og:title" content="{esc(title)}"><meta property="og:description" content="{esc(description or self.ui(tag,'intro'))}"><meta property="og:url" content="{ORIGIN}{esc(route)}"><meta property="og:site_name" content="{BRAND}">
<link rel="icon" href="/assets/favicons/favicon.ico"><link rel="alternate" type="application/rss+xml" title="{esc(BRAND)} — {esc(locale['meta']['native_name'])}" href="/{tag}/feed.xml">
<script src="/assets/preferences.js"></script>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin><link rel="stylesheet" href="https://fonts.googleapis.com/css2?{esc(fonts)}">
<link rel="stylesheet" href="/assets/theme.css"><link rel="stylesheet" href="/assets/site.css">
<script defer src="/assets/theme.js"></script><script type="module" src="/assets/site.js"></script>{article_assets}{scripture_assets}{structured}
</head><body id="top">
<a class="skip-link" href="#main">{t('skip_content')}</a>
<header class="tcc-site-header tm-header" data-tcc-global-header><div class="tcc-header__container tcc-container">
<a class="tcc-header__brand uk-logo" href="https://truechristian.church/"><img src="/assets/brand/logo.jpg" width="288" height="77" alt="A True Christian Church"></a>
<button class="tcc-header__toggle" type="button" aria-controls="tcc-primary-navigation" aria-expanded="false"><span class="tcc-visually-hidden">{t('menu')}</span><span aria-hidden="true">☰</span></button>
<nav id="tcc-primary-navigation" class="tcc-header__navigation" aria-label="{t('main_navigation')}"><button class="tcc-header__close" type="button" aria-label="{t('close')}"><span aria-hidden="true">×</span></button><ul class="tcc-header__menu uk-navbar-nav">{nav}</ul></nav>
<button class="tcc-header__scrim" type="button" tabindex="-1" aria-label="{t('close')}"></button></div></header>
<div class="reader-bar"><div class="tcc-container reader-bar__inner"><a class="reader-brand" href="/{tag}/"><span class="brand-dot" aria-hidden="true"></span>REMNANT <span>{t('magazine')}</span></a><div class="reader-settings">
<label class="select-control"><span>{t('language')}</span><select data-language-select aria-label="{t('language')}">{languages}</select></label>
<label class="select-control theme-control"><span>{t('theme')}</span><select data-theme-select aria-label="{t('theme')}">{appearance}</select></label></div></div></div>
<noscript><div class="nojs-languages tcc-container">{nojs_languages}</div></noscript>
<main id="main" tabindex="-1">{body}</main>
<section class="archive-end"><div class="tcc-container archive-end__inner"><div><p class="eyebrow">{t('about_archive')}</p><p>{t('intro')}</p></div><a class="text-link" href="/{tag}/feed.xml">{t('subscribe_rss')} <span aria-hidden="true"><svg class="nav-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M5 19 19 5M5 5h14v14"/></svg></span></a></div></section>
{self.footer(tag)}
<script type="application/json" id="page-config">{json_script(config)}</script>
</body></html>'''

    def page(self, tag, route, title, body, **kwargs):
        self.write(route, self.shell(tag, route, title, body, **kwargs))

    def breadcrumb(self, tag, parts):
        return f'<nav class="breadcrumbs" aria-label="{esc(self.ui(tag,"breadcrumbs"))}"><a href="/{tag}/">{esc(self.ui(tag,"home"))}</a>' + ''.join(f'<span aria-hidden="true">/</span><a href="{esc(url)}">{esc(label)}</a>' if url else f'<span aria-hidden="true">/</span><span aria-current="page">{esc(label)}</span>' for label,url in parts) + '</nav>'

    def title(self, tag, article):
        return article.get('title') or self.ui(tag, 'untitled_article')

    def byline_html(self, tag, article):
        """Link recorded names without rewriting the publication's raw byline."""
        raw = author_of(article)
        authors = self.article_authors[article['id']]
        if not authors:
            return esc(raw)
        names = {name: author for author in authors
                 for name in [author['name'], *author['source_names']]}
        pattern = re.compile(r'(?<!\w)(' + '|'.join(re.escape(name) for name in sorted(names, key=len, reverse=True)) + r')(?!\w)')
        pieces, seen, end = [], set(), 0
        def link(author, text=None):
            return f'<a class="author-link" href="{esc(self.author_url(tag,author["id"]))}"><bdi>{esc(author["name"] if text is None else text)}</bdi></a>'
        for match in pattern.finditer(raw):
            author = names[match.group()]
            credit = esc(match.group()) if author['id'] in seen else link(author, match.group())
            pieces.extend([esc(raw[end:match.start()]), credit])
            seen.add(author['id'])
            end = match.end()
        pieces.append(esc(raw[end:]))
        remaining = [link(author) for author in authors if author['id'] not in seen]
        if remaining:
            pieces.append(f' <span class="byline-authors">({esc(self.ui(tag,"author"))}: '+', '.join(remaining)+')</span>')
        return ''.join(pieces)

    def author_counts(self, tag, author):
        total = self.ui(tag, 'author_total_articles', count=len(author['article_ids']))
        available = self.ui(tag, 'author_available_articles', count=len(self.author_articles[tag][author['id']]))
        return f'<div class="author-counts"><span>{esc(total)}</span><span>{esc(available)}</span></div>'

    def author_details(self, tag, author):
        if not author['details']:
            return ''
        fields = ''.join(f'<div><dt>{esc(self.ui(tag,"author_"+field))}</dt><dd>' +
                         ' · '.join(f'<bdi>{esc(value)}</bdi>' for value in author['details'][field]) + '</dd></div>'
                         for field in DETAIL_FIELDS if field in author['details'])
        return f'<div class="author-details"><p class="author-details__label">{esc(self.ui(tag,"author_recorded_details"))}</p><dl>{fields}</dl></div>'

    def authors_page(self, tag):
        body = f'<section class="tcc-container page-section authors-page"><header class="page-heading"><p class="eyebrow">{esc(self.ui(tag,"author_count",count=len(self.authors)))}</p><h1>{esc(self.ui(tag,"authors"))}</h1><p>{esc(self.ui(tag,"authors_intro"))}</p></header>'
        if self.authors:
            body += '<div class="author-grid">'
            for author in self.authors:
                body += f'<article class="author-card"><h2><a class="author-name" href="{esc(self.author_url(tag,author["id"]))}"><bdi>{esc(author["name"])}</bdi></a></h2>{self.author_counts(tag,author)}{self.author_details(tag,author)}</article>'
            body += '</div>'
        else:
            body += f'<p class="empty-state">{esc(self.ui(tag,"no_authors"))}</p>'
        body += '</section>'
        self.page(tag,f'/{tag}/authors/',self.ui(tag,'authors'),body,description=self.ui(tag,'authors_intro'),paths=self.localized_paths('authors',suffix='authors/'),current='authors')

    def author_page(self, tag, author):
        articles = self.author_articles[tag][author['id']]
        base = self.author_url(tag,author['id'])
        pages = max(1,math.ceil(len(articles)/PAGE_SIZE))
        for number in range(1,pages+1):
            route = base if number == 1 else f'{base}page/{number}/'
            body = f'<section class="tcc-container page-section author-profile">{self.breadcrumb(tag,[(self.ui(tag,"authors"),f"/{tag}/authors/"),(author["name"],None)])}<header class="page-heading"><p class="eyebrow">{esc(self.ui(tag,"author"))}</p><h1><bdi>{esc(author["name"])}</bdi></h1>{self.author_counts(tag,author)}</header>{self.author_details(tag,author)}'
            if articles:
                body += f'<section class="author-works"><h2>{esc(self.ui(tag,"articles"))}</h2><ol class="author-articles">'
                for article in articles[(number-1)*PAGE_SIZE:number*PAGE_SIZE]:
                    category = article_categories(article)[0]
                    issue = self.issue_map[article['issue_id']]
                    body += f'<li><div class="card-meta"><a href="{esc(self.category_url(tag,category))}">{esc(self.category(tag,category)["name"])}</a><a href="{esc(self.issue_url(tag,issue["id"]))}">{esc(issue_date(issue,self.locales[tag]))}</a></div><h2><a href="{esc(article["url"])}">{esc(self.title(tag,article))}</a></h2><p>{esc(article.get("excerpt",""))}</p><p class="author-article-byline">{self.byline_html(tag,article)}</p></li>'
                body += '</ol></section>'
            else:
                body += f'<div class="empty-state"><div><p>{esc(self.ui(tag,"author_no_articles"))}</p><a class="button" href="{esc(self.author_url("en",author["id"]))}" hreflang="en">{esc(self.ui(tag,"author_read_english"))}</a></div></div>'
            if pages > 1:
                body += f'<nav class="pagination" aria-label="{esc(self.ui(tag,"articles"))}">'
                if number > 1:
                    previous = base if number == 2 else f'{base}page/{number-1}/'
                    body += f'<a rel="prev" href="{esc(previous)}">← {esc(self.ui(tag,"prev"))}</a>'
                body += f'<span>{number} / {pages}</span>'
                if number < pages:
                    body += f'<a rel="next" href="{esc(base)}page/{number+1}/">{esc(self.ui(tag,"next"))} →</a>'
                body += '</nav>'
            body += '</section>'
            description = author['name'] + ' · ' + self.ui(tag,'author_available_articles',count=len(articles))
            self.page(tag,route,author['name'],body,description=description,paths=self.localized_paths('author',author['id']),indexed=number==1,current='authors')

    def author_pagination_redirects(self):
        """Keep author identity when a paginated URL's language is changed."""
        for author in self.authors:
            identity = author['id']
            pages = {tag:max(1,math.ceil(len(self.author_articles[tag][identity])/PAGE_SIZE)) for tag in self.locales}
            tails = set()
            for tag in self.locales:
                entry = self.routes['registry']['authors'][tag][identity]
                for path in [self.author_url(tag,identity), *entry.get('history',[])]:
                    tails.add(path.split('/',2)[2])
            for number in range(2,max(pages.values())+1):
                for tag in self.locales:
                    base = self.author_url(tag,identity)
                    destination = f'{base}page/{number}/' if number <= pages[tag] else base
                    for tail in tails:
                        self.redirect(f'/{tag}/{tail}page/{number}/',destination)

    def image(self, article):
        images = article.get('images') or []
        return images[0] if images else None

    def image_markup(self, article, *, eager=False):
        image = self.image(article)
        if not image:
            return '<div class="article-image-placeholder" aria-hidden="true"><span>R</span></div>'
        src = image.get('public_path') or image.get('src')
        return f'<img src="{esc(src)}" alt="{esc(image.get("alt", ""))}" loading="{("eager" if eager else "lazy")}" decoding="async"{(" fetchpriority=\"high\"" if eager else "")}>'

    def card(self, tag, article, *, large=False, eager=False, number=None):
        category = self.category(tag, article_categories(article)[0])
        issue = self.issue_map[article['issue_id']]
        return f'''<article class="article-card{(' article-card--lead' if large else '')}"><a class="article-card__image" href="{esc(article['url'])}" tabindex="-1" aria-hidden="true">{self.image_markup(article,eager=eager)}</a><div class="article-card__body"><div class="card-meta"><span class="eyebrow">{esc(category['name'])}</span><span>{esc(issue_date(issue,self.locales[tag]))}</span></div><h{('2' if large else '3')}><a href="{esc(article['url'])}">{esc(self.title(tag,article))}</a></h{('2' if large else '3')}><p>{esc(article.get('excerpt',''))}</p><div class="card-bottom"><span>{self.byline_html(tag,article)}</span><a class="card-arrow" href="{esc(article['url'])}" aria-label="{esc(self.ui(tag,'read_article'))}: {esc(self.title(tag,article))}"><svg class="nav-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M5 19 19 5M5 5h14v14"/></svg></a></div></div></article>'''

    def issue_cover(self, tag, issue, *, small=False):
        cover = self.covers.get(issue['id'])
        if cover:
            path = cover['path']
            if not path.startswith('/covers/') or '..' in path.split('/') or not (ROOT / 'public' / path.lstrip('/')).is_file():
                raise ValueError(f'Invalid issue cover: {path}')
            return f'<img class="issue-cover__image" src="{esc(path)}" alt="{esc(cover["alt"].get(tag,cover["alt"]["en"]))}" loading="lazy">'
        date = issue.get('date') or {}
        return f'''<div class="issue-cover{(' issue-cover--small' if small else '')}" aria-label="{esc(issue_date(issue,self.locales[tag]))}"><span class="issue-cover__eyebrow">THE HEARTBEAT OF THE</span><span class="issue-cover__name">REMNANT</span><span class="issue-cover__rule"></span><span class="issue-cover__year">{esc(date.get('year',''))}</span><span class="issue-cover__date">{esc(issue_date(issue,self.locales[tag]))}</span><span class="issue-cover__bottom">{esc(self.ui(tag,'cover_placeholder'))}</span></div>'''

    def empty(self, tag, english_url, *, missing=False, article=None):
        available = ''
        if article:
            available = '<div class="available-languages">' + ''.join(f'<a class="button button--quiet" href="{esc(self.article_map[code][article["id"]]["url"])}" lang="{esc(code)}">{esc(info["meta"]["native_name"])}</a>' for code, info in self.locales.items() if article['id'] in self.article_map[code] and code != 'en') + '</div>'
        return f'''<div class="empty-state"><span class="empty-symbol" aria-hidden="true"><svg class="nav-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M5 19 19 5M5 5h14v14"/></svg></span><div><p class="eyebrow">{esc(self.locales[tag]['meta']['native_name'])}</p><h2>{esc(self.ui(tag,'no_articles_title'))}</h2><p>{esc(self.ui(tag,'missing_translation' if missing else 'coming_soon'))}</p><a class="button" href="{esc(english_url)}" hreflang="en">{esc(self.ui(tag,'read_english'))} <span aria-hidden="true"><svg class="nav-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M5 19 19 5M5 5h14v14"/></svg></span></a>{available}</div></div>'''

    def section_heading(self, tag, title, url=None, link='all_articles'):
        return f'<div class="section-heading"><h2>{esc(self.ui(tag,title))}</h2>' + (f'<a class="text-link" href="{esc(url)}">{esc(self.ui(tag,link))} <span aria-hidden="true"><svg class="nav-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M5 19 19 5M5 5h14v14"/></svg></span></a>' if url else '') + '</div>'

    def editor_remarks(self):
        """Resolve editorial identity in authoritative English, then join by UUID.

        Never guess from a translated title or substitute an unrelated first article.
        A section label can identify an editorial whose title is not 'From the Editor'.
        """
        pattern = re.compile(r"^(?:from the editor(?:[’']s desk)?[.:…]*|letter from the editor\b.*)$", re.I)
        result = {}
        for article in self.articles['en']:
            if any(pattern.fullmatch((article.get(key) or '').strip()) for key in ('section', 'title')):
                result.setdefault(article['issue_id'], article['id'])
        return result

    def home_feature(self, tag, issue, article=None, english_article=None):
        if article:
            lead = self.card(tag, article, large=True, eager=True)
        else:
            english_url = english_article['url'] if english_article else self.issue_url('en', issue['id'])
            lead = self.empty(tag, english_url, missing=bool(english_article and self.articles[tag]))
        return f'''<div class="home-lead__article">{lead}</div><aside class="featured-issue" data-issue-id="{esc(issue['id'])}"><a class="issue-cover-link" href="{esc(self.issue_url(tag,issue['id']))}">{self.issue_cover(tag,issue)}</a><div class="featured-issue__foot"><h2>{esc(issue_date(issue,self.locales[tag]))}</h2><a class="text-link" href="{esc(self.issue_url(tag,issue['id']))}">{esc(self.ui(tag,'read_issue'))} <span aria-hidden="true"><svg class="nav-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M5 19 19 5M5 5h14v14"/></svg></span></a></div></aside>'''

    def home(self, tag):
        t = lambda key,**kw: esc(self.ui(tag,key,**kw))
        articles = self.articles[tag]
        intro = f'''<section class="masthead tcc-container"><div class="masthead__top"><span class="eyebrow">{t('kicker')}</span><span class="edition-count">{t('issue_count',count=len(self.issues))} <span aria-hidden="true"> / </span> {t('article_count',count=len(articles))}</span></div><h1><span>THE HEARTBEAT OF THE</span>Remnant<span class="masthead__dot" aria-hidden="true">.</span></h1><div class="masthead__bottom"><p>{t('intro')}</p><form class="quick-search" action="/{tag}/search/"><label class="sr-only" for="home-q">{t('search')}</label><input id="home-q" name="q" type="search" placeholder="{t('search_placeholder')}"><button type="submit" aria-label="{t('search')}"><svg class="nav-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M5 19 19 5M5 5h14v14"/></svg></button></form></div></section>'''
        editors = self.editor_remarks()
        features = []
        for issue in self.issues:
            article_id = editors.get(issue['id'])
            if article_id and article_id in self.article_map[tag]:
                article = self.article_map[tag][article_id]
                features.append({'id': issue['id'], 'articleId': article_id,
                                 'html': self.home_feature(tag, issue, article)})
        # Empty/partially translated locales keep an honest same-issue English link.
        # Once an editorial is translated, only actual localized pairs are featured.
        if not features:
            for issue in self.issues:
                english = self.article_map['en'].get(editors.get(issue['id']))
                features.append({'id': issue['id'], 'articleId': None,
                                 'html': self.home_feature(tag, issue, english_article=english)})
        latest_articles = articles[:6]
        latest_ids = {a['id'] for a in latest_articles}
        editor_ids = {feature['articleId'] for feature in features if feature['articleId']}
        archive_articles = [a for a in articles if a['id'] not in latest_ids | editor_ids]
        archive_exclusions = latest_ids
        if len(archive_articles) < 3:
            # A tiny locale cannot fill both Latest and Archive independently.
            # Keep its real archive discoverable; the chronological section is
            # explicitly outside the rotating no-repeat guarantee.
            archive_exclusions = set()
            archive_articles = [a for a in articles if a['id'] not in editor_ids]
        cards = [{'id': a['id'], 'issueId': a['issue_id'], 'html': self.card(tag,a)} for a in archive_articles]
        categories = [{'id': c['id'], 'html': self.category_card(tag,c)} for c in self.categories]
        # A stable, useful no-JavaScript/offline fallback. The enhanced schedule is
        # computed by the browser from shared UTC slots, never from build time.
        stable = lambda rows: sorted(rows, key=lambda row: hashlib.sha256((tag + row['id']).encode()).hexdigest())
        feature = stable(features)[0] if features else None
        body = intro + f'<div class="home-update-control tcc-container" data-home-controls hidden><button type="button" class="text-button" data-home-pause aria-pressed="false">{t("pause_updates")}</button></div>'
        if feature:
            body += f'<section class="home-lead tcc-container" data-home-feature data-feature-id="{esc(feature["id"])}">{feature["html"]}</section>'
        elif not articles:
            body += f'<section class="tcc-container">{self.empty(tag,"/en/")}</section>'
        if cards:
            body += f'''<section class="archive-feature" data-home-archive-section><div class="tcc-container">{self.section_heading(tag,'featured_archive',f'/{tag}/articles/','browse_archive')}<div class="article-grid" data-home-archive>''' + ''.join(f'<div data-home-article-id="{esc(row["id"])}">{row["html"]}</div>' for row in stable(cards)[:3]) + '</div></div></section>'
        if latest_articles:
            body += f'<section class="page-section tcc-container" data-home-latest>{self.section_heading(tag,"latest_articles",f"/{tag}/articles/")}<div class="article-grid">' + ''.join(self.card(tag,a) for a in latest_articles) + '</div></section>'
        body += f'<section class="page-section tcc-container">{self.section_heading(tag,"browse_categories",f"/{tag}/categories/","all_categories")}<div class="category-grid" data-home-categories>' + ''.join(row['html'] for row in stable(categories)[:8]) + '</div></section>'
        data = {'schema': 1, 'locale': tag, 'features': features, 'articles': cards, 'categories': categories, 'latestIds': sorted(archive_exclusions)}
        value = json.dumps(data,ensure_ascii=False,separators=(',',':'))
        digest = hashlib.sha256(value.encode()).hexdigest()[:16]
        data_url = f'/{tag}/home-data.{digest}.json'
        self.write(data_url,value)
        (self.output / data_url.lstrip('/') ).with_suffix('.json.gz').write_bytes(gzip.compress(value.encode(),mtime=0))
        self.page(tag,f'/{tag}/',BRAND,body,paths=self.localized_paths('home'),current='home',extra_config={'homeData':data_url, 'homeUi':{'pause':self.ui(tag,'pause_updates'),'resume':self.ui(tag,'resume_updates')}})

    def category_card(self, tag, category):
        data = self.category(tag,category['id'])
        count = sum(category['id'] in article_categories(a) for a in self.articles[tag])
        return f'<a class="category-tile" href="{esc(self.category_url(tag,category["id"]))}"><div><span class="eyebrow">{esc(self.ui(tag,"article_count",count=count))}</span><h3>{esc(data["name"])}</h3><p>{esc(data["description"])}</p></div><span class="tile-arrow" aria-hidden="true"><svg class="nav-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M5 19 19 5M5 5h14v14"/></svg></span></a>'

    def listing(self, tag, *, category=None):
        t = lambda key,**kw: esc(self.ui(tag,key,**kw))
        if category:
            title = self.category(tag,category['id'])['name']; intro = self.category(tag,category['id'])['description']
            base = self.category_url(tag,category['id']); articles = [a for a in self.articles[tag] if category['id'] in article_categories(a)]
            paths = self.localized_paths('category',category['id']); english = self.category_url('en',category['id'])
        else:
            title = self.ui(tag,'all_articles'); intro = self.ui(tag,'archive_intro'); base = f'/{tag}/articles/'; articles = self.articles[tag]
            paths = self.localized_paths('articles',suffix='articles/'); english = '/en/articles/'
        pages = max(1,math.ceil(len(articles)/PAGE_SIZE))
        for number in range(1,pages+1):
            route = base if number == 1 else f'{base}page/{number}/'
            body = f'<div class="tcc-container page-section">{self.breadcrumb(tag,[(self.ui(tag,"categories"),f"/{tag}/categories/")] if category else [])}<header class="page-heading"><p class="eyebrow">{t("article_count",count=len(articles))}</p><h1>{esc(title)}</h1><p>{esc(intro)}</p></header>'
            if articles:
                body += '<div class="article-grid">' + ''.join(self.card(tag,a) for a in articles[(number-1)*PAGE_SIZE:number*PAGE_SIZE]) + '</div>'
            else:
                body += self.empty(tag,english)
            if pages > 1:
                body += '<nav class="pagination" aria-label="'+t('articles')+'">'
                if number > 1:
                    prev = base if number == 2 else f'{base}page/{number-1}/'
                    body += f'<a rel="prev" href="{esc(prev)}">← {t("prev")}</a>'
                body += f'<span>{number} / {pages}</span>'
                if number < pages:
                    body += f'<a rel="next" href="{esc(base)}page/{number+1}/">{t("next")} →</a>'
                body += '</nav>'
            body += '</div>'
            self.page(tag,route,title,body,description=intro,paths=paths,indexed=number==1,current='categories' if category else 'articles')

    def categories_page(self,tag):
        body = f'<section class="tcc-container page-section"><header class="page-heading"><p class="eyebrow">{esc(self.ui(tag,"browse_archive"))}</p><h1>{esc(self.ui(tag,"categories"))}</h1><p>{esc(self.ui(tag,"category_intro"))}</p></header><div class="category-grid">' + ''.join(self.category_card(tag,c) for c in self.categories) + '</div></section>'
        self.page(tag,f'/{tag}/categories/',self.ui(tag,'categories'),body,paths=self.localized_paths('categories',suffix='categories/'),current='categories')

    def issues_page(self,tag):
        body = f'<section class="tcc-container page-section"><header class="page-heading"><p class="eyebrow">{esc(self.ui(tag,"issue_count",count=len(self.issues)))}</p><h1>{esc(self.ui(tag,"issues"))}</h1><p>{esc(self.ui(tag,"issue_intro"))}</p></header><div class="issue-grid">'
        for issue in self.issues:
            count = sum(a['issue_id']==issue['id'] for a in self.articles[tag])
            body += f'<a class="issue-tile" href="{esc(self.issue_url(tag,issue["id"]))}">{self.issue_cover(tag,issue,small=True)}<h2>{esc(issue_date(issue,self.locales[tag]))}</h2><span>{esc(self.ui(tag,"article_count",count=count))}</span></a>'
        body += '</div></section>'
        self.page(tag,f'/{tag}/issues/',self.ui(tag,'issues'),body,paths=self.localized_paths('issues',suffix='issues/'),current='issues')

    def issue_page(self,tag,issue):
        articles = [a for a in self.articles[tag] if a['issue_id']==issue['id']]
        title = issue_date(issue,self.locales[tag])
        detail = ' · '.join(f'{self.ui(tag,key)} {issue[field]}' for key,field in [('volume','volume_number'),('number','issue_number')] if issue.get(field) is not None)
        pdf_url = self.issue_pdfs.get(issue['id'])
        publisher_links = f'<a href="{PUBLISHER_URL}" rel="external">{esc(self.ui(tag,"publisher"))}</a>'
        if pdf_url:
            # A cross-origin download is an ordinary direct PDF link; the HTML
            # download attribute cannot force browsers to save external files.
            publisher_links += f'<a href="{esc(pdf_url)}" rel="external" type="application/pdf">{esc(self.ui(tag,"download"))} <span class="file-type">(PDF)</span></a>'
        body = f'<div class="tcc-container page-section">{self.breadcrumb(tag,[(self.ui(tag,"issues"),f"/{tag}/issues/"),(title,None)])}<header class="issue-heading"><div>{self.issue_cover(tag,issue)}</div><div class="page-heading"><p class="eyebrow">{esc(self.ui(tag,"magazine"))}</p><h1>{esc(title)}</h1><p class="issue-publication">{esc(issue["publication"])}</p><p>{esc(detail)}</p><p>{esc(self.ui(tag,"issue_intro"))}</p><div class="issue-actions"><span class="count-pill">{esc(self.ui(tag,"article_count",count=len(articles)))}</span>{publisher_links}</div></div></header>'
        if not articles:
            body += self.empty(tag,self.issue_url('en',issue['id']))
        else:
            body += f'<div class="section-heading"><h2>{esc(self.ui(tag,"articles"))}</h2></div><ol class="issue-contents">'
            for article in articles:
                body += f'<li><span class="contents-number">{article.get("sequence", "")}</span><div><p class="eyebrow">{esc(self.category(tag,article_categories(article)[0])["name"])}</p><h2><a href="{esc(article["url"])}">{esc(self.title(tag,article))}</a></h2><p>{self.byline_html(tag,article)}</p></div><a class="contents-arrow" href="{esc(article["url"])}" aria-label="{esc(self.ui(tag,"read_article"))}: {esc(self.title(tag,article))}"><svg class="nav-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M5 19 19 5M5 5h14v14"/></svg></a></li>'
            body += '</ol>'
        body += '</div>'
        self.page(tag,self.issue_url(tag,issue['id']),title,body,paths=self.localized_paths('issue',issue['id']),current='issues')

    def article_page(self,tag,article):
        issue = self.issue_map[article['issue_id']]
        category = article_categories(article)[0]
        title = self.title(tag,article)
        minutes = max(1,round(len(article.get('text','').split())/200))
        byline = author_of(article)
        subtitle = f'<p class="article-subtitle">{esc(article["subtitle"])}</p>' if article.get('subtitle') else ''
        pages = source_pages(article)
        credit_items = []
        for image in article.get('images',[]):
            if image.get('credit') and image['credit'] not in article['html']:
                credit_items.append(f'<li>{esc(image.get("alt") or image.get("public_path"))} · {esc(image["credit"])}</li>')
        credit_html = '<ul class="image-credits">' + ''.join(credit_items) + '</ul>' if credit_items else ''
        display_html = self.canonical_article_links(self.scripture.render(tag,article) if self.scripture else article['html'])
        review_link = ''
        if tag != 'en':
            review_url = f"https://github.com/trueChristian/berean-translation/edit/main/content/{self.locales[tag]['meta']['code']}/articles/{article['id']}.html"
            review_link = f'<p class="translation-review"><a class="text-link" data-review-translation href="{esc(review_url)}">{esc(self.ui(tag,"review_translation"))}</a></p>'
        body = f'''<div class="tcc-container article-shell">{self.breadcrumb(tag,[(self.category(tag,category)['name'],self.category_url(tag,category)),(title,None)])}<header class="article-heading"><p class="eyebrow"><a href="{esc(self.category_url(tag,category))}">{esc(self.category(tag,category)['name'])}</a></p><h1>{esc(title)}</h1>{subtitle}<div class="article-byline"><span>{self.byline_html(tag,article)}</span><span>{esc(self.ui(tag,'minutes',count=minutes))}</span></div><a class="article-issue" href="{esc(self.issue_url(tag,issue['id']))}"><span class="mini-book" aria-hidden="true">R</span><span><small>{esc(self.ui(tag,'original_issue'))}</small>{esc(issue['publication'])} · {esc(self.issue_identity(tag,issue))}</span><span aria-hidden="true"><svg class="nav-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M5 19 19 5M5 5h14v14"/></svg></span></a></header><div class="reading-layout"><aside class="reading-rail"><p class="eyebrow">{esc(self.ui(tag,'magazine'))}</p><a href="{esc(self.issue_url(tag,issue['id']))}">{esc(issue_date(issue,self.locales[tag]))}</a><p>{esc(self.ui(tag,'source_pages'))} {esc(pages)}</p><a href="{esc(article['markdown_url'])}" download>{esc(self.ui(tag,'download_markdown'))} ↓</a></aside><div class="reading-main"><div class="prose">{display_html}</div>{credit_html}<section class="article-citation"><h2>{esc(self.ui(tag,'citation'))}</h2><p>{esc(title)}. {esc(byline)}. <a href="{esc(self.issue_url(tag,issue['id']))}">{esc(issue['publication'])}, {esc(self.issue_identity(tag,issue))}</a>{('. '+esc(self.ui(tag,'source_pages'))+' '+esc(pages) if pages else '')}.</p><p>{esc(issue.get('publisher',''))}</p></section><section class="reader-tools"><a class="button button--quiet" href="{esc(article['markdown_url'])}" download>{esc(self.ui(tag,'download_markdown'))} ↓</a><button class="button enhanced-only" type="button" data-copy-markdown="{esc(article['markdown_url'])}">{esc(self.ui(tag,'copy_markdown'))}</button><p role="status" id="copy-status"></p><div id="markdown-fallback" hidden><label for="markdown-text">{esc(self.ui(tag,'copy_fallback'))}</label><textarea id="markdown-text" readonly rows="12"></textarea></div></section>{review_link}</div></div></div>'''
        related = [a for a in self.articles[tag] if a['issue_id']==article['issue_id'] and a['id']!=article['id']][:3]
        if related:
            body += f'<section class="tcc-container page-section">{self.section_heading(tag,"related_articles",self.issue_url(tag,issue["id"]),"read_issue")}<div class="article-grid">'+''.join(self.card(tag,a) for a in related)+'</div></section>'
        self.page(tag,article['url'],title,body,description=article.get('excerpt',''),paths=self.localized_paths('article',article['id']),article=article)
        article['issue_url'] = ORIGIN+self.issue_url(tag,issue['id'])
        article['markdown_labels'] = {key:self.ui(tag,value) for key,value in {'language':'language','byline':'author','issue':'original_issue','pages':'source_pages','canonical':'read_article','source':'source_pdf','credits':'citation','untitled':'untitled_article','issue_number':'number'}.items()}
        markdown_article = {**article, 'html': self.canonical_article_links(article['html'])}
        markdown = generate_markdown(markdown_article, ORIGIN+article['url'], f"{issue['publication']}, {issue_date(issue,self.locales[tag])}")
        self.write(article['markdown_url'],markdown)

    def missing_article(self,tag,article):
        title = self.ui(tag,'no_articles_title')
        body = f'<section class="tcc-container page-section"><header class="page-heading"><p class="eyebrow">{esc(self.ui(tag,"available_languages"))}</p><h1>{esc(title)}</h1><p lang="en">{esc(article.get("title") or self.ui("en","untitled_article"))}</p></header>{self.empty(tag,article["url"],missing=True,article=article)}</section>'
        self.page(tag,self.routes['articles'][tag][article['id']],title,body,indexed=False,paths=self.localized_paths('article',article['id']))

    def search_page(self,tag):
        t = lambda key: esc(self.ui(tag,key))
        category_filters = {self.category_url(tag,c['id']).strip('/').split('/')[-1]: c['id'] for c in self.categories}
        issue_filters = {self.issue_url(tag,i['id']).strip('/').split('/')[-1]: i['id'] for i in self.issues}
        categories = ''.join(f'<option value="{esc(slug)}">{esc(self.category(tag,identity)["name"])}</option>' for slug, identity in category_filters.items())
        issues = ''.join(f'<option value="{esc(slug)}">{esc(issue_date(self.issue_map[identity],self.locales[tag]))}</option>' for slug, identity in issue_filters.items())
        body = f'''<section class="tcc-container page-section search-page"><header class="page-heading"><p class="eyebrow">{t('browse_archive')}</p><h1>{t('search')}</h1><p>{t('search_hint')}</p></header><form data-search-form action="/{tag}/search/" role="search"><div class="search-input"><label class="sr-only" for="search-q">{t('search')}</label><input type="search" id="search-q" name="q" placeholder="{t('search_placeholder')}" autocomplete="off"><button type="submit" class="button">{t('search')} <svg class="nav-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M5 19 19 5M5 5h14v14"/></svg></button></div><div class="search-filters"><label>{t('categories')}<select name="category"><option value="">{t('all_categories')}</option>{categories}</select></label><label>{t('issues')}<select name="issue"><option value="">{t('all_issue_filter')}</option>{issues}</select></label><button type="reset" class="text-button">{t('clear')}</button></div></form><p id="search-status" role="status" aria-live="polite">{t('search_hint')}</p><div id="search-results"></div><noscript><p><a href="/{tag}/articles/">{t('all_articles')}</a> · <a href="/{tag}/categories/">{t('browse_categories')}</a> · <a href="/{tag}/issues/">{t('all_issues')}</a> · <a href="/{tag}/authors/">{t('authors')}</a></p></noscript>'''
        if not self.articles[tag]:
            body += self.empty(tag,'/en/search/')
        body += '</section>'
        self.page(tag,f'/{tag}/search/',self.ui(tag,'search'),body,paths=self.localized_paths('search',suffix='search/'),current='search',extra_config={'categoryFilters': category_filters, 'issueFilters': issue_filters, 'authorLabel': self.ui(tag,'author')})
        records = []
        for article in self.articles[tag]:
            category_ids = article_categories(article)
            topics = [self.topic_map.get(topic,{}).get('name','') if isinstance(topic,str) else topic.get('name','') for topic in article.get('topics',[])]
            issue = self.issue_map[article['issue_id']]
            authors = [{'name':author['name'],'url':self.author_url(tag,author['id']),
                        'aliases':author['source_names']} for author in self.article_authors[article['id']]]
            records.append({'id':article['id'],'title':self.title(tag,article),'url':article['url'],'body':article['text'],'categories':[self.category(tag,c)['name'] for c in category_ids if c],'category_ids':category_ids,'topics':topics,'issue':' · '.join([issue['publication'],self.issue_identity(tag,issue),issue.get('publisher','')]),'issue_id':issue['id'],'author':author_of(article),'authors':authors})
        value = json.dumps(records,ensure_ascii=False,separators=(',',':'))
        self.write(f'/{tag}/search-index.json',value)
        (self.output/tag/'search-index.json.gz').write_bytes(gzip.compress(value.encode(),mtime=0))
        self.search_sizes[tag] = {'raw_bytes':len(value.encode()),'gzip_bytes':len(gzip.compress(value.encode(),mtime=0)),'articles':len(records)}

    def rss(self,tag):
        root = ET.Element('rss',version='2.0')
        channel = ET.SubElement(root,'channel')
        for key,value in [('title',BRAND),('link',ORIGIN+f'/{tag}/'),('description',self.ui(tag,'intro')),('language',tag)]:
            ET.SubElement(channel,key).text = value
        for article in self.articles[tag][:50]:
            item = ET.SubElement(channel,'item')
            ET.SubElement(item,'title').text = self.title(tag,article)
            ET.SubElement(item,'link').text = ORIGIN+article['url']
            ET.SubElement(item,'guid',isPermaLink='false').text = f'urn:remnant:{tag}:{article["id"]}'
            ET.SubElement(item,'description').text = article.get('excerpt','')
            ET.SubElement(item,'source',url=ORIGIN+self.issue_url(tag,article['issue_id'])).text = self.issue_map[article['issue_id']]['publication']+' · '+issue_date(self.issue_map[article['issue_id']],self.locales[tag])
        self.write(f'/{tag}/feed.xml',ET.tostring(root,encoding='unicode',xml_declaration=True))

    def redirect(self,path,destination):
        if path==destination or path in self.written:
            return
        self.write(path,f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>{BRAND}</title><link rel="canonical" href="{ORIGIN}{esc(destination)}"><meta name="robots" content="noindex,follow"><meta http-equiv="refresh" content="0;url={esc(destination)}"></head><body><a href="{esc(destination)}">{BRAND} →</a></body></html>')

    def category_pagination_redirects(self):
        """Retain category identity when a visitor changes a paginated prefix."""
        for category in self.categories:
            identity = category['id']
            pages = {tag: max(1,math.ceil(sum(identity in article_categories(article) for article in self.articles[tag])/PAGE_SIZE)) for tag in self.locales}
            tails = set()
            for tag in self.locales:
                entry = self.routes['registry']['categories'][tag][identity]
                for path in [self.category_url(tag,identity), *entry.get('history',[])]:
                    tail = path.split('/',2)[2]
                    if not re.search(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}',tail,re.I):
                        tails.add(tail)
            for number in range(2,max(pages.values())+1):
                for tag in self.locales:
                    base = self.category_url(tag,identity)
                    destination = f'{base}page/{number}/' if number <= pages[tag] else base
                    for tail in tails:
                        self.redirect(f'/{tag}/{tail}page/{number}/',destination)

    def not_found(self,tag, *, root=False):
        body = f'<section class="tcc-container page-section"><header class="page-heading"><p class="eyebrow">404</p><h1>{esc(self.ui(tag,"not_found_title"))}</h1><p>{esc(self.ui(tag,"not_found_body"))}</p><a class="button" href="/{tag}/">{esc(self.ui(tag,"return_home"))} <svg class="nav-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M5 19 19 5M5 5h14v14"/></svg></a></header></section>'
        self.page(tag,'/404.html' if root else f'/{tag}/404/',self.ui(tag,'not_found_title'),body,indexed=False,paths=self.localized_paths('404',suffix='404/'),extra_config={'notFound':root,'locales':list(self.locales),'legacyRouteIndex':'/legacy-route-index.json'})

    def build(self):
        for tag in self.locales:
            self.home(tag); self.listing(tag); self.categories_page(tag); self.issues_page(tag); self.authors_page(tag); self.search_page(tag); self.rss(tag); self.not_found(tag)
            for category in self.categories:
                self.listing(tag,category=category)
            for issue in self.issues:
                self.issue_page(tag,issue)
            for author in self.authors:
                self.author_page(tag,author)
            for article in self.articles[tag]:
                self.article_page(tag,article)
            for article in self.articles['en']:
                if article['id'] not in self.article_map[tag]:
                    self.missing_article(tag,article)
        for path,destination in self.routes['redirects'].items():
            self.redirect(path,destination)
        self.category_pagination_redirects()
        self.author_pagination_redirects()
        for tag in self.locales:
            for article in self.articles[tag]:
                self.redirect(article['compatibility_url'],article['url'])
        legacy_index = {'aliases': self.routes.get('legacy_aliases', {}), 'targets': {kind: self.routes[kind] for kind in ('articles', 'categories', 'issues')}}
        self.write('/legacy-route-index.json',json.dumps(legacy_index,ensure_ascii=False,separators=(',',':'))+'\n')
        self.not_found('en',root=True)
        root_body = '<section class="tcc-container page-section"><header class="page-heading"><h1>'+BRAND+'</h1><p>'+esc(self.ui('en','intro'))+'</p></header><div class="language-grid">'+''.join(f'<a class="button button--quiet" href="/{tag}/" lang="{esc(tag)}" dir="{esc(data["meta"]["dir"])}">{esc(data["meta"]["native_name"])}</a>' for tag,data in self.locales.items())+'</div></section>'
        self.page('en','/',BRAND,root_body,indexed=False,extra_config={'rootRedirect':True,'locales':list(self.locales)})
        self.write('/routes.json',json.dumps(self.routes['registry'],ensure_ascii=False,indent=2)+'\n')
        self.write('/CNAME','remnant.truechristian.church\n')
        self.write('/.nojekyll','')
        self.write('/robots.txt',f'User-agent: *\nAllow: /\nSitemap: {ORIGIN}/sitemap.xml\n')
        sitemap = '<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:xhtml="http://www.w3.org/1999/xhtml">'
        for path,equivalents in self.sitemap:
            sitemap += '<url><loc>'+esc(ORIGIN+path)+'</loc>'+''.join(f'<xhtml:link rel="alternate" hreflang="{esc(tag)}" href="{esc(ORIGIN+url)}"/>' for tag,url in equivalents.items())+'</url>'
        self.write('/sitemap.xml',sitemap+'</urlset>')

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--english',type=Path,default=ROOT/'.build/english')
    parser.add_argument('--translations',type=Path,default=ROOT/'.build/translations')
    parser.add_argument('--theme',type=Path,default=ROOT/'.build/theme')
    parser.add_argument('--output',type=Path,default=ROOT/'dist')
    parser.add_argument('--locales',type=Path,default=ROOT/'locales')
    parser.add_argument('--registry',type=Path,default=ROOT/'data/routes.json')
    parser.add_argument('--languages',type=Path,default=ROOT/'.build/languages.json')
    parser.add_argument('--update-routes',action='store_true')
    parser.add_argument('--english-only',action='store_true')
    args = parser.parse_args()
    if args.output.exists() and any(args.output.iterdir()):
        parser.error('Output must be empty. Remove your previous generated dist explicitly before building.')
    model = load_content(args.english,None if args.english_only else args.translations, language_registry=args.languages if args.languages.exists() else None)
    locales = load_locales(args.locales)
    validate_locales(locales,registry=model['languages'],categories=model['categories'])
    routes = initialize_routes(model,locales,args.registry,update=args.update_routes)
    args.output.mkdir(parents=True,exist_ok=True)
    shutil.copytree(ROOT/'assets',args.output/'assets',dirs_exist_ok=True)
    for path in ['assets/brand/logo.jpg','assets/favicons/favicon.ico','assets/footer/city-skyline-skyscrapers-top.jpg']:
        destination = args.output/path; destination.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(args.theme/path,destination)
    shutil.copy2(args.theme/'dist/truechristian-theme.css',args.output/'assets/theme.css')
    shutil.copy2(args.theme/'dist/truechristian-theme.js',args.output/'assets/theme.js')
    images = args.english/'images'
    if not images.exists():
        images = args.english/'public/images'
    shutil.copytree(images,args.output/'images')
    if (ROOT/'public/covers').is_dir():
        shutil.copytree(ROOT/'public/covers',args.output/'covers')
    covers = json.loads((ROOT/'data/covers.json').read_text())
    scripture = Scripture()
    scripture.prepare(model['articles'])
    site = Site(model,locales,routes,args.theme,args.output,covers,scripture=scripture)
    site.build()
    scripture.save(args.output)
    report = {'site_revision':git_revision(ROOT),'theme_revision':git_revision(args.theme),'source':{key:model.get(key) for key in ['source_revision','translation_revision','translation_status','translation_omissions']},'warnings':model.get('warnings',[]),'scripture':scripture.report,'article_counts':{tag:len(articles) for tag,articles in site.articles.items()},'issues':len(site.issues),'publisher_pdfs':{'linked':len(site.issue_pdfs),'unmapped':[issue['id'] for issue in site.issues if issue['id'] not in site.issue_pdfs]},'categories':len(site.categories),'authors':len(site.authors),'search':site.search_sizes,'html_pages':len(site.html_sizes),'largest_html':sorted(site.html_sizes,key=lambda x:x[1],reverse=True)[:10],'route_additions':len(routes.get('pending',[]))}
    (ROOT/'.build').mkdir(exist_ok=True)
    (ROOT/'.build/site-build-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({key:report[key] for key in ['article_counts','issues','categories','html_pages','warnings']},ensure_ascii=False,indent=2))

if __name__=='__main__':
    main()
