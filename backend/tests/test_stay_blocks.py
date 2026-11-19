import unittest,copy
from app.services import stay_blocks as sb,long_review,weather
from app.agents import reviewer

def trip():
 cities=[('罗马',41.9,12.49),('罗马',41.91,12.48),('佛罗伦萨',43.77,11.25),('佛罗伦萨',43.78,11.25),('威尼斯',45.44,12.33),('威尼斯',45.45,12.34),('米兰',45.46,9.19),('米兰',45.47,9.19)]
 return {'location':'意大利','days':8,'trip_meta':{'start_date':'2026-12-24'},'itinerary':[{'day':i+1,'title':f'Day {i+1}｜{c}历史中心综合游览','activities':[{'name':'A','latitude':a,'longitude':b,'time':'10:00-11:00'}],'meals':[]} for i,(c,a,b) in enumerate(cities)]}
class StayBlocksTests(unittest.TestCase):
 def test_four_city_eight_day_trip_needs_four_choices_for_seven_nights(self):
  p=trip();before=copy.deepcopy(p);r=sb.propose(p,3)
  self.assertEqual([b['city'] for b in r['blocks']],['罗马','佛罗伦萨','威尼斯','米兰'])
  self.assertEqual([(b['night_start'],b['night_end']) for b in r['blocks']],[(1,2),(3,4),(5,6),(7,7)])
  self.assertEqual(r['total_nights'],7);self.assertEqual(r['blocks'][-1]['check_out'],'2026-12-31');self.assertEqual(p,before)
  self.assertEqual(r['blocks'][-1]['areas'][0]['source'],'itinerary_center')
 def test_areas_from_other_cities_are_not_offered(self):
  p=trip();p['stay']={'areas':[{'name':'Monti','stats':{'latitude':41.9,'longitude':12.49},'why':'就近住宿'},{'name':'Milan','stats':{'latitude':45.46,'longitude':9.19}}]}
  r=sb.propose(p);self.assertEqual(r['blocks'][0]['areas'][0]['name'],'Monti');self.assertEqual(r['blocks'][-1]['areas'][0]['name'],'Milan')
 def test_confirm_expands_and_preserves_boundaries(self):
  blocks=[{'night_start':a,'night_end':b,'name':city,'lat':lat,'lng':lng,'kind':'area'} for a,b,city,lat,lng in [(1,2,'Rome',41.9,12.49),(3,4,'Florence',43.77,11.25),(5,5,'Venice',45.44,12.33),(6,7,'Milan',45.46,9.19)]]
  values,clean=sb.expand(blocks,7);self.assertEqual([s['night'] for s in values],list(range(1,8)));self.assertEqual(values[5]['name'],'Milan');self.assertEqual(len(clean),4)
 def test_overlaps_gaps_missing_coordinates_and_infinite_values_rejected(self):
  base={'night_start':1,'night_end':7,'name':'Rome','lat':41.9,'lng':12.49}
  for blocks in [[{**base,'night_end':3},{**base,'night_start':3}], [{**base,'night_end':3},{**base,'night_start':5}], [{**base,'lat':None}], [{**base,'lng':float('nan')}], [{**base,'night_end':8}], [{**base,'name':''}]]:
   with self.subTest(blocks=blocks),self.assertRaises(ValueError):sb.expand(blocks,7)
 def test_existing_nightly_choices_are_retained_as_runs(self):
  p=trip();p['trip_meta']['stays']=[{'night':n,'name':'Chosen','lat':41.9,'lng':12.49,'kind':'hotel'} for n in range(1,8)]
  r=sb.propose(p);self.assertTrue(r['complete']);self.assertEqual(len(r['saved_blocks']),1);self.assertEqual(r['saved_blocks'][0]['selection']['name'],'Chosen')
 def test_one_day_has_no_overnight(self):
  p=trip();p['itinerary']=p['itinerary'][:1];r=sb.propose(p);self.assertEqual(r['total_nights'],0);self.assertEqual(r['blocks'],[])
 def test_cached_recommendations_must_match_revision(self):
  p=trip();p['stay_recommendations']={'stay-1':{'rev':4,'city':'罗马','areas':[{'name':'Saved','stats':{'latitude':41.9,'longitude':12.49}}]}}
  self.assertNotEqual(sb.propose(p,5)['blocks'][0]['areas'][0]['name'],'Saved');self.assertEqual(sb.propose(p,4)['blocks'][0]['areas'][0]['name'],'Saved')
class ReviewTests(unittest.TestCase):
 def test_long_policy_requires_more_time_rounds_and_two_passes(self):
  cfg=long_review.policy(8,{'max_rounds':2,'target_score':85,'max_revisions':6,'total_timeout_seconds':200,'timeout_seconds':90})
  self.assertGreaterEqual(cfg['max_rounds'],4);self.assertEqual(cfg['min_passes'],2);self.assertEqual(cfg['max_revisions'],8);self.assertEqual(cfg['target_score'],90)
 def test_high_score_never_overrides_severe_conflicts(self):
  p=trip();r={'status':'ok','score':99,'issues':[{'severity':'high','type':'timing'}]};long_review.apply(r,p,p['trip_meta'],2);self.assertEqual(r['quality_gate']['state'],'needs_attention');self.assertEqual(r['verdict'],'revise')
 def test_single_review_cannot_claim_long_trip_passed(self):
  p=trip();r={'status':'ok','score':99,'issues':[]};long_review.apply(r,p,p['trip_meta'],1);self.assertEqual(r['quality_gate']['state'],'unverified')
 def test_failed_review_gate_survives_public_projection(self):
  r={'status':'failed','model':'test','quality_gate':{'state':'unverified','policy':long_review.VERSION}};self.assertEqual(reviewer.public_view(r)['quality_gate']['state'],'unverified')
 def test_unknown_weather_removes_only_generated_daily_empty_alerts(self):
  p={'weather':{'days':[{'date':f'2026-12-{n}','status':'unavailable'} for n in range(24,32)]},'warnings':['重要的交通提醒']+[f'2026-12-{n} 天气：无法获取' for n in range(24,32)]}
  weather.compact_presentation(p);self.assertEqual(p['warnings'],['重要的交通提醒'])
if __name__=='__main__':unittest.main()
