import copy,unittest
from unittest.mock import patch,AsyncMock
from app.agents import final_review,refine
from app.agents.context import PlanningContext

def payload():return {'location':'Test','days':8,'itinerary':[{'day':i+1,'title':'City','activities':[{'name':f'Stop {i}','latitude':41.9,'longitude':12.49,'time':'10:00-11:00'}],'meals':[]} for i in range(8)],'trip_meta':{}}
def clean():return {'status':'ok','model':'test','score':99,'summary':'checked','verdict':'pass','issues':[]}
class LongReviewTests(unittest.IsolatedAsyncioTestCase):
 async def test_final_audit_runs_twice_and_keeps_conflicts(self):
  p=payload();before=copy.deepcopy(p);a=clean();b={**clean(),'score':70,'issues':[{'day':3,'severity':'high','type':'timing','message':'换城时间不足','fix':'缩短游览'}]}
  with patch.object(final_review.reviewer,'review_itinerary',new=AsyncMock(side_effect=[a,b])) as review,patch.object(final_review,'get_llm_router'),patch.object(final_review,'get_model',return_value='test'):
   result=await final_review.review_payload(p,{})
  self.assertEqual(review.await_count,2);self.assertEqual(result['score'],70);self.assertEqual(result['quality_gate']['state'],'needs_attention');self.assertEqual(p,before)
 async def test_even_a_clean_high_score_gets_a_second_long_trip_pass(self):
  p=payload();ctx=PlanningContext(location='Test',days=8)
  info={'fingerprint':'fixed','checks':[],'notes':[],'hours_unresolved':[]}
  with patch.object(refine,'prepare',side_effect=lambda *args:copy.deepcopy(info)),patch.object(refine.reviewer,'settings',return_value={'max_rounds':0,'target_score':85,'max_revisions':1,'total_timeout_seconds':30}),patch.object(refine.reviewer,'review_itinerary',new=AsyncMock(side_effect=[clean(),clean()])) as review,patch.object(refine,'get_llm_router'),patch.object(refine,'get_model',return_value='test'):
   result=await refine.refine_plan(ctx,p,p['itinerary'],[],None,'Test',8,'','')
  self.assertEqual(review.await_count,2);self.assertEqual(len(result[2]['rounds']),2);self.assertEqual(result[2]['quality_gate']['passes'],2)
 async def test_code_conflicts_enter_revision_even_when_model_gives_99(self):
  p=payload();ctx=PlanningContext(location='Test',days=8)
  info={'fingerprint':'fixed','checks':[],'notes':[],'hours_unresolved':[]}
  first={**copy.deepcopy(info),'checks':[{'day':1,'code':'overlap','message':'Day 1 时间重叠'}]}
  with patch.object(refine,'prepare',side_effect=[first,copy.deepcopy(info)]),patch.object(refine.reviewer,'settings',return_value={'max_rounds':0,'target_score':85,'max_revisions':1,'total_timeout_seconds':30}),patch.object(refine.reviewer,'review_itinerary',new=AsyncMock(side_effect=[clean(),clean()])),patch.object(refine,'_revise',new=AsyncMock(return_value=(p['itinerary'],[],[1]))) as revise,patch.object(refine,'get_llm_router'),patch.object(refine,'get_model',return_value='test'):
   await refine.refine_plan(ctx,p,p['itinerary'],[],None,'Test',8,'','')
  revise.assert_awaited_once();self.assertIn('时间重叠',revise.call_args.args[2][1]['feedback'])
 async def test_accommodation_budget_uses_confirmed_city_blocks(self):
  from app.services import budget
  p=payload();meta={'stay_blocks':[{'city':'Rome','night_start':1,'night_end':2},{'city':'Florence','night_start':3,'night_end':4},{'city':'Venice','night_start':5,'night_end':5},{'city':'Milan','night_start':6,'night_end':7}]}
  calls=[]
  async def prices(tool,args):
   calls.append((tool,args));return {'single':3} if tool=='transit_fares' else {'ok':True,'per_night':100,'confidence':'range'}
  with patch.object(budget,'_acall',prices),patch.object(budget.tp,'build'):
   result=await budget.build_budget(p,meta)
  self.assertEqual([args['city'] for tool,args in calls if tool=='city_hotel_prices'],['Rome','Florence','Venice','Milan'])
  self.assertEqual(result['detail']['lodging']['nights'],7);self.assertEqual(result['detail']['lodging']['total'],700)

if __name__=='__main__':unittest.main()

