import copy,unittest
from unittest.mock import patch,Mock,AsyncMock
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.api.routes import route_compare as api,itinerary_edit
from app.services import route_compare as rc
class RouteApiTests(unittest.TestCase):
 def setUp(self):
  self.leg={'kind':'arrival','mode':'train','intercity':True,'from':{'name':'Dusseldorf','lat':51.2,'lng':6.7},'to':{'name':'Rome','lat':41.9,'lng':12.49}}
  self.record={'rev':4,'payload':{'trip_meta':{'travelers':3,'transportation':'公共交通'},'itinerary':[{'day':1,'activities':[],'transit_start':self.leg}], 'route_compare':{'1:transit_start':{'sig':rc.sig_of(self.leg),'prefs':{'passengers':2},'result':{'options':[{'id':'t1','kind':'transit','passengers':2}]}}}}}
  self.store=Mock();self.store.get.side_effect=lambda _:copy.deepcopy(self.record)
  app=FastAPI();app.include_router(api.router,prefix='/api');self.client=TestClient(app)
  self.patches=[patch.object(api,'get_travel_plan_store',return_value=self.store),patch.object(api,'is_owner',return_value=True),patch.object(api,'can_edit',return_value=False),patch.object(api.rc,'fetch',new=AsyncMock(return_value={'ok':True,'options':[]})),patch.object(api.route_advisor,'advise',new=AsyncMock(return_value={'text':'ground','source':'rule'})),patch.object(itinerary_edit,'_require_editor'),patch.object(itinerary_edit,'_consume')]
  self.mocks=[p.start() for p in self.patches]
 def tearDown(self):
  for p in reversed(self.patches):p.stop()
 def test_default_comparison_uses_saved_party_and_explains_ground_coverage(self):
  r=self.client.post('/api/travel-plan/test/route-compare',json={'day':1,'kind':'transit_start'})
  self.assertEqual(r.status_code,200,r.text);self.assertEqual(self.mocks[3].await_args.args[0]['passengers'],3);self.assertEqual(r.json()['item']['result']['coverage'],'ground_only')
 def test_old_two_person_choice_cannot_be_silently_reapplied_to_three_people(self):
  r=self.client.post('/api/travel-plan/test/route-choose',json={'day':1,'kind':'transit_start','option_id':'t1'})
  self.assertEqual(r.status_code,409,r.text);self.store.update_payload.assert_not_called()
if __name__=='__main__':unittest.main()
