# AI Infra 个人博客

GitHub Pages 博客工程，目标仓库为 `ChrisFang1999/aiinfra-notes`。正文唯一人工维护来源是正式 AI_Infra 知识库。本工程维护页面、发布适配和构建流程。

## 本地运行

需要 Python 3.10+，从本目录运行：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3 脚本/构建.py preview --source "/正式知识库/AI_Infra"
python3 -m http.server 8765 --bind 127.0.0.1 --directory 本地预览
```

访问 http://127.0.0.1:8765 。也可直接用浏览器打开 `本地预览/index.html`；文件方式下复制代码可能受浏览器限制。修改知识库后重新执行 preview，再刷新页面。预览输出、审核记录和截图均已忽略，不应加入 Git。

## 方案

采用 Markdown → 静态 HTML → GitHub Pages，Python 只在构建时运行。当前两篇文章不需要前端应用框架；固定版本的 Markdown 渲染器支持表格、代码高亮，原生 JS 提供复制与目录定位。页面使用相对资源链接，兼容个人站点根路径与项目站点子路径。

与文档框架相比，该方案依赖少、发布白名单清晰，但全文搜索、复杂内容集合等需要后续增加。随内容增长可迁移至成熟静态文档框架；正文 Markdown、稳定文档 id 与发布审核规则继续保留。

GitHub Pages 支持由自定义 Actions 构建并上传静态产物：[官方说明](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages)。本站按此配置，未使用其他托管服务。

## 内容与公开边界

白名单目前只有训练报错 SOP 和详细解释。个人学习记录不进入构建；没有递归复制知识库。两篇适配后的正文已获用户公开授权，源文档为 public/draft，公开资格与编辑状态分别记录。目标仓库为 `ChrisFang1999/aiinfra-notes`。预览本身不代表线上发布。

适配规则：两篇文档互链转换为稳定网址；知识库首页链接映射到网站首页；学习记录链接改成未公开提示；内部工作总结的资料条目整行移除。技术正文不改写。其他未知链接、未经审查图片将阻止构建；原始 HTML 按文本显示。链接白名单并不能识别全部敏感文字，公开前仍需逐篇人工审阅。

网站不会访问公司资料链接。关于检测阈值、工具能力和经验范围的公开资格，请查看本地审核记录；未经用户确认不得据“候选”身份发布。

## 维护与发布

详见 [维护说明](维护说明.md)。先运行：

```bash
python3 -m unittest discover -s 测试
```

公开构建目前应被拦截：

```bash
python3 脚本/构建.py public
```

搜索、批注、自测与学习进度暂未实现。未来学习数据单独存储，关联文档 id 和版本；不写回教程正文。
