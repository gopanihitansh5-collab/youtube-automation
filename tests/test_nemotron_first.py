import ast,pathlib,unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]
def function(name,context):
 tree=ast.parse((ROOT/'long-videos/multi_llm_pipeline.py').read_text());n=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==name);exec(compile(ast.Module(body=[n],type_ignores=[]),'test','exec'),context);return context[name]
class OrderTests(unittest.TestCase):
 def test_free_nemotron_route_first(self):
  calls=[]
  f=function('_call_free_llm',{'_call_openrouter':lambda *a:(calls.append('router') or ('ok','nemotron')),'_call_groq':lambda *a:calls.append('groq')})
  self.assertEqual(f('prompt'),('ok','nemotron'));self.assertEqual(calls,['router'])
 def test_groq_only_on_router_failure(self):
  calls=[]
  def fail(*a):calls.append('router');raise RuntimeError('unavailable')
  f=function('_call_free_llm',{'_call_openrouter':fail,'_call_groq':lambda *a:(calls.append('groq') or ('ok','groq'))})
  self.assertEqual(f('prompt'),('ok','groq'));self.assertEqual(calls,['router','groq'])
 def test_single_provider_order_and_final_gate_preserved(self):
  s=(ROOT/'long-videos/main_long.py').read_text().split('# Fallback: single-provider chain')[1];self.assertLess(s.index('chain.append(("openrouter-free"'),s.index('chain.append(("groq-gpt-oss"'))
  p=(ROOT/'long-videos/multi_llm_pipeline.py').read_text();self.assertIn('Final Gemini review unavailable or malformed',p);self.assertIn('Final reviewer gate blocked',p)
if __name__=='__main__':unittest.main()
