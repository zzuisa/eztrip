import copy,unittest
from unittest.mock import patch,AsyncMock
from fastapi import FastAPI,HTTPException
from fastapi.testclient import TestClient
from app.api.routes import stay,itinerary_edit

class Store:
 def __init__(self):self.record={'rev':3,'payload':{'days':2,'location':'Rome','itinerary':[{'day':1,'activities':[]},{'day':2,'activities':[]}],'trip_meta':{'travelers':2,'transportation':'租车自驾'},'total_budget':{}}}
 def get(self,key):return copy.deepcopy(self.record)
 def update_record(self,key,fn):
  new=copy.deepcopy(self.record)
  if fn(new) is False:return False
  self.record=new;return True
class ApiTests(unittest.TestCase):
 def setUp(self):
  self.store=Store();app=FastAPI();app.include_router(stay.router,prefix='/api');self.client=TestClient(app)
  def editor(request,record):
   if request.headers.get('x-test-editor')!='yes':raise HTTPException(403,'no access')
  self.patchers=[patch.object(stay,'get_travel_plan_store',return_value=self.store),patch.object(itinerary_edit,'_require_editor',editor),patch.object(itinerary_edit,'_consume'),patch.object(stay.budget_svc,'build_budget',new=AsyncMock(return_value={'total':100}))]
  self.mocks=[p.start() for p in self.patchers]
 def tearDown(self):
  for p in reversed(self.patchers):p.stop()
 def post(self,body=None,editor=True):return self.client.post('/api/travel-plan/test/budget/refresh',json=body,headers={'x-test-editor':'yes'} if editor else {})
 def test_party_settings_persist_atomically_without_changing_activities(self):
  old=copy.deepcopy(self.store.record['payload']['itinerary']);r=self.post({'travelers':6,'rooms':3,'vehicle_count':2,'rev':3})
  self.assertEqual(r.status_code,200,r.text);self.assertEqual(r.json()['rev'],4);self.assertEqual(self.store.record['payload']['trip_meta']['travelers'],6);self.assertEqual(self.store.record['payload']['itinerary'],old)
  self.assertEqual(self.mocks[3].await_args.args[1]['rooms'],3)
 def test_shared_viewer_cannot_change_counts_or_call_pricing(self):
  self.assertEqual(self.post({'travelers':4},False).status_code,403);self.mocks[3].assert_not_awaited()
 def test_stale_revision_and_invalid_party_do_not_call_pricing(self):
  for data in [{'rev':2},{'travelers':2,'rooms':4},{'travelers':9,'vehicle_count':1}]:self.assertIn(self.post(data).status_code,(409,422))
  self.mocks[3].assert_not_awaited()
 def test_legacy_null_body_still_refreshes(self):
  self.assertEqual(self.post().status_code,200);self.assertEqual(self.store.record['rev'],3)
 def test_quote_response_without_verified_party_is_not_exposed_as_actual_price(self):
  with patch.object(stay.budget_svc,'_acall',new=AsyncMock(return_value={'ok':True,'per_night_min':10})):
   r=self.client.get('/api/travel-plan/hotels/quote',params={'hotel_name':'Hotel','travelers':4,'rooms':2})
  self.assertEqual(r.status_code,200);self.assertFalse(r.json()['ok'])
if __name__=='__main__':unittest.main()
