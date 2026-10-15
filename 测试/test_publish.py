import copy, importlib.util, unittest
from pathlib import Path
spec=importlib.util.spec_from_file_location('blog',Path(__file__).resolve().parents[1]/'脚本/构建.py')
blog=importlib.util.module_from_spec(spec);spec.loader.exec_module(blog)
class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.pages={ident:{'body':'# 示例\n','source_sha256':'abc','status':'draft','visibility':'public','publication_approval':'approved','publication_scope':'adapted_body_only','deployment_status':'not_published'} for ident,_,_ in blog.DOCS}
        self.pages['ddp-training-principles']['publication_scope']='body_images_example_code'
        self.config={'enabled':True,'repository':'example/example.github.io','approved':{ident:{'source_sha256':'abc','body_sha256':blog.digest(d['body'])} for ident,d in self.pages.items()}}
    def test_unapproved_default(self):
        with self.assertRaises(ValueError):blog.check_approval({'enabled':False},self.pages)
    def test_private_unapproved_or_wrong_scope_are_blocked(self):
        for key,value in [('visibility','private'),('publication_approval',''),('publication_scope','raw_source')]:
            pages=copy.deepcopy(self.pages);pages['training-error-sop'][key]=value
            with self.assertRaises(ValueError):blog.check_approval(self.config,pages)
    def test_changed_source_or_body_blocked(self):
        for key in ['source_sha256','body']:
            pages=copy.deepcopy(self.pages);pages['training-error-sop'][key]+='changed'
            with self.assertRaises(ValueError):blog.check_approval(self.config,pages)
    def test_approved_draft_not_yet_deployed_is_allowed(self):blog.check_approval(self.config,self.pages)
    def test_private_link_adaptation(self):
        source='[详细解释](训练报错排查详细解释.md) · [学习记录](学习记录与待补充.md)\n- [工作总结中的诊断能力](../../internal.md)：内部背景\n**技术结论不改写**\n'
        result=blog.adapt(source)
        self.assertNotIn('internal.md',result);self.assertNotIn('学习记录与待补充.md',result)
        self.assertIn('training-error-explanation.html',result);self.assertIn('**技术结论不改写**',result)
    def test_unknown_links_fail_closed(self):
        with self.assertRaises(ValueError):blog.adapt('[内部](https://internal.example/path)')
        with self.assertRaises(ValueError):blog.render('[内部][ref]\n\n[ref]: ../private.md')
    def test_html_is_inert_and_code_preserved(self):
        rendered,_=blog.render('<script>alert(1)</script>\n\n```python\nprint("hello")\n```')
        self.assertNotIn('<script>',rendered);self.assertIn('&lt;script&gt;',rendered)
        self.assertIn('language-python',rendered);self.assertIn('hello',rendered)
    def test_cross_topic_links_and_private_notes(self):
        adapted=blog.adapt('[GPU Hang](../训练报错排查/训练卡住排查：通信等待型GPU_Hang.md) · [学习记录](训练慢排查讨论记录.md)', 'training-slow-explanation')
        self.assertIn('training-hang-communication.html',adapted)
        self.assertNotIn('训练慢排查讨论记录.md',adapted)
        with self.assertRaises(ValueError):blog.adapt('[维护](../../../文档维护记录.md)', 'training-slow-sop')
    def test_mermaid_is_a_diagram_and_unknown_syntax_fails(self):
        diagram="""flowchart TD
A{"日志？"}
A -- 有 --> B["看日志"]
A -- 无 --> C{"平台？"}
C -- 有 --> D["看平台"]
C -- 无 --> E{"Hang？"}
E -- 有 --> F["查堆栈"]
E -- 无 --> G["查其他"]
"""
        output,_=blog.render('```mermaid\n'+diagram+'```\n')
        self.assertIn('<svg ',output)
        self.assertIn('日志？',output)
        self.assertNotIn('<pre',output)
        with self.assertRaises(ValueError):blog.mermaid_svg('flowchart LR\nA-->B')
    def test_search_only_indexes_allowlisted_adapted_bodies(self):
        pages={ident:{'title':'公开教程', 'body':blog.adapt('[学习记录](学习记录与待补充.md)\n- [工作总结中的诊断能力](../internal.md)\n## GPU Hang\n每 30 秒采样。')} for ident,_,_ in blog.DOCS}
        pages['private-note']={'title':'私有笔记','body':'PRIVATE_SENTINEL'}
        index=blog.search_index(pages)
        self.assertEqual(len(index),len(blog.DOCS))
        text=str(index)
        self.assertIn('每 30 秒采样',text)
        for excluded in ['PRIVATE_SENTINEL','internal.md','学习记录与待补充.md']:
            self.assertNotIn(excluded,text)
    def test_ddp_requires_approved_scope_and_version(self):
        pages=copy.deepcopy(self.pages)
        pages['ddp-training-principles']['publication_approval']='pending'
        with self.assertRaises(ValueError): blog.check_approval(self.config,pages)
        pages['ddp-training-principles']['publication_approval']='approved'
        pages['ddp-training-principles']['publication_scope']='adapted_body_only'
        with self.assertRaises(ValueError): blog.check_approval(self.config,pages)
        pages['ddp-training-principles']['publication_scope']='body_images_example_code'
        blog.check_approval(self.config,pages)
        pages['ddp-training-principles']['body']+='changed'
        with self.assertRaises(ValueError): blog.check_approval(self.config,pages)
    def test_ddp_disclosure_and_anchors(self):
        body='## 1. 从 torchrun 启动\n\n[跳转](#1-从-torchrun-启动)\n\n<details>\n<summary>原理说明</summary>\n\n**重要内容**\n\n</details>\n'
        markup,_=blog.render(body,'ddp-training-principles')
        self.assertIn('id="1-从-torchrun-启动"',markup)
        self.assertIn('<details class="article-details">',markup)
        self.assertIn('<strong>重要内容</strong>',markup)
        with self.assertRaises(ValueError): blog.render('<details onclick="alert(1)">x</details>','ddp-training-principles')
    def test_ring_diagram_opens_original(self):
        body='![Ring AllReduce](ddp配图/11_Ring_AllReduce分步图.png)'
        markup,_=blog.render(body,'ddp-training-principles')
        self.assertIn('class="diagram-original"',markup)
        self.assertIn('打开原图放大查看',markup)
        self.assertEqual(markup.count('<img '),1)
if __name__=='__main__':unittest.main()
