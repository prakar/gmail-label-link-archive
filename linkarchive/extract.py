"""Link extraction driven by a TOML profile. Standard library only (Python 3.11+ for tomllib)."""
import hashlib, re, tomllib
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html import escape
from html.parser import HTMLParser
from urllib.parse import urlparse, parse_qs, urlunparse, urlencode

BLOCK_TAGS = {'p', 'li', 'div', 'td', 'tr', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'blockquote', 'br', 'table', 'section', 'article'}
KNOWN_FIELDS = ('author', 'publication', 'date', 'flag', 'comment')


class Profile:
    """An extraction profile loaded from TOML. See config/profiles/example-newsletter.toml for every key."""
    def __init__(self, data):
        self.data = data
        self.name = data.get('name', 'unnamed')
        f = data.get('filter', {})
        rx = lambda s, flags=re.I: re.compile(s, flags) if s else None
        self.skip_text = rx(f.get('skip_text'))
        self.skip_hosts = rx(f.get('skip_hosts'))
        self.always = rx(f.get('always_consider_regex'))
        self.min_title_chars = int(f.get('min_title_chars', 18))
        self.unwrap_keys = tuple(f.get('unwrap_keys', ('url', 'u', 'redirect', 'redirect_url', 'target', 'link', 'q')))
        self.drop_prefixes = tuple(f.get('drop_param_prefixes', ('utm_', 'mc_', 'fbclid', 'gclid')))
        self.max_blurb = int(data.get('blurb', {}).get('max_chars', 700))
        m = data.get('meta', {})
        self.meta = rx(m.get('regex'), 0 if m.get('case_sensitive') else re.I)
        self.date_formats = tuple(m.get('date_formats', ('%d %B %Y', '%d %b %Y', '%B %Y', '%Y')))
        self.rules = []
        for r in data.get('rules', []):
            flags = 0 if r.get('case_sensitive') else re.I          # per rule; (?-i:...) inside a regex still works too
            self.rules.append({'kind': r['kind'], 'use_meta': bool(r.get('use_meta')), 'title_equals_subject': bool(r.get('title_equals_subject')),
                               **{k: rx(r[k], flags) for k in ('title_regex', 'blurb_regex', 'subject_regex', 'any_regex') if k in r}})
        self.split = {s['kind']: s['field'] for s in data.get('split_title', [])}
        k = data.get('kinds', {})
        self.keep = tuple(k.get('keep', ('article', 'podcast', 'video', 'other')))
        self.resolve_kinds = tuple(k.get('resolve', ('article', 'podcast', 'video', 'other')))
        r = data.get('resolve', {})
        self.resolve_hosts = tuple(h.strip().lower() for h in r.get('hosts', []) if h.strip())
        self.resolve_prefix = r.get('path_prefix', '/r/')
        self.drop_ref_values = tuple(v.lower() for v in r.get('drop_ref_values', []))

    @classmethod
    def load(cls, path):
        with open(path, 'rb') as fh:
            return cls(tomllib.load(fh))


class Blocks(HTMLParser):
    """Walks the HTML once and produces blocks: {'text': str, 'links': [(href, text)], 'heading': bool}."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blocks, self._text, self._links, self._href, self._atext, self._head, self._skip = [], [], [], None, [], False, 0

    def _flush(self):
        text = re.sub(r'\s+', ' ', ''.join(self._text)).strip()
        if text or self._links:
            self.blocks.append({'text': text, 'links': self._links, 'heading': self._head})
        self._text, self._links, self._head = [], [], False

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style', 'head'): self._skip += 1; return
        if tag in BLOCK_TAGS: self._flush()
        if tag in ('h1', 'h2', 'h3', 'h4'): self._head = True
        if tag == 'a': self._href, self._atext = dict(attrs).get('href'), []

    def handle_endtag(self, tag):
        if tag in ('script', 'style', 'head'): self._skip = max(0, self._skip - 1); return
        if tag == 'a' and self._href is not None:
            t = re.sub(r'\s+', ' ', ''.join(self._atext)).strip()
            if t: self._links.append((self._href, t))
            self._href = None
        if tag in BLOCK_TAGS: self._flush()

    def handle_data(self, data):
        if self._skip: return
        self._text.append(data)
        if self._href is not None: self._atext.append(data)

    def close(self):
        super().close(); self._flush()


def clean_url(url, profile):
    """Unwrap tracking redirects (...?url=https%3A//real) and drop tracking parameters."""
    u = urlparse(url)
    q = parse_qs(u.query)
    for k in profile.unwrap_keys:
        for v in q.get(k, []):
            if v.startswith(('http://', 'https://')): return clean_url(v, profile)
    keep = [(k, v) for k, vs in q.items() if not k.lower().startswith(profile.drop_prefixes) for v in vs]
    return urlunparse((u.scheme, u.netloc, u.path, u.params, urlencode(keep), ''))


def good_link(href, text, heading, profile):
    if not href or not href.startswith(('http://', 'https://')): return False
    if profile.skip_text and profile.skip_text.search(text): return False
    if profile.skip_hosts and profile.skip_hosts.search(urlparse(href).hostname or ''): return False
    return heading or len(text) >= profile.min_title_chars


def parse_date(text, profile):
    """'13th August 2026' -> '2026-08-13'; anything the profile's formats do not cover -> ''."""
    t = re.sub(r'(\d)(st|nd|rd|th)\b', r'\1', (text or '').strip())
    for fmt in profile.date_formats:
        try: return datetime.strptime(t, fmt).strftime('%Y-%m-%d')
        except ValueError: pass
    return ''


def classify(title, blurb, subject, profile):
    """First matching rule wins; no match gives kind 'other'. Returns (kind, fields)."""
    for r in profile.rules:
        if r['title_equals_subject'] and title.strip().lower() != subject.strip().lower(): continue
        if 'title_regex' in r and not r['title_regex'].search(title): continue
        if 'blurb_regex' in r and not r['blurb_regex'].search(blurb.lstrip()): continue
        if 'subject_regex' in r and not r['subject_regex'].search(subject): continue
        if 'any_regex' in r and not (r['any_regex'].search(title) or r['any_regex'].search(blurb[:120])): continue
        fields = {}
        if r['use_meta']:
            m = profile.meta.match(blurb) if profile.meta else None
            if not m: continue
            g = m.groupdict()
            fields = {'author': (g.get('author') or '').strip(), 'publication': (g.get('publication') or '').strip(),
                      'published': parse_date(g.get('date'), profile), 'published_raw': (g.get('date') or '').strip(),
                      'access': (g.get('flag') or '').strip(), 'comment': (g.get('comment') or '').strip()}
        return r['kind'], fields
    return 'other', {}


def clean_title(kind, title, profile):
    """If the profile splits titles for this kind ('Title | Show'), keep the first part and store the rest in the named field."""
    parts = [x.strip() for x in title.split('|')]
    field = profile.split.get(kind)
    if field and len(parts) > 1: return parts[0], {field: ' | '.join(parts[1:])}
    return title, {}


def find_links(html, subject, profile):
    """Each qualifying link becomes a record: {kind, title, url, blurb, ...}. The blurb is the rest of the link's own block
    plus following plain-text blocks, up to the next block that carries a link."""
    p = Blocks(); p.feed(html); p.close()
    blocks, seen, out = p.blocks, set(), []
    for i, b in enumerate(blocks):
        cands = [(h, t) for h, t in b['links'] if good_link(h, t, b['heading'], profile) or (profile.always and profile.always.search(t))]
        if not cands: continue
        href, title = max(cands, key=lambda x: len(x[1]))
        url = clean_url(href, profile)
        if url in seen: continue
        seen.add(url)
        parts = [b['text'].replace(title, '', 1).strip(' -–—:|')]
        j = i + 1
        while j < len(blocks) and not blocks[j]['links'] and sum(map(len, parts)) < profile.max_blurb:
            if blocks[j]['text']: parts.append(blocks[j]['text'])
            j += 1
        blurb = ' '.join(x for x in parts if x).strip()[:profile.max_blurb]
        kind, fields = classify(title, blurb, subject, profile)
        title2, more = clean_title(kind, title, profile)
        if kind == 'other':      # a link inside running prose: keep the whole sentence as context
            blurb = ' '.join(x for x in [b['text']] + parts[1:] if x).strip()[:profile.max_blurb]
        out.append({'kind': kind, 'title': title2, 'url': url, 'blurb': blurb, **fields, **more})
    return out


def strip_fw(subject):
    return re.sub(r'^\s*((fw|fwd|re)\s*:\s*)+', '', subject or '', flags=re.I).strip() or '(no subject)'


def body_html(msg):
    """Prefers text/html; falls back to text/plain wrapped in <pre>. Looks inside forwarded-as-attachment messages too."""
    html = plain = None
    for part in msg.walk():
        ct = part.get_content_type()
        if ct == 'message/rfc822':
            inner = part.get_payload(0)
            if inner is not None:
                h = body_html(inner)
                if h: return h
        if part.is_multipart(): continue
        if ct == 'text/html' and html is None: html = part.get_content()
        elif ct == 'text/plain' and plain is None: plain = part.get_content()
    if html: return html
    if plain: return '<pre>' + escape(plain) + '</pre>'
    return ''


def issue_from_message(msg, profile):
    try: when = parsedate_to_datetime(msg['Date'])
    except Exception: when = datetime.now(timezone.utc)
    if when.tzinfo is None: when = when.replace(tzinfo=timezone.utc)
    mid = (msg['Message-ID'] or '').strip() or hashlib.sha1(((msg['Subject'] or '') + str(when)).encode()).hexdigest()
    html = body_html(msg); subject = strip_fw(str(msg['Subject'] or ''))
    found = find_links(html, subject, profile)
    return {'id': mid, 'subject': subject, 'date': when, 'html': html,
            'issue_url': next((x['url'] for x in found if x['kind'] == 'issue'), ''), 'all_links': found,
            'articles': [x for x in found if x['kind'] in profile.keep]}
