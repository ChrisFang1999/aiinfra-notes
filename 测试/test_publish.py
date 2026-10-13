import copy, importlib.util, unittest
from pathlib import Path
spec=importlib.util.spec_from_file_location('blog',Path(__file__).resolve().parents[1]/'脚本/构建.py')
blog=importlib.util.module_from_spec(spec);spec.loader.exec_module(blog)
class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.pages={ident:{'body':'# 示例\n','source_sha256':'abc','status':'draft','visibility':'public','publication_approval':'approved','publication_scope':'adapted_body_only','deployment_status':'not_published'} for ident,_,_ in blog.DOCS}
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
    def test_search_only_indexes_allowlisted_adapted_bodies(self):
        pages={ident:{'title':'公开教程', 'body':blog.adapt('[学习记录](学习记录与待补充.md)\n- [工作总结中的诊断能力](../internal.md)\n## GPU Hang\n每 30 秒采样。')} for ident,_,_ in blog.DOCS}
        pages['private-note']={'title':'私有笔记','body':'PRIVATE_SENTINEL'}
        index=blog.search_index(pages)
        self.assertEqual(len(index),len(blog.DOCS))
        text=str(index)
        self.assertIn('每 30 秒采样',text)
        for excluded in ['PRIVATE_SENTINEL','internal.md','学习记录与待补充.md']:
            self.assertNotIn(excluded,text)
if __name__=='__main__':unittest.main()
