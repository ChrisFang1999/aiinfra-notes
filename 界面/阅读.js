document.querySelectorAll('table').forEach(table=>{const box=document.createElement('div');box.className='table-wrap';box.tabIndex=0;box.setAttribute('role','region');box.setAttribute('aria-label','可横向滚动的表格');table.before(box);box.append(table);});
document.querySelectorAll('pre').forEach(pre=>{const button=document.createElement('button');button.textContent='复制代码';button.type='button';button.addEventListener('click',async()=>{try{await navigator.clipboard.writeText(pre.querySelector('code').textContent);button.textContent='已复制';}catch{button.textContent='请选中代码复制';}setTimeout(()=>button.textContent='复制代码',2200);});pre.prepend(button);});
if('IntersectionObserver' in window){const links=[...document.querySelectorAll('.toc a')];const observer=new IntersectionObserver(entries=>{entries.forEach(entry=>{if(entry.isIntersecting)links.forEach(a=>a.classList.toggle('active',a.hash==='#'+entry.target.id));});},{rootMargin:'0px 0px -65% 0px'});document.querySelectorAll('article h2, article h3').forEach(h=>observer.observe(h));}

// Search stays in the browser and only uses the generated article whitelist.
const searchDialog = document.querySelector('#search-dialog');
const searchInput = document.querySelector('#search-input');
const searchResults = document.querySelector('#search-results');
const searchStatus = document.querySelector('#search-status');
const searchOpen = document.querySelector('.search-open');
function openSearch() { searchDialog.showModal(); searchInput.focus(); }
searchOpen.addEventListener('click', openSearch);
document.querySelector('.search-close').addEventListener('click', () => searchDialog.close());
searchDialog.addEventListener('close', () => searchOpen.focus());
searchDialog.addEventListener('keydown', event => {
  if (event.key === 'Escape') { event.preventDefault(); searchDialog.close(); }
});
document.addEventListener('keydown', event => {
  if (event.key === '/' && !event.ctrlKey && !event.metaKey && !event.altKey &&
      !event.target.closest('input, textarea, select, [contenteditable]') && !searchDialog.open) {
    event.preventDefault(); openSearch();
  }
});
function markMatches(parent, text, terms) {
  const lower = text.toLocaleLowerCase();
  let position = 0;
  while (position < text.length) {
    let next = text.length, size = 0;
    for (const term of terms) {
      const found = lower.indexOf(term, position);
      if (found >= 0 && (found < next || (found === next && term.length > size))) {
        next = found; size = term.length;
      }
    }
    parent.append(document.createTextNode(text.slice(position, next)));
    if (!size) break;
    const mark = document.createElement('mark');
    mark.textContent = text.slice(next, next + size); parent.append(mark);
    position = next + size;
  }
}
searchInput.addEventListener('input', () => {
  searchResults.replaceChildren();
  const terms = [...new Set(searchInput.value.trim().toLocaleLowerCase().split(/\s+/).filter(Boolean))];
  if (!terms.length) { searchStatus.textContent = '输入关键词开始搜索'; return; }
  if (!Array.isArray(window.blogSearchIndex)) { searchStatus.textContent = '搜索索引加载失败，请刷新页面重试。'; return; }
  const matches = window.blogSearchIndex.filter(item => {
    const text = (item.title + ' ' + item.text).toLocaleLowerCase();
    return terms.every(term => text.includes(term));
  }).sort((a, b) => terms.filter(t => b.title.toLocaleLowerCase().includes(t)).length - terms.filter(t => a.title.toLocaleLowerCase().includes(t)).length);
  searchStatus.textContent = matches.length ? `找到 ${matches.length} 篇文章` : '没有找到匹配文章，试试更短的关键词。';
  for (const item of matches) {
    const li = document.createElement('li');
    const link = document.createElement('a'); link.href = item.url;
    const title = document.createElement('strong'); markMatches(title, item.title, terms);
    const excerpt = document.createElement('p');
    const lower = item.text.toLocaleLowerCase();
    const positions = terms.map(t => lower.indexOf(t)).filter(i => i >= 0);
    const start = Math.max(0, (positions.length ? Math.min(...positions) : 0) - 45);
    const snippet = (start ? '…' : '') + item.text.slice(start, start + 180) + (item.text.length > start + 180 ? '…' : '');
    markMatches(excerpt, snippet, terms); link.append(title, excerpt); li.append(link); searchResults.append(li);
  }
});
