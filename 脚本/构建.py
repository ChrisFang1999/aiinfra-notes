"""正文唯一来源为知识库；输出均由明确白名单生成。"""
import argparse, hashlib, html, json, os, re, shutil
from pathlib import Path
from html.parser import HTMLParser
from urllib.parse import unquote, urlsplit
from markdown_it import MarkdownIt
from pygments import highlight
from pygments.lexers import get_lexer_by_name, TextLexer
from pygments.formatters import HtmlFormatter

ROOT = Path(__file__).resolve().parents[1]
TOPIC = Path('知识体系/稳定性与排障/训练报错排查')
DOCS = [('training-error-sop', '训练报错排查SOP.md', '快速 SOP'),
        ('training-error-explanation', '训练报错排查详细解释.md', '深入解释')]
EXTERNAL = {'pytorch.org', 'docs.nvidia.com', 'kubernetes.io'}

def digest(text):
    return hashlib.sha256(text.encode()).hexdigest()

def parse(raw):
    if not raw.startswith('---\n') or '\n---\n' not in raw[4:]:
        raise ValueError('缺少文档元数据')
    head, body = raw[4:].split('\n---\n', 1)
    meta = {}
    for line in head.splitlines():
        key, value = line.split(':', 1)
        if key in meta: raise ValueError('重复元数据')
        meta[key] = value.strip()
    return meta, body.strip() + '\n'

def adapt(body):
    # Only the internal reference bullet is omitted; never rewrite technical prose.
    lines = [line for line in body.splitlines() if not line.startswith('- [工作总结中的诊断能力](')]
    body = '\n'.join(lines) + '\n'
    names = {name: ident + '.html' for ident, name, _ in DOCS}
    def link(match):
        label, dest = match.groups()
        dest = unquote(dest)
        if dest in names: return f'[{label}]({names[dest]})'
        if dest == '../../../README.md': return f'[{label}](index.html)'
        if dest == '学习记录与待补充.md': return f'{label}（未公开）'
        url = urlsplit(dest)
        if url.scheme == 'https' and url.hostname in EXTERNAL:
            return match.group(0)
        raise ValueError('存在未审核的链接目标；请先审查适配规则')
    body = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', link, body)
    if any(x in body for x in ['30_工作与项目', '工作总结.md', '/Users/', 'file://']):
        raise ValueError('正文存在内部路径')
    return body

def code_highlight(code, lang, attrs):
    try: lexer = get_lexer_by_name(lang)
    except Exception: lexer = TextLexer()
    return highlight(code, lexer, HtmlFormatter(nowrap=True))

def render(body):
    md = MarkdownIt('commonmark', {'html':False, 'highlight':code_highlight}).enable('table')
    tokens = md.parse(body)
    toc = []
    n = 0
    for i, token in enumerate(tokens):
        if token.type == 'heading_open':
            n += 1
            anchor = f'section-{n}'
            token.attrSet('id', anchor)
            if token.tag != 'h1': toc.append((anchor, tokens[i+1].content, token.tag))
        if token.type == 'inline':
            for child in token.children or []:
                if child.type == 'image': raise ValueError('图片尚未经过公开审查')
                if child.type == 'link_open':
                    href = child.attrGet('href') or ''
                    allowed = {'index.html'} | {x[0]+'.html' for x in DOCS}
                    u = urlsplit(href)
                    if not (href in allowed or href.startswith('#') or (u.scheme == 'https' and u.hostname in EXTERNAL)):
                        raise ValueError('渲染层发现未经审核的链接')
    return md.renderer.render(tokens, md.options, {}), toc

class SearchText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
    def handle_data(self, data):
        self.parts.append(data)

def search_index(pages):
    result = []
    for ident, _, _ in DOCS:
        data = pages[ident]
        markup, _ = render(data['body'])
        parser = SearchText()
        parser.feed(markup)
        result.append({'title': data['title'], 'url': ident + '.html',
                       'text': re.sub(r'\s+', ' ', ' '.join(parser.parts)).strip()})
    return result

def shell(title, content, active='', toc=None, preview=False):
    nav = ''.join(f'<a {"aria-current=page" if active == ident else ""} href="{ident}.html"><span>0{i+1}</span>{kind}</a>' for i,(ident,_,kind) in enumerate(DOCS))
    aside = ''.join(f'<a class="{level}" href="#{anchor}">{html.escape(label)}</a>' for anchor,label,level in (toc or []))
    notice = '<div class="preview">本地预览 · 非线上发布版本</div>' if preview else ''
    return f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="{'noindex,nofollow' if preview else 'index,follow'}"><title>{html.escape(title)} · AI Infra 手记</title><link rel="stylesheet" href="assets/阅读.css"><script src="assets/搜索索引.js" defer></script><script src="assets/阅读.js" defer></script></head><body>{notice}<a class="skip" href="#main">跳至正文</a><header><a class="brand" href="index.html"><b>AI<span>/</span>Infra</b><small>工程实践手记</small></a><div class="header-tools"><button class="search-open" type="button" aria-haspopup="dialog">搜索 <kbd>/</kbd></button><a href="index.html#topics">知识导航 ↗</a></div></header><dialog id="search-dialog" aria-labelledby="search-title"><div class="search-top"><h2 id="search-title">搜索文章</h2><button class="search-close" type="button" aria-label="关闭搜索">关闭 ×</button></div><label for="search-input">输入关键词，查找标题与正文</label><input id="search-input" type="search" placeholder="如：GPU Hang、堆栈、采样" autocomplete="off"><p id="search-status" role="status" aria-live="polite">输入关键词开始搜索</p><ul id="search-results"></ul></dialog><div class="layout"><nav class="sidebar" aria-label="专题导航"><p class="eyebrow">知识体系 / 01</p><a class="category" href="index.html#topics">稳定性与排障</a><p class="nav-title">训练报错排查</p>{nav}<div class="side-note">从现象出发，沿证据定位。<br>保留经验的适用边界。</div></nav><main id="main">{content}</main><aside class="toc"><p class="eyebrow">本页目录</p>{aside}<a class="backtop" href="#main">回到顶部 ↑</a></aside></div><footer>AI Infra 手记 <span>持续学习 · 审慎验证 · 逐步沉淀</span></footer></body></html>'''

def build(pages, output, preview):
    # Render everything before replacing output: a validation failure preserves the last preview.
    index = search_index(pages)
    rendered = {}
    cards = []
    for ident,name,kind in DOCS:
        data = pages[ident]
        markup,toc = render(data['body'])
        intro = f'<div class="article-meta">稳定性与排障 <span> / {kind} · 更新 {html.escape(data["updated"])}</span></div>'
        other = next(x for x in DOCS if x[0] != ident)
        end = f'<a class="next" href="{other[0]}.html"><small>继续阅读</small><strong>{other[2]} →</strong></a>'
        mobile_toc = '<details class=mobile-toc><summary>本页目录</summary>' + ''.join(f'<a href="#{a}">{html.escape(t)}</a>' for a,t,_ in toc) + '</details>'
        rendered[ident+'.html'] = shell(data['title'], intro+mobile_toc+'<article>'+markup+'</article>'+end, ident, toc, preview)
        cards.append(f'<a class="card" href="{ident}.html"><span class="tag">{kind}</span><h3>{html.escape(data["title"])}</h3><p>{"多机日志、GPU 状态、平台事件与跨 rank 堆栈的初步排查入口。" if kind == "快速 SOP" else "理解判断依据、GPU Hang 检测顺序，以及经验与证据的边界。"}</p><span class="card-end">开始阅读 <b>↗</b></span></a>')
    home = '<section class="hero"><p class="eyebrow">AI INFRA / FIELD NOTES</p><h1>把问题拆开，<br>把系统看清。</h1><p class="lead">围绕真实工程问题，整理 AI 基础设施的排查路径、判断依据与实践边界。</p><a class="primary" href="training-error-sop.html">从训练报错排查开始 →</a><div class="hero-stats"><span><b>01</b> 已有专题</span><span><b>02</b> 阅读入口</span><span>从快速操作到机制理解</span></div></section><section id="topics"><p class="eyebrow">当前专题</p><h2>稳定性与排障</h2><p class="muted">先找到调查入口，再沿证据深入。</p><div class="cards">'+''.join(cards)+'</div></section><section class="direction"><p class="eyebrow">学习方向</p><h2>按问题生长的知识体系</h2><p>稳定性与排障、可观测性与软硬件监控是独立的重点方向。其余主题随实际内容逐步建立。</p><div class="chips">'+''.join('<span>'+x+'</span>' for x in ['可观测性与软硬件监控','计算与系统基础','模型计算与执行','训练系统与效率','推理系统','数据与存储','平台与工程'])+'</div></section>'
    rendered['index.html'] = shell('首页',home,preview=preview)
    rendered['404.html'] = shell('页面不存在','<h1>这篇内容尚未到来。</h1><p>请通过顶部导航返回首页。</p>',preview=preview)
    if output.exists(): shutil.rmtree(output)
    output.mkdir(parents=True)
    for name,content in rendered.items(): (output/name).write_text(content)
    shutil.copytree(ROOT/'界面',output/'assets')
    (output/'assets/搜索索引.js').write_text('window.blogSearchIndex = ' + json.dumps(index, ensure_ascii=False).replace('<', '\\u003c') + ';\n')
    with (output/'assets/阅读.css').open('a') as f: f.write(HtmlFormatter().get_style_defs('pre'))
    (output/'.nojekyll').touch()

def source_pages(source):
    pages={}
    for ident,name,kind in DOCS:
        raw=(source/TOPIC/name).read_text()
        meta,body=parse(raw)
        if meta['id'] != ident: raise ValueError('文档标识发生变化')
        pages[ident]={'title':meta['title'],'updated':meta['updated'],'body':adapt(body),'source_sha256':digest(raw),'status':meta['status'],'visibility':meta['visibility'],'publication_approval':meta.get('publication_approval',''),'publication_scope':meta.get('publication_scope',''),'deployment_status':meta.get('deployment_status','not_published')}
    return pages

def check_approval(config,pages):
    if config.get('enabled') is not True or not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',config.get('repository','')):
        raise ValueError('尚未批准公开内容及目标仓库')
    if set(config.get('approved',{})) != {d[0] for d in DOCS}: raise ValueError('公开批准清单不完整')
    for ident,data in pages.items():
        if data['visibility'] != 'public' or data.get('publication_approval') != 'approved' or data.get('publication_scope') != 'adapted_body_only':
            raise ValueError('内容未取得适配正文的公开资格')
        approved=config['approved'].get(ident,{})
        if approved.get('source_sha256') != data['source_sha256'] or approved.get('body_sha256') != digest(data['body']):
            raise ValueError('内容版本与批准记录不符，需重新审查')

def main():
    p=argparse.ArgumentParser()
    p.add_argument('mode',choices=['preview','export','public'])
    p.add_argument('--source',type=Path,default=os.environ.get('AI_INFRA_SOURCE'))
    args=p.parse_args()
    config=json.loads((ROOT/'发布配置.json').read_text())
    if args.mode in ['preview','export']:
        if not args.source: p.error('请使用 --source 指定正式知识库路径')
        pages=source_pages(Path(args.source))
        if args.mode == 'preview':
            build(pages,ROOT/'本地预览',True)
            report={ident:{'source_sha256':d['source_sha256'],'body_sha256':digest(d['body']),'status':d['status'],'visibility':d['visibility']} for ident,d in pages.items()}
            (ROOT/'本地记录').mkdir(exist_ok=True)
            (ROOT/'本地记录/版本核对.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
            print('本地预览已生成；不代表公开授权。')
            return
        check_approval(config,pages)
        for data in pages.values(): render(data['body'])
        out=ROOT/'发布内容'
        out.mkdir(exist_ok=True)
        for ident,data in pages.items(): (out/(ident+'.json')).write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
        print('已生成获准版本副本；未推送、未部署。')
    else:
        if not config.get('enabled'): raise ValueError('尚未批准公开内容及目标仓库')
        pages={ident:json.loads((ROOT/'发布内容'/(ident+'.json')).read_text()) for ident,_,_ in DOCS}
        check_approval(config,pages)
        repo=os.environ.get('GITHUB_REPOSITORY')
        if repo and repo != config['repository']: raise ValueError('当前仓库与批准目标不符')
        build(pages,ROOT/'发布站点',False)
        print('公开静态站点已生成。')

if __name__=='__main__': main()
