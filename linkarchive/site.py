"""One static, searchable HTML page for the whole archive (no server code, no external requests)."""
import json, os
from datetime import datetime
from html import escape
from urllib.parse import urlparse

from .archive import rkey_of
from .feeds import write_atomic


def rows_for_site(db, profiles):
    """profiles: {source: Profile}. Each row: kind, title, href, direct, author, publication, published, flag, blurb, day, subject, issue_url, host, source."""
    q = '''SELECT l.kind, l.title, l.url, r.target, l.author, l.publication, l.published, l.flag, l.blurb, substr(i.date,1,10), i.subject, i.issue_url, i.source
           FROM links l JOIN issues i ON i.id=l.issue_id LEFT JOIN resolutions r ON r.rkey=l.rkey AND r.status='ok' AND l.rkey!=''
           ORDER BY i.date DESC, l.pos'''
    out = []
    for kind, title, url, target, author, pub, published, flag, blurb, day, subject, issue_url, source in db.execute(q):
        href = target or url
        direct = 1 if (target or not rkey_of(url, profiles[source])) else 0
        out.append([kind, title, href, direct, author, pub, published, flag, blurb[:320], day, subject, issue_url,
                    (urlparse(href).hostname or '').removeprefix('www.'), source])
    return out


def build_site(db, out_dir, title, profiles):
    data = json.dumps(rows_for_site(db, profiles), ensure_ascii=False, separators=(',', ':')).replace('<', '\\u003c').replace('\u2028', '\\u2028').replace('\u2029', '\\u2029')
    path = os.path.join(out_dir, 'archive', 'index.html')
    write_atomic(path, PAGE.replace('__TITLE__', escape(title)).replace('__BUILT__', datetime.now().strftime('%Y-%m-%d %H:%M')).replace('__DATA__', data))
    return path


PAGE = r'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__</title>
<style>
:root{--bg:#fbfaf7;--fg:#1d1c1a;--mute:#6b675f;--line:#e4e0d6;--card:#fff;--acc:#a4400f;--chip:#efeadf}
@media (prefers-color-scheme:dark){:root{--bg:#161512;--fg:#ece8df;--mute:#a09a8c;--line:#2d2a24;--card:#1e1c18;--acc:#f0a070;--chip:#2a2721}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:17px/1.5 Georgia,'Iowan Old Style',serif}
main{max-width:62rem;margin:0 auto;padding:1rem 16px 4rem}h1{font-size:1.5rem;margin:.6rem 0 .2rem}.sub{color:var(--mute);margin:0 0 1rem;font:14px system-ui,sans-serif}
.bar{position:sticky;top:0;background:var(--bg);padding:.6rem 0;border-bottom:1px solid var(--line);z-index:2}
.row{display:flex;flex-wrap:wrap;gap:.5rem;align-items:center;font:14px system-ui,sans-serif}
input[type=search],select{font:inherit;padding:.5rem .6rem;border:1px solid var(--line);border-radius:6px;background:var(--card);color:var(--fg)}
input[type=search]{flex:1 1 16rem;min-width:0;font-size:16px}
ul{list-style:none;margin:0;padding:0}li{padding:.8rem 0;border-bottom:1px solid var(--line)}
li a.t{color:var(--fg);font-weight:600;text-decoration:none;font-size:1.05rem}li a.t:hover,li a.t:focus-visible{color:var(--acc);text-decoration:underline}
.m{font:13px system-ui,sans-serif;color:var(--mute);margin:.15rem 0}.b{margin:.2rem 0 0;font-size:.95rem}
.chip{display:inline-block;background:var(--chip);border-radius:999px;padding:0 .5rem;font:12px system-ui,sans-serif;margin-right:.3rem}
button{font:14px system-ui,sans-serif;padding:.5rem 1rem;border:1px solid var(--line);border-radius:6px;background:var(--card);color:var(--fg);cursor:pointer}
</style></head><body><main>
<h1>__TITLE__</h1><p class="sub"><span id="n"></span> &middot; built __BUILT__ &middot; press / to search &middot; private: keep this page off the public internet</p>
<div class="bar"><div class="row"><input type="search" id="q" placeholder="Search titles, authors, publications, notes, domains" aria-label="Search" autofocus>
<select id="source" aria-label="Source"><option value="">All sources</option></select>
<select id="kind" aria-label="Kind"><option value="">All kinds</option></select>
<select id="year" aria-label="Year"><option value="">All years</option></select>
<select id="pub" aria-label="Publication"><option value="">All publications</option></select>
<select id="acc" aria-label="Access flag"><option value="">Any access flag</option></select>
<select id="sort" aria-label="Sort"><option value="new">Newest first</option><option value="old">Oldest first</option><option value="pub">Publication A to Z</option></select></div></div>
<ul id="list"></ul><p><button id="more" hidden>Show more</button></p></main>
<script>
const D=__DATA__;let view=[],shown=0;const PAGE=150,$=id=>document.getElementById(id);
const fill=(id,vals)=>[...new Set(vals.filter(Boolean))].sort().forEach(v=>$(id).add(new Option(v,v)));
fill('source',D.map(r=>r[13]));fill('kind',D.map(r=>r[0]));fill('acc',D.map(r=>r[7]));
[...new Set(D.map(r=>r[9].slice(0,4)))].sort().reverse().forEach(y=>$('year').add(new Option(y,y)));
const pubs={};D.forEach(r=>{if(r[5])pubs[r[5]]=(pubs[r[5]]||0)+1});Object.entries(pubs).sort((a,b)=>b[1]-a[1]).slice(0,300).forEach(([p,c])=>$('pub').add(new Option(p+' ('+c+')',p)));
function run(){const toks=$('q').value.toLowerCase().split(/\s+/).filter(Boolean),f=id=>$(id).value;
 view=D.filter(r=>(!f('source')||r[13]===f('source'))&&(!f('kind')||r[0]===f('kind'))&&(!f('year')||r[9].startsWith(f('year')))&&(!f('pub')||r[5]===f('pub'))&&(!f('acc')||r[7]===f('acc'))&&
  toks.every(t=>(r[1]+' '+r[4]+' '+r[5]+' '+r[8]+' '+r[12]).toLowerCase().includes(t)));
 const s=f('sort');if(s==='old')view=view.slice().reverse();else if(s==='pub')view=view.slice().sort((a,b)=>a[5].localeCompare(b[5])||b[9].localeCompare(a[9]));
 $('n').textContent=view.length.toLocaleString()+' of '+D.length.toLocaleString()+' links';$('list').replaceChildren();shown=0;more()}
function safe(u){return /^https?:\/\//i.test(u)?u:'#'}
function more(){const ul=$('list');view.slice(shown,shown+PAGE).forEach(r=>{const li=document.createElement('li'),a=document.createElement('a');a.className='t';a.href=safe(r[2]);a.textContent=r[1];a.rel='noopener noreferrer';a.target='_blank';li.append(a);
 const m=document.createElement('div');m.className='m';if(r[0]!=='article'){const c=document.createElement('span');c.className='chip';c.textContent=r[0];m.append(c)}
 m.append([r[5],r[4],r[6]||'',r[12]].filter(Boolean).join(' \u00b7 ')+'  \u00b7  '+r[9]);
 if(r[7]){const c=document.createElement('span');c.className='chip';c.textContent=r[7];m.append(' ',c)}
 if(!r[3]){const c=document.createElement('span');c.className='chip';c.textContent='via redirect';m.append(' ',c)}li.append(m);
 if(r[8]){const b=document.createElement('div');b.className='b';b.textContent=r[8];li.append(b)}ul.append(li)});shown+=PAGE;$('more').hidden=shown>=view.length}
['q','source','kind','year','pub','acc','sort'].forEach(id=>$(id).addEventListener('input',run));$('more').onclick=more;
addEventListener('keydown',e=>{if(e.key==='/'&&document.activeElement!==$('q')){e.preventDefault();$('q').focus()}});run();
</script></body></html>'''
