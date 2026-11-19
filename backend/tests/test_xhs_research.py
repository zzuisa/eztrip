import copy,json,unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock,patch
from app.services import xhs_research as x,dining,multi_city
from app.agents.context import PlanningContext
from app.models.schemas import TravelPlanRequest,TravelPlanDay

def feed(name,likes,collections,id='note1234'):
 return {'id':id,'feed_id':id,'xsec_token':'PRIVATE','title':name,'noteCard':{'displayTitle':name,'interactInfo':{'likedCount':likes,'collectedCount':collections}}}
class PureTests(unittest.TestCase):
 def ctx(self):return PlanningContext(location='Düsseldorf',days=2,preferences=dining.prompt({'cuisines':['chinese','french']})+' citywalk；不要博物馆；交通约束：Private Home Address')
 def test_keywords_use_cuisines_and_positive_intents_without_private_addresses(self):
  plan=x.keywords(self.ctx(),'轻松散步');queries=' '.join(q['keyword'] for q in plan['queries']);self.assertIn('中餐',queries);self.assertIn('法餐',queries);self.assertIn('citywalk',queries);self.assertNotIn('博物馆',queries);self.assertNotIn('Private',queries);self.assertNotIn('[dining',queries);self.assertLessEqual(len(plan['queries']),4)
 def test_count_snapshots_support_chinese_units_and_unknown_is_not_zero(self):
  for raw,want in [('1.2万',12000),('1,234',1234),('2w+',20000),('5k',5000),('0',0),('未提供',None),(None,None)]:self.assertEqual(x.count(raw),want)
 def test_relevance_precedes_popularity_then_combined_saves_and_likes(self):
  rows=[feed('巴黎购物','9万','8万','note0001'),feed('杜塞中餐攻略','20','30','note0002'),feed('杜塞中餐攻略','120','100','note0003')]
  ranked=x.rank(rows,['中餐'],'Düsseldorf');self.assertEqual(ranked[0][0]['id'],'note0003');self.assertEqual(ranked[-1][0]['id'],'note0001')
 def test_detail_excludes_comments_from_recommendation_evidence(self):
  self.assertNotIn('not a venue',x.detail_text({'note':{'title':'A','desc':'real guide'},'comments':[{'content':'not a venue'}]}))
 def notes(self):return [{'id':'note1234','title':'杜塞吃饭','text':'杜塞的 China House 可以试试家常菜，附近散步也方便。','geographic_evidence':True,'likes':120,'collections':250,'url':'https://www.xiaohongshu.com/explore/note1234'}]
 def recommendation(self):return {'note_id':'note1234','place_name':'China House','quote':'China House 可以试试家常菜','tip':'可以试试家常菜，饭后在附近散步','kind':'restaurant'}
 def test_only_read_notes_with_literal_place_and_quote_can_be_used(self):
  good=self.recommendation();self.assertEqual(len(x.verified_recommendations({'recommendations':[good]},self.notes())),1)
  for patch in [{'note_id':'made-up'},{'place_name':'Invented Venue'},{'quote':'invented supporting quote'},{'tip':'保证营业到22:00'}]:
   self.assertEqual(x.verified_recommendations({'recommendations':[{**good,**patch}]},self.notes()),[])
 def test_only_adopted_verified_venues_are_marked_with_true_counts(self):
  ctx=self.ctx();ctx.meals_by_day={1:[{'name':'China House','lat':51.2,'lng':6.7}]};ctx.insight={'notes':self.notes(),'recommendations':[self.recommendation()]}
  day={'day':1,'title':'A','route_summary':'B','activities':[],'meals':[{'type':'lunch','name':'China House','time':'12:00-13:00','latitude':51.2,'longitude':6.7,'description':'午餐','route_desc':'步行','estimated_cost':20}]}
  payload={'itinerary':[day]};x.attach(payload,ctx);meal=day['meals'][0];self.assertEqual(meal['xhs_sources'][0]['likes'],120);self.assertIn('攻略建议',meal['description']);self.assertEqual(payload['xhs_research']['used_note_ids'],['note1234']);self.assertNotIn('PRIVATE',json.dumps(payload))
  self.assertEqual(TravelPlanDay(**day).model_dump()['meals'][0]['xhs_sources'][0]['collections'],250)
  meal['name']='Other Restaurant';x.attach(payload,ctx);self.assertNotIn('xhs_sources',meal);self.assertEqual(payload['xhs_research']['used_note_ids'],[])
 def test_model_fabricated_sources_are_removed(self):
  ctx=self.ctx();ctx.insight={};payload={'itinerary':[{'activities':[{'name':'Unknown','xhs_sources':[{'likes':9999}]}]}]};x.attach(payload,ctx);self.assertNotIn('xhs_sources',payload['itinerary'][0]['activities'][0])
 def test_dining_request_and_multicity_preserve_options_and_sources(self):
  r=TravelPlanRequest(location='Paris',dining={'cuisines':['french','chinese']});self.assertEqual(r.dining.cuisines,['french','chinese'])
  results=[{'itinerary':[],'xhs_research':{'selected_notes':[{'id':str(i)}],'used_note_ids':[str(i)]}} for i in range(2)]
  merged=multi_city.merge(results,[{'city':'Paris','days':1},{'city':'Rome','days':1}]);self.assertEqual(len(merged['xhs_research']['selected_notes']),2)

class AsyncTests(unittest.IsolatedAsyncioTestCase):
 async def test_bounded_searches_use_popularity_filters_read_details_and_dedupe(self):
  ctx=PlanningContext(location='Düsseldorf',days=1,preferences=dining.prompt({'cuisines':['chinese']})+' citywalk');calls=[]
  async def dispatch(tool,args):
   calls.append((tool,args))
   if tool=='xhs_search_feeds':return {'available':True,'data':{'feeds':[feed('杜塞中餐 China House','100','200')]}}
   return {'available':True,'data':{'note':{'desc':'杜塞 China House 推荐家常菜，附近适合散步。'}}}
  result=await x.research(ctx,dispatch);self.assertEqual(len(result['notes']),1);self.assertEqual(len([c for c in calls if c[0]=='xhs_feed_detail']),1);self.assertTrue(result['notes'][0]['geographic_evidence']);self.assertEqual(calls[0][1]['filters']['sort_by'],'最多收藏')
 async def test_agent_uses_grounded_notes_json_prompt_and_does_not_repeat_research(self):
  from app.agents import subagents,context
  ctx=PlanningContext(location='Düsseldorf',days=1);context.set_context(ctx)
  note={'id':'note1234','title':'杜塞餐饮','text':'杜塞的 China House 可以试试家常菜，附近散步也方便。','geographic_evidence':True}
  rec={'note_id':'note1234','place_name':'China House','quote':'China House 可以试试家常菜','tip':'可以试试家常菜','kind':'restaurant'}
  router=SimpleNamespace(primary_model='test',generate_json=AsyncMock(return_value=SimpleNamespace(content=json.dumps({'recommendations':[rec]}))))
  with patch.object(x,'research',new=AsyncMock(return_value={'available':True,'notes':[note],'tokens':['中餐'],'queries':[]})) as research,patch.object(subagents,'get_llm_router',return_value=router):
   first=await subagents._xhs_insight('餐饮');second=await subagents._xhs_insight('重复主题')
  self.assertEqual(first['place_names'],['China House']);self.assertEqual(second['place_names'],['China House']);research.assert_awaited_once();self.assertTrue(router.generate_json.await_args.kwargs['user_prompt'].startswith('Return JSON.'))
 async def test_filter_failure_falls_back_once_and_keeps_local_popularity_ranking(self):
  ctx=PlanningContext(location='Düsseldorf',days=1);calls=[]
  async def dispatch(tool,args):
   calls.append((tool,args))
   if tool=='xhs_search_feeds' and 'filters' in args:return {'available':False,'code':'filters_unavailable'}
   if tool=='xhs_search_feeds':return {'available':True,'data':{'feeds':[feed('杜塞餐饮','10','20')]}}
   return {'available':True,'data':{'note':{'desc':'杜塞餐饮与街区散步的详细攻略。'}}}
  with patch.object(x,'_filter_retry_after',0):
   result=await x.research(ctx,dispatch)
  self.assertTrue(result['available']);self.assertEqual(len([c for c in calls if 'filters' in c[1]]),1);self.assertTrue(all(q['ranking_mode']=='returned_results_metrics' for q in result['queries']))
 async def test_unavailable_search_does_not_fail_planning(self):
  ctx=PlanningContext(location='Paris',days=1);result=await x.research(ctx,AsyncMock(return_value={'available':False}));self.assertFalse(result['available'])
