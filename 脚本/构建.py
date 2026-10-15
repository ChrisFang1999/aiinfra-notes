"""正文唯一来源为知识库；输出均由明确白名单生成。"""
import argparse, hashlib, html, json, os, re, shutil, posixpath
from pathlib import Path
from html.parser import HTMLParser
from urllib.parse import unquote, urlsplit
from markdown_it import MarkdownIt
from pygments import highlight
from pygments.lexers import get_lexer_by_name, TextLexer
from pygments.formatters import HtmlFormatter

ROOT = Path(__file__).resolve().parents[1]
TOPIC = Path('知识体系/稳定性与排障/训练报错排查')
SLOW_TOPIC = Path('知识体系/稳定性与排障/训练慢与变慢排查')
DDP_TOPIC = Path('知识体系/训练系统与效率/DDP分布式训练')
IMAGES = ('GPU通信等待利用率原理示意图.png', 'GPU利用率与SM活跃率统计原理示意图.png')
DDP_IMAGES = ('01_DDP训练全流程图.png', '02_单机与双机进程结构图.png', '03_分布式初始化与通信验证图.png', '04_模型状态与同步范围图.png', '05_样本索引分配图.png', '06_单rank数据加载链路图.png', '07_数据预取与消费时间线.png', '08_各rank计算与参数更新图.png', '09_bucket划分与梯度就绪图.png', '10_计算通信重叠时间线.png', '11_Ring_AllReduce分步图.png', '12_梯度累计与no_sync时间线.png', '13_AMP与参数更新顺序图.png', '14_慢rank与通信不匹配对照图.png')
DOCS = [('training-error-sop', '训练报错排查SOP.md', '快速 SOP'),
        ('training-error-explanation', '训练报错排查详细解释.md', '深入解释'),
        ('training-hang-communication', '训练卡住排查：通信等待型GPU_Hang.md', 'GPU Hang 专题'),
        ('training-slow-sop', '训练慢与变慢排查SOP.md', '训练慢 SOP'),
        ('training-slow-explanation', '训练慢与变慢排查详细解释.md', '训练慢详解'),
        ('ddp-training-principles', 'DDP分布式训练：从启动到参数更新.md', 'DDP 原理与实战')]
DOC_PATHS = {ident: (DDP_TOPIC if ident.startswith('ddp-') else SLOW_TOPIC if ident.startswith('training-slow-') else TOPIC) / name for ident,name,_ in DOCS}
EXTERNAL = {'pytorch.org', 'docs.pytorch.org', 'docs.nvidia.com', 'kubernetes.io', 'numpy.org', 'deepspeed.readthedocs.io'}
EXTERNAL_URLS = {
    'https://github.com/NVIDIA/nccl/blob/master/src/device/prims_simple.h',
    'https://github.com/NVIDIA/nccl/blob/master/src/misc/socket.cc',
    'https://github.com/NVIDIA/nccl/issues/947',
    'https://github.com/facebookresearch/HolisticTraceAnalysis',
}
SUMMARIES = {
    'training-error-sop': '多机日志、GPU 状态、平台事件与跨 rank 堆栈的初步排查入口。',
    'training-error-explanation': '理解判断依据、自动检测顺序、网卡计数器及经验与证据的边界。',
    'training-hang-communication': '从通信等待机制出发，串联 GPU Hang 的排查流程、原因分支与恢复验证。',
    'training-slow-sop': '以 step time 和跨 rank 差异为入口，快速定位数据、CPU、GPU 与通信问题。',
    'training-slow-explanation': '展开基准比较、数据等待、Profile 时间线及验证边界。',
    'ddp-training-principles': '从 torchrun 启动到梯度同步和参数更新，结合流程图与可运行示例理解 DDP。',
}

def allowed_external(url):
    parsed = urlsplit(url)
    return parsed.scheme == 'https' and (parsed.hostname in EXTERNAL or url in EXTERNAL_URLS)


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

def adapt(body, ident="training-error-sop"):
    # Only the internal reference bullet is omitted; never rewrite technical prose.
    lines = [line for line in body.splitlines() if not line.startswith('- [工作总结中的诊断能力](')]
    body = '\n'.join(lines) + '\n'
    source_dir = DOC_PATHS[ident].parent.as_posix()
    paths = {path.as_posix(): key + '.html' for key,path in DOC_PATHS.items()}
    private_names = {'学习记录与待补充.md', '训练慢排查讨论记录.md', '文档维护记录.md'}
    def link(match):
        label, dest = match.groups()
        dest = unquote(dest)
        if dest in private_names: return f'{label}（未公开）'
        resolved = posixpath.normpath(posixpath.join(source_dir, dest))
        if resolved in paths: return f'[{label}]({paths[resolved]})'
        if dest.startswith('#') and ident.startswith('ddp-'): return match.group(0)
        if dest.startswith('配图/') and dest.removeprefix('配图/') in IMAGES: return match.group(0)
        if ident.startswith('ddp-') and dest.startswith('配图/') and dest.removeprefix('配图/') in DDP_IMAGES:
            return f'[{label}](ddp配图/{dest.removeprefix("配图/")})'
        if ident.startswith('ddp-') and dest == 'DDP训练示例.py': return f'[{label}](下载/DDP训练示例.py)'
        if dest == '../../../README.md': return f'[{label}](index.html)'
        url = urlsplit(dest)
        if allowed_external(dest):
            return match.group(0)
        raise ValueError(f'存在未审核的链接目标：{dest}')
    body = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', link, body)
    if any(x in body for x in ['30_工作与项目', '工作总结.md', '/Users/', 'file://']):
        raise ValueError('正文存在内部路径')
    return body

def code_highlight(code, lang, attrs):
    try: lexer = get_lexer_by_name(lang)
    except Exception: lexer = TextLexer()
    return highlight(code, lexer, HtmlFormatter(nowrap=True))

def mermaid_svg(code):
    # Supported source grammar is deliberately narrow; new syntax fails closed.
    lines = [line.strip() for line in code.strip().splitlines() if line.strip()]
    if not lines or lines.pop(0) != 'flowchart TD':
        raise ValueError('仅支持当前自上而下的 Mermaid 流程图')
    nodes, edges = {}, []
    definition = re.compile(r'([A-Z])([\[{])"([^"\n]+)"([\]}])')
    for line in lines:
        standalone = definition.fullmatch(line)
        if standalone:
            ident, opener, title, closer = standalone.groups()
            if (opener, closer) not in [('{','}'),('[',']')]: raise ValueError('节点括号不匹配')
            nodes[ident] = (title.split('<br/>'), opener == '{')
            continue
        parts = re.split(r'\s+--\s+(.+?)\s+-->\s+', line, maxsplit=1)
        if len(parts) != 3:
            raise ValueError('流程图出现未支持的 Mermaid 语法')
        left, label, right = parts
        found = []
        for part in (left, right):
            match = definition.fullmatch(part)
            if match:
                ident, opener, title, closer = match.groups()
                if (opener, closer) not in [('{','}'),('[',']')]: raise ValueError('节点括号不匹配')
                info = (title.split('<br/>'), opener == '{')
                if ident in nodes and nodes[ident] != info: raise ValueError('节点定义冲突')
                nodes[ident] = info; found.append(ident)
            elif re.fullmatch(r'[A-Z]', part) and part in nodes: found.append(part)
            else: raise ValueError('流程图出现未定义节点')
        edges.append((found[0], found[1], label))
    if set(nodes) != set('ABCDEFG') or len(edges) != 6 or set((a,b) for a,b,_ in edges) != {('A','B'),('A','C'),('C','D'),('C','E'),('E','F'),('E','G')}:
        raise ValueError('流程图结构变化，需要更新图形布局')
    centers = {'A':(390,85),'B':(635,85),'C':(390,230),'D':(635,375),'E':(390,375),'F':(150,520),'G':(635,520)}
    result = ['<figure class="flowchart"><svg viewBox="0 0 790 610" role="img" aria-labelledby="flow-title flow-desc" xmlns="http://www.w3.org/2000/svg"><title id="flow-title">训练报错排障流程图</title><desc id="flow-desc">先查多机日志，再查平台与硬件，最后按 GPU Hang 迹象分流；所有分支保留堆栈与日志调查入口。</desc><defs><marker id="arrow" markerWidth="9" markerHeight="9" refX="8" refY="4.5" orient="auto"><path d="M0 0L9 4.5L0 9Z" fill="#527a65"/></marker></defs>']
    routes = {('A','B'):'M510 85 L530 85',('A','C'):'M390 135 L390 180',('C','D'):'M510 230 L635 230 L635 335',('C','E'):'M390 280 L390 325',('E','F'):'M270 375 L150 375 L150 480',('E','G'):'M510 375 L635 375 L635 480'}
    labels = {('A','B'):(558,76),('A','C'):(403,163),('C','D'):(558,222),('C','E'):(403,308),('E','F'):(178,365),('E','G'):(558,365)}
    for a,b,label in edges:
        x,y=labels[(a,b)]
        result.append(f'<path class="flow-edge" d="{routes[(a,b)]}" marker-end="url(#arrow)"/><text class="flow-label" x="{x}" y="{y}">{html.escape(label)}</text>')
    for ident,(title,decision) in nodes.items():
        x,y=centers[ident]
        if decision: result.append(f'<path class="flow-decision" d="M{x} {y-50} L{x+120} {y} L{x} {y+50} L{x-120} {y}Z"/>')
        else: result.append(f'<rect class="flow-action" x="{x-105}" y="{y-40}" width="210" height="80" rx="11"/>')
        result.append(f'<text class="flow-node" x="{x}" y="{y-9 if len(title)>1 else y+5}">')
        for j,part in enumerate(title): result.append(f'<tspan x="{x}" dy="{j*0+20 if j else 0}">{html.escape(part)}</tspan>')
        result.append('</text>')
    result.append('</svg><p class="mobile-hint">左右滑动查看完整流程图</p><figcaption>训练报错初步排查路径。发现线索后进入对应诊断；证据不足时继续补充日志和堆栈。</figcaption></figure>')
    return ''.join(result)

def image_hashes(directory):
    result = {}
    for name in IMAGES:
        path = directory / '配图' / name
        if not path.is_file() or path.stat().st_size > 5_000_000 or path.read_bytes()[:8] != b'\x89PNG\r\n\x1a\n':
            raise ValueError('缺少获准 PNG 或图片格式不符')
        result[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result

def ddp_asset_hashes(directory):
    result = {}
    for name in DDP_IMAGES:
        path = directory / 'ddp配图' / name
        if not path.is_file() or path.stat().st_size > 5_000_000 or path.read_bytes()[:8] != b'\x89PNG\r\n\x1a\n':
            raise ValueError('缺少获准 DDP PNG 或图片格式不符')
        result['ddp配图/' + name] = hashlib.sha256(path.read_bytes()).hexdigest()
    code = directory / '下载/DDP训练示例.py'
    if not code.is_file() or code.stat().st_size > 100_000:
        raise ValueError('缺少获准 DDP 示例代码')
    result['下载/DDP训练示例.py'] = hashlib.sha256(code.read_bytes()).hexdigest()
    return result

def render(body, ident=''):
    disclosures = []
    if ident == 'ddp-training-principles':
        def disclosure(match):
            summary, content = match.groups()
            if '<' in summary or '>' in summary or '<details' in content or '<summary' in content:
                raise ValueError('折叠内容格式未经审核')
            inner, _ = render(content.strip(), ident)
            disclosures.append(f'<details class="article-details"><summary>{html.escape(summary)}</summary>{inner}</details>')
            return f'\n\nBLOG_DISCLOSURE_{len(disclosures)-1}\n\n'
        body = re.sub(r'<details>\s*<summary>([^\n<>]+)</summary>\s*(.*?)\s*</details>', disclosure, body, flags=re.S)
        if '<details' in body or '<summary' in body: raise ValueError('折叠内容格式未经审核')
    md = MarkdownIt('commonmark', {'html':False, 'highlight':code_highlight}).enable('table')
    tokens = md.parse(body)
    for token in tokens:
        if token.type == 'fence' and token.info.strip() == 'mermaid':
            token.type = 'html_block'
            token.content = mermaid_svg(token.content)
    toc = []
    n = 0
    for i, token in enumerate(tokens):
        if token.type == 'heading_open':
            n += 1
            anchor = re.sub(r'[^\w\s-]', '', tokens[i+1].content.lower()).strip().replace(' ', '-') if ident == 'ddp-training-principles' else f'section-{n}'
            token.attrSet('id', anchor)
            if token.tag != 'h1': toc.append((anchor, tokens[i+1].content, token.tag))
        if token.type == 'inline':
            for child in token.children or []:
                if child.type == 'image' and unquote(child.attrGet('src') or '') not in ({'配图/' + x for x in IMAGES} | {'ddp配图/' + x for x in DDP_IMAGES}): raise ValueError('图片尚未经过公开审查')
                if child.type == 'link_open':
                    href = unquote(child.attrGet('href') or '')
                    allowed = {'index.html', '下载/DDP训练示例.py'} | {x[0]+'.html' for x in DOCS}
                    u = urlsplit(href)
                    if not (href in allowed or href.startswith('#') or allowed_external(href)):
                        raise ValueError(f'渲染层发现未经审核的链接：{href}')
                    if href == '下载/DDP训练示例.py': child.attrSet('download', 'DDP训练示例.py')
    markup = md.renderer.render(tokens, md.options, {})
    if ident == 'ddp-training-principles' and '11_Ring_AllReduce分步图.png' in body:
        def original_diagram(match):
            tag = match.group(0)
            src = match.group(1)
            return f'<a class="diagram-original" href="{src}" target="_blank" rel="noopener" aria-label="打开 Ring AllReduce 原图">{tag}<span>打开原图放大查看 ↗</span></a>'
        markup, count = re.subn(r'<img\s+[^>]*src="([^"]*11_Ring_AllReduce[^"]*\.png)"[^>]*>', original_diagram, markup)
        if count != 1: raise ValueError('Ring AllReduce 图的原图链接未生成')
    for i, disclosure_html in enumerate(disclosures):
        markup = markup.replace(f'<p>BLOG_DISCLOSURE_{i}</p>', disclosure_html)
    return markup, toc

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
        markup, _ = render(data['body'], ident)
        parser = SearchText()
        parser.feed(markup)
        result.append({'title': data['title'], 'url': ident + '.html',
                       'text': re.sub(r'\s+', ' ', ' '.join(parser.parts)).strip()})
    return result

def analytics_snippet(config, preview=False):
    if preview or config.get('enabled') is not True:
        return ''
    if config.get('provider') != 'umami_cloud':
        raise ValueError('未审核的统计服务')
    website_id = config.get('website_id', '')
    if not isinstance(website_id, str) or not re.fullmatch(r'[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}', website_id):
        raise ValueError('Umami Website ID 缺失或格式错误')
    return (f'<script defer src="https://cloud.umami.is/script.js" data-website-id="{website_id}" '
            'data-domains="chrisfang1999.github.io" data-exclude-search="true" '
            'data-exclude-hash="true" data-do-not-track="true"></script>')

def shell(title, content, active='', toc=None, preview=False):
    nav = ''
    for i,(ident,_,kind) in enumerate(DOCS):
        if i == 5: nav += '<a class="category" href="index.html#ddp-topic">训练系统与效率</a>'
        if i in (0,3,5): nav += f'<p class="nav-title">{"训练报错排查" if i == 0 else "训练慢与变慢排查" if i == 3 else "DDP 分布式训练"}</p>'
        nav += f'<a {"aria-current=page" if active == ident else ""} href="{ident}.html"><span>0{i+1}</span>{kind}</a>'
    aside = ''.join(f'<a class="{level}" href="#{anchor}">{html.escape(label)}</a>' for anchor,label,level in (toc or []))
    notice = '<div class="preview">本地预览 · 非线上发布版本</div>' if preview else ''
    analytics = analytics_snippet(json.loads((ROOT/'统计配置.json').read_text()), preview)
    return f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="{'noindex,nofollow' if preview else 'index,follow'}"><title>{html.escape(title)} · AI Infra 手记</title><link rel="stylesheet" href="assets/阅读.css"><script src="assets/搜索索引.js" defer></script><script src="assets/阅读.js" defer></script>{analytics}</head><body>{notice}<a class="skip" href="#main">跳至正文</a><header><a class="brand" href="index.html"><b>AI<span>/</span>Infra</b><small>工程实践手记</small></a><div class="header-tools"><button class="search-open" type="button" aria-haspopup="dialog">搜索 <kbd>/</kbd></button><a href="index.html#topics">知识导航 ↗</a></div></header><dialog id="search-dialog" aria-labelledby="search-title"><div class="search-top"><h2 id="search-title">搜索文章</h2><button class="search-close" type="button" aria-label="关闭搜索">关闭 ×</button></div><label for="search-input">输入关键词，查找标题与正文</label><input id="search-input" type="search" placeholder="如：GPU Hang、堆栈、采样" autocomplete="off"><p id="search-status" role="status" aria-live="polite">输入关键词开始搜索</p><ul id="search-results"></ul></dialog><div class="layout"><nav class="sidebar" aria-label="专题导航"><p class="eyebrow">知识体系 / 01</p><a class="category" href="index.html#topics">稳定性与排障</a>{nav}<div class="side-note">从现象出发，沿证据定位。<br>保留经验的适用边界。</div></nav><main id="main">{content}</main><aside class="toc"><p class="eyebrow">本页目录</p>{aside}<a class="backtop" href="#main">回到顶部 ↑</a></aside></div><footer>AI Infra 手记 <span>持续学习 · 审慎验证 · 逐步沉淀</span></footer></body></html>'''

def build(pages, output, preview, images):
    # Render everything before replacing output: a validation failure preserves the last preview.
    index = search_index(pages)
    rendered = {}
    cards = []
    for ident,name,kind in DOCS:
        data = pages[ident]
        markup,toc = render(data['body'], ident)
        category = '训练系统与效率' if ident.startswith('ddp-') else '稳定性与排障'
        intro = f'<div class="article-meta">{category} <span> / {kind} · 更新 {html.escape(data["updated"])}</span></div>'
        end = '<div class="related">' + ''.join(f'<a class="next" href="{other[0]}.html"><small>继续阅读</small><strong>{other[2]} →</strong></a>' for other in DOCS if other[0] != ident) + '</div>'
        mobile_toc = '<details class=mobile-toc><summary>本页目录</summary>' + ''.join(f'<a href="#{a}">{html.escape(t)}</a>' for a,t,_ in toc) + '</details>'
        rendered[ident+'.html'] = shell(data['title'], intro+mobile_toc+'<article>'+markup+'</article>'+end, ident, toc, preview)
        cards.append(f'<a class="card" href="{ident}.html"><span class="tag">{kind}</span><h3>{html.escape(data["title"])}</h3><p>{SUMMARIES[ident]}</p><span class="card-end">开始阅读 <b>↗</b></span></a>')
    home = '<section class="hero"><p class="eyebrow">AI INFRA / FIELD NOTES</p><h1>把问题拆开，<br>把系统看清。</h1><p class="lead">围绕真实工程问题，整理 AI 基础设施的排查路径、判断依据与实践边界。</p><a class="primary" href="training-error-sop.html">从训练报错排查开始 →</a><div class="hero-stats"><span><b>03</b> 已有专题</span><span><b>06</b> 阅读入口</span><span>从快速操作到机制理解</span></div></section><section id="topics"><p class="eyebrow">当前专题</p><h2>稳定性与排障</h2><p class="muted">先找到调查入口，再沿证据深入。</p><div class="cards"><h3 class="group-heading">训练报错排查</h3>'+''.join(cards[:3])+'<h3 class="group-heading">训练慢与变慢排查</h3>'+''.join(cards[3:5])+'</div></section><section id="ddp-topic" class="topic-section"><p class="eyebrow">新增专题</p><h2>训练系统与效率</h2><p class="muted">从启动、数据分配到梯度同步和参数更新。</p><div class="cards">'+''.join(cards[5:])+'</div></section><section class="direction"><p class="eyebrow">学习方向</p><h2>按问题生长的知识体系</h2><p>稳定性与排障、可观测性与软硬件监控是独立的重点方向。其余主题随实际内容逐步建立。</p><div class="chips">'+''.join('<span>'+x+'</span>' for x in ['可观测性与软硬件监控','计算与系统基础','模型计算与执行','训练系统与效率','推理系统','数据与存储','平台与工程'])+'</div></section>'
    rendered['index.html'] = shell('首页',home,preview=preview)
    rendered['404.html'] = shell('页面不存在','<h1>这篇内容尚未到来。</h1><p>请通过顶部导航返回首页。</p>',preview=preview)
    if output.exists(): shutil.rmtree(output)
    output.mkdir(parents=True)
    for name,content in rendered.items(): (output/name).write_text(content)
    shutil.copytree(ROOT/'界面',output/'assets')
    (output/'配图').mkdir()
    for name in IMAGES: shutil.copy2(images/'配图'/name, output/'配图'/name)
    (output/'ddp配图').mkdir()
    for name in DDP_IMAGES: shutil.copy2(images/'ddp配图'/name, output/'ddp配图'/name)
    (output/'下载').mkdir()
    shutil.copy2(images/'下载/DDP训练示例.py', output/'下载/DDP训练示例.py')
    (output/'assets/搜索索引.js').write_text('window.blogSearchIndex = ' + json.dumps(index, ensure_ascii=False).replace('<', '\\u003c') + ';\n')
    with (output/'assets/阅读.css').open('a') as f: f.write(HtmlFormatter().get_style_defs('pre'))
    (output/'.nojekyll').touch()

def source_pages(source, only=None):
    pages={}
    for ident,name,kind in DOCS:
        if only and ident != only: continue
        raw=(source/DOC_PATHS[ident]).read_text()
        meta,body=parse(raw)
        if meta['id'] != ident: raise ValueError('文档标识发生变化')
        pages[ident]={'title':meta['title'],'updated':meta['updated'],'body':adapt(body,ident),'source_sha256':digest(raw),'status':meta['status'],'visibility':meta['visibility'],'publication_approval':meta.get('publication_approval',''),'publication_scope':meta.get('publication_scope',''),'deployment_status':meta.get('deployment_status','not_published')}
    return pages

def check_approval(config,pages):
    if config.get('enabled') is not True or not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',config.get('repository','')):
        raise ValueError('尚未批准公开内容及目标仓库')
    if set(config.get('approved',{})) != {d[0] for d in DOCS}: raise ValueError('公开批准清单不完整')
    for ident,data in pages.items():
        approved=config['approved'].get(ident,{})
        allowed_scope = 'body_images_example_code' if ident == 'ddp-training-principles' else 'adapted_body_only'
        if data['visibility'] != 'public' or data.get('publication_approval') != 'approved' or data.get('publication_scope') != allowed_scope:
            raise ValueError('内容未取得适配正文的公开资格')
        if approved.get('source_sha256') != data['source_sha256'] or approved.get('body_sha256') != digest(data['body']):
            raise ValueError('内容版本与批准记录不符，需重新审查')

def main():
    p=argparse.ArgumentParser()
    p.add_argument('mode',choices=['preview','export','public'])
    p.add_argument('--source',type=Path,default=os.environ.get('AI_INFRA_SOURCE'))
    p.add_argument('--only',choices=[d[0] for d in DOCS])
    args=p.parse_args()
    config=json.loads((ROOT/'发布配置.json').read_text())
    if args.mode in ['preview','export']:
        if not args.source: p.error('请使用 --source 指定正式知识库路径')
        pages=source_pages(Path(args.source), args.only)
        if args.mode == 'preview':
            pages = {ident: json.loads((ROOT/'发布内容'/(ident+'.json')).read_text()) for ident,_,_ in DOCS if ident not in pages} | pages
            build(pages,ROOT/'本地预览',True,ROOT/'发布内容')
            report={ident:{'source_sha256':d['source_sha256'],'body_sha256':digest(d['body']),'status':d['status'],'visibility':d['visibility']} for ident,d in pages.items()}
            (ROOT/'本地记录').mkdir(exist_ok=True)
            (ROOT/'本地记录/版本核对.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
            print('本地预览已生成；不代表公开授权。')
            return
        check_approval(config,pages)
        for ident,data in pages.items(): render(data['body'], ident)
        out=ROOT/'发布内容'
        out.mkdir(exist_ok=True)
        for ident,data in pages.items(): (out/(ident+'.json')).write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
        if not args.only or args.only == 'ddp-training-principles':
            ddp_dir=Path(args.source)/DDP_TOPIC
            staged=ROOT/'本地记录/DDP资源暂存'
            (staged/'ddp配图').mkdir(parents=True,exist_ok=True)
            (staged/'下载').mkdir(exist_ok=True)
            for name in DDP_IMAGES: shutil.copy2(ddp_dir/'配图'/name, staged/'ddp配图'/name)
            shutil.copy2(ddp_dir/'DDP训练示例.py', staged/'下载/DDP训练示例.py')
            if ddp_asset_hashes(staged) != config.get('approved_ddp_assets'): raise ValueError('DDP 资源版本与批准记录不符')
            shutil.copytree(staged/'ddp配图',out/'ddp配图',dirs_exist_ok=True)
            shutil.copytree(staged/'下载',out/'下载',dirs_exist_ok=True)
            shutil.rmtree(staged)
        if not args.only:
            asset_dir = Path(args.source)/TOPIC
            if image_hashes(asset_dir) != config.get('approved_assets'): raise ValueError('图片版本与批准记录不符')
            (out/'配图').mkdir(exist_ok=True)
            for name in IMAGES: shutil.copy2(asset_dir/'配图'/name, out/'配图'/name)
        print('已生成获准版本副本；未推送、未部署。')
    else:
        if not config.get('enabled'): raise ValueError('尚未批准公开内容及目标仓库')
        pages={ident:json.loads((ROOT/'发布内容'/(ident+'.json')).read_text()) for ident,_,_ in DOCS}
        check_approval(config,pages)
        repo=os.environ.get('GITHUB_REPOSITORY')
        if repo and repo != config['repository']: raise ValueError('当前仓库与批准目标不符')
        if image_hashes(ROOT/'发布内容') != config.get('approved_assets'): raise ValueError('发布图片与批准版本不符')
        if ddp_asset_hashes(ROOT/'发布内容') != config.get('approved_ddp_assets'): raise ValueError('DDP 资源与批准版本不符')
        build(pages,ROOT/'发布站点',False,ROOT/'发布内容')
        print('公开静态站点已生成。')

if __name__=='__main__': main()
