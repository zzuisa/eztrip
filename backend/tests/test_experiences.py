import copy,unittest
from unittest.mock import Mock,AsyncMock,patch
from app.services import experiences as e,transit_plan as tp,route_compare as rc
from app.agents.context import PlanningContext
from app.agents.composer import ensure_day_completeness

def spot(name,lat=45.46,lng=9.19,kind='tourist_attraction'):
 return {'name':name,'lat':lat,'lng':lng,'primary_type':kind,'formatted_address':'test'}
class PolicyTests(unittest.TestCase):
 def test_guidance_examples_do_not_select_spa_or_ski_for_everyone(self):
  p=e.policy(e.prompt({'mode':'balanced','interests':[]}));self.assertEqual(p['interests'],[])
  self.assertEqual(e.policy(e.prompt({'mode':'balanced','interests':['spa']}))['interests'],['spa'])
 def test_culture_depth_respected_while_balanced_detects_repetitive_museums(self):
  day={'day':1,'activities':[{'name':f'Museum {i}','time':f'{9+i*2:02}:00-{11+i*2:02}:00'} for i in range(3)]}
  self.assertTrue(e.diversity_issues([day],e.prompt({'mode':'balanced'})))
  self.assertEqual(e.diversity_issues([day],e.prompt({'mode':'culture'})),[])
 def test_half_day_spa_does_not_get_padded_with_three_museums(self):
  spa={**spot('Actual Spa',kind='spa'),'experience_priority':True,'experience_category':'spa','source_url':'https://example.org/spa','seasonality_note':'需确认预约','suggested_stay_minutes':180}
  ctx=PlanningContext(location='Milan',days=2)
  result=ensure_day_completeness({'activities':[{'name':'Actual Spa','time':'14:00-17:00','description':'Spa'}],'meals':[]},2,[spa,spot('Museum')],ctx)
  self.assertEqual(len(result['activities']),1);self.assertEqual(result['activities'][0]['source_url'],spa['source_url'])
 def test_fallback_queries_do_not_search_prompt_metadata_or_private_origin(self):
  from app.services.itinerary_utils import _build_theme_fallbacks
  queries,_=_build_theme_fallbacks('Milan',1,'',[],e.prompt({'mode':'balanced'})+'；交通约束：来自Private Home Address')
  self.assertFalse(any('experience:' in q or 'Private Home' in q for q in queries))
 def test_model_cannot_fabricate_an_experience_source(self):
  result=e.enrich_day({'activities':[{'name':'Museum','source_url':'https://invented.example','experience_category':'spa'}]},[spot('Museum')],'')
  self.assertNotIn('source_url',result['activities'][0])
 def test_traditional_chinese_museum_names_are_detected(self):
  self.assertTrue(e.museum({'name':'米蘭考古博物館'}))
 def test_unread_url_invented_name_and_closed_venue_are_not_evidence(self):
  pages=[{'url':'https://example.org','text':'Known Spa open 2026-12-24 2026-12-31'}]
  for c in [{'name':'Invented','url':'https://example.org','category':'spa'}, {'name':'Known Spa','url':'https://other.org','category':'spa'},{'name':'Known Spa','url':'https://example.org','category':'spa','availability':'closed'}]:self.assertFalse(e.eligible(c,pages,'2026-12-24','2026-12-31'))
class ResearchTests(unittest.IsolatedAsyncioTestCase):
 def ctx(self):
  c=PlanningContext(location='Italy',days=4,start_date='2026-12-24',preferences=e.prompt({'mode':'balanced','interests':['spa']}))
  c.attractions_by_day={1:[spot('Rome A',41.9,12.49)],2:[spot('Rome B',41.9,12.49)],3:[spot('Milan A')],4:[spot('Milan B')]};return c
 async def test_mcp_search_then_fetch_then_geo_checks_and_city_specific_day(self):
  ctx=self.ctx();ctx.attractions_by_day[1].append(spot('Actual Spa',kind='spa'));calls=[]
  def call(tool,args):
   calls.append((tool,args));return {'results':[{'title':'Official','url':'https://example.org/spa'}]} if tool=='web_search' else {'text':'Actual Spa official visitor information'}
  async def extract(ctx,pages):return [{'name':'Actual Spa','url':'https://example.org/spa','category':'spa'}]
  service=Mock();service.search_places.return_value=[spot('Actual Spa',kind='spa')]
  await e.research(ctx,service,call=call,extract=extract)
  self.assertEqual([x[0] for x in calls],['web_search','web_search','fetch_page']);self.assertEqual(ctx.experience['status'],'researched')
  chosen=[d for d,items in ctx.attractions_by_day.items() if any(a.get('experience_priority') for a in items)]
  self.assertEqual(len(chosen),1);self.assertIn(chosen[0],(3,4));self.assertTrue(ctx.experience['sources'])
  # Research evidence must survive global candidate deduplication.
  from app.agents.composer import assign_days
  assigned=assign_days(ctx)
  self.assertTrue(any(a.get('experience_priority') for items in assigned.values() for a in items))
 async def test_far_venue_is_not_inserted(self):
  ctx=self.ctx()
  def call(t,a):return {'results':[{'url':'https://example.org/spa'}]} if t=='web_search' else {'text':'Actual Spa'}
  service=Mock();service.search_places.return_value=[spot('Actual Spa',50,3)]
  await e.research(ctx,service,call,AsyncMock(return_value=[{'name':'Actual Spa','url':'https://example.org/spa','category':'spa'}]))
  self.assertFalse(any(a.get('experience_priority') for a in ctx.all_attractions()))
 async def test_seasonal_venue_without_dates_stays_optional(self):
  ctx=self.ctx();ctx.preferences=e.prompt({'mode':'playful','interests':['skating']})
  def call(t,a):return {'results':[{'url':'https://example.org/rink'}]} if t=='web_search' else {'text':'Actual Rink winter ice skating'}
  service=Mock();service.search_places.return_value=[spot('Actual Rink',kind='ice_skating_rink')]
  await e.research(ctx,service,call,AsyncMock(return_value=[{'name':'Actual Rink','url':'https://example.org/rink','category':'skating'}]))
  self.assertIn('Actual Rink',ctx.experience['optional_venues']);self.assertFalse(any(a.get('experience_priority') for a in ctx.all_attractions()))
 async def test_mcp_failure_is_honest_and_keeps_existing_itinerary_candidates(self):
  ctx=self.ctx();before=copy.deepcopy(ctx.attractions_by_day)
  def call(t,a):raise RuntimeError('offline')
  await e.research(ctx,Mock(),call,AsyncMock())
  self.assertEqual(ctx.experience['status'],'unavailable');self.assertEqual(before,ctx.attractions_by_day)
class TransportTests(unittest.TestCase):
 def test_public_transport_does_not_turn_into_flight_based_on_distance(self):
  self.assertEqual(tp._intercity_mode('公共交通',1200,{}),'train')
  self.assertEqual(tp._intercity_mode('公共交通',1200,{'longhaul_mode':'flight'}),'flight')
  self.assertEqual(tp._intercity_mode('公共交通',230,{'longhaul_mode':'flight'}),'train')
  self.assertEqual(tp._intercity_mode('租车自驾',1200,{'longhaul_mode':'flight'}),'drive')
 def test_chosen_overnight_route_is_labelled_next_day_and_conflict_remains(self):
  leg={'kind':'arrival','from':{'lat':51,'lng':6},'to':{'lat':41,'lng':12},'minutes':100,'mode':'flight'}
  opt={'kind':'transit','price':100,'passengers':3,'duration_min':1106,'depart':'11:51','arrive':'06:05'}
  p={'route_choices':{'1:transit_start':{'sig':rc.sig_of(leg),'opt':opt}}}
  self.assertTrue(rc.apply_choice(p,1,'transit_start',leg,first_start=13*60));self.assertTrue(leg['arrive'].startswith('次日'));self.assertEqual(leg['arrival_day_offset'],1);self.assertTrue(leg['late_min']>0)
 def test_projected_transport_recalculates_v3_budget_without_mixing_flight_costs(self):
  from app.services import budget
  p={'days':1,'transport_projection':True,'trip_meta':{'travelers':2},'itinerary':[{'day':1,'activities':[],'transit_end':{'mode':'train','cost':100,'intercity':True}}], 'total_budget':{'transport':10,'total':10,'detail':{'version':3,'party':{'travelers':2},'fares':{}}}}
  budget.present_legacy(p);self.assertEqual(p['total_budget']['transport'],100);self.assertEqual(p['total_budget']['detail']['group_totals']['transport'],200)
 def test_legacy_flight_projection_does_not_mutate_original_activities(self):
  p={'itinerary':[{'day':1,'activities':[{'name':'Milan','latitude':45.46,'longitude':9.19,'time':'10:00-11:00'}],'meals':[], 'transit_end':{'mode':'flight'}}], 'trip_meta':{'transportation':'公共交通','origin':'Dusseldorf','origin_lat':51.2,'origin_lng':6.7},'warnings':[]}
  old=copy.deepcopy(p);view=dict(p);tp.present_transport(view)
  self.assertEqual(p,old);self.assertEqual(view['itinerary'][0]['transit_end']['mode'],'train');self.assertEqual(view['itinerary'][0]['activities'],old['itinerary'][0]['activities'])
if __name__=='__main__':unittest.main()
