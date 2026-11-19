import copy, unittest
from unittest.mock import Mock,patch,AsyncMock
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.services import route_sync
from app.api.routes import itinerary_edit as api
from tests.test_party_budget_api import Store


def activity(name,time,lat=41.9,lng=12.49):
 return dict(name=name,time=time,latitude=lat,longitude=lng,description='venue facts',route_desc='obsolete predecessor',image_url='https://example.org/img.jpg')

class SyncTests(unittest.TestCase):
 def setUp(self):
  self.svc=Mock();self.svc.cached.return_value=None
  self.p=patch.object(route_sync,'get_route_service',return_value=self.svc);self.p.start()
 def tearDown(self):self.p.stop()
 def test_reorder_removes_old_predecessor_and_synchronizes_titles_and_fallback_places(self):
  old=[dict(day=1,title='old',route_summary='old',activities=[activity('A','09:00-10:00'),activity('B','10:30-11:30')],meals=[])]
  new=copy.deepcopy(old);new[0]['activities']=[activity('B','09:00-10:00'),activity('A','10:30-11:30')]
  payload={'itinerary':new,'trip_meta':{},'attractions':[{'name':'removed'}],'story':{'title':'old'}};route_sync.rebuild(payload,old)
  self.assertNotIn('route_desc',new[0]['activities'][0]);self.assertIn('从B前往A',new[0]['activities'][1]['route_desc']);self.assertEqual(new[0]['title'],'B → A');self.assertEqual([p['name'] for p in payload['attractions']],['B','A']);self.assertTrue(payload['story_stale']);self.assertEqual(old[0]['title'],'old')
 def test_missing_coordinates_do_not_reuse_stale_distances(self):
  a,b=activity('A','09:00'),activity('B','10:00');b.pop('longitude');p={'itinerary':[{'activities':[a,b]}]};route_sync.rebuild(p)
  self.assertIn('坐标待确认',b['route_desc']);self.assertNotIn('route_connection',b)
 def test_public_transit_does_not_claim_road_duration_as_a_timetable(self):
  a,b=activity('A','09:00'),activity('B','10:00',42.5,13)
  route_sync.rebuild({'itinerary':[{'activities':[a,b]}],'trip_meta':{'transportation':'公共交通'}})
  self.assertEqual(b['route_connection']['mode'],'transit');self.assertNotIn('duration_s',b['route_connection']);self.assertIn('耗时待查询',b['route_desc'])
 def test_save_returns_authoritative_route_snapshot_and_stale_revision_cannot_overwrite(self):
  store=Store();store.record['payload']['itinerary']=[{'day':1,'title':'old','activities':[activity('A','09:00'),activity('B','10:00')],'meals':[]}];store.record['payload']['days']=1
  app=FastAPI();app.include_router(api.router,prefix='/api');client=TestClient(app)
  patches=[patch.object(api,'get_travel_plan_store',return_value=store),patch.object(api,'_require_editor'),patch.object(api,'_consume'),patch.object(api,'_schedule_review'),patch.object(api,'_geocode_missing',new=AsyncMock(return_value=[]))]
  for p in patches:p.start()
  try:
   body={'rev':3,'days':[{'day':1,'activities':[activity('B','09:00'),activity('A','10:00')],'meals':[]}]}
   res=client.put('/api/travel-plan/results/test/itinerary',json=body);self.assertEqual(res.status_code,200,res.text);data=res.json();self.assertEqual(data['rev'],4);self.assertEqual(data['data']['itinerary'][0]['title'],'B → A');self.assertIn('从B前往A',data['data']['itinerary'][0]['activities'][1]['route_desc']);self.assertTrue(data['data']['review_stale']);self.assertEqual(client.put('/api/travel-plan/results/test/itinerary',json=body).status_code,409)
  finally:
   for p in reversed(patches):p.stop()
if __name__=='__main__':unittest.main()
