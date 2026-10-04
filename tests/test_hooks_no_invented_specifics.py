import pathlib,ast,random,unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]
class HookTests(unittest.TestCase):
    def test_no_unsupported_stat_hook_or_filler(self):
        s=(ROOT/'long-videos/longform_prompt.py').read_text();tree=ast.parse(s);vals={}
        for n in tree.body:
            if isinstance(n,ast.Assign):
                for t in n.targets:
                    if isinstance(t,ast.Name) and t.id in ('HOOK_TEMPLATES','HOOK_FILLERS','HOOK_STYLES'):vals[t.id]=ast.literal_eval(n.value)
        self.assertNotIn('percent',vals['HOOK_FILLERS']);self.assertNotIn('surprising_stat',vals['HOOK_STYLES'])
        for template in vals['HOOK_TEMPLATES']['qualitative_contrast']:
            self.assertNotIn('%',template);self.assertNotIn('Studies show',template);self.assertNotIn('{percent}',template)
        self.assertIn('FACTUAL_GENERATION_RULE',s);self.assertNotIn('cite a specific statistic or research finding',s)
    def test_prompts_demand_context_not_invented_numbers(self):
        s=(ROOT/'long-videos/longform_prompt.py').read_text();self.assertNotIn('a real number, a named person, a specific date, a place, or a study citation',s);self.assertIn('quotation is optional only when supplied in topic context',s)
        s=(ROOT/'long-videos/multi_llm_pipeline.py').read_text();self.assertNotIn('Include specific numbers, dates, examples.',s);self.assertNotIn('Add real numbers, dates, named examples.',s);self.assertIn('FACTUAL_GENERATION_RULE',s)
if __name__=='__main__':unittest.main()
