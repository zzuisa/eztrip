import copy,unittest
from unittest.mock import patch,AsyncMock,Mock
from fastapi import FastAPI,HTTPException
from fastapi.testclient import TestClient
from app.api.routes import stay,itinerary_edit
from app.services import stay_blocks

class Store:
 def __init__(self):self.record={'rev':3,'payload':{'location':'Test','itinerary':[{'day':n,'activities':[],'meals':[]} for n in range(1,9)],'trip_meta':{},'total_budget':{}}}
 def get(self,key):return copy.deepcopy(self.record)
 def update_record(self,key,fn):
  work=copy.deepcopy(self.record)
  if fn(work) is False:return False
  self.record=work;return True

class ApiTests(unittest.TestCase):
 def setUp(self):
  self.store=Store();app=FastAPI();app.include_router(stay.router,prefix='/api');self.client=TestClient(app)
  def editor(request,rec):
   if request.headers.get('x-test-editor')!='yes':raise HTTPException(403,detail='没有编辑权限')
  self.patches=[patch.object(stay,'get_travel_plan_store',return_value=self.store),patch.object(itinerary_edit,'_require_editor',editor),patch.object(itinerary_edit,'_consume'),patch.object(itinerary_edit,'_schedule_review'),patch.object(stay.budget_svc,'build_budget',new=AsyncMock(return_value={'total':0}))]
  self.mocks=[p.start() for p in self.patches]
  self.blocks=[{'night_start':1,'night_end':4,'name':'First area','lat':41.9,'lng':12.49,'kind':'area'},{'night_start':5,'night_end':7,'name':'Second area','lat':43.77,'lng':11.25,'kind':'area'}]
 def tearDown(self):
  for p in reversed(self.patches):p.stop()
 def post(self,**overrides):return self.client.post('/api/travel-plan/test/stay-set',headers={'x-test-editor':'yes'},json={'rev':3,'blocks':self.blocks,**overrides})
 def test_save_expands_all_nights_once_and_schedules_review(self):
  r=self.post();self.assertEqual(r.status_code,200,r.text);self.assertEqual(r.json()['rev'],4)
  meta=self.store.record['payload']['trip_meta'];self.assertEqual(len(meta['stay_blocks']),2);self.assertEqual([s['night'] for s in meta['stays']],list(range(1,8)))
  self.mocks[3].assert_called_once_with('test')
 def test_missing_overlap_and_empty_name_rejected_without_mutation(self):
  before=copy.deepcopy(self.store.record)
  for blocks in [[self.blocks[0]], [{**self.blocks[0],'night_end':5},self.blocks[1]], [{**self.blocks[0],'name':''},self.blocks[1]]]:
   r=self.post(blocks=blocks);self.assertEqual(r.status_code,422,r.text);self.assertEqual(self.store.record,before)
  self.mocks[2].assert_not_called()
 def test_stale_revision_does_not_recalculate_or_write(self):
  r=self.post(rev=2);self.assertEqual(r.status_code,409);self.mocks[4].assert_not_called();self.assertEqual(self.store.record['rev'],3)
 def test_shared_viewer_cannot_save(self):
  r=self.client.post('/api/travel-plan/test/stay-set',json={'rev':3,'blocks':self.blocks});self.assertEqual(r.status_code,403);self.assertEqual(self.store.record['rev'],3)
 def test_compatible_nightly_payload_matches_blocks(self):
  values,_=stay_blocks.expand(self.blocks,7)
  self.assertEqual(self.post(stays=values).status_code,200)
 def test_inconsistent_compatibility_payload_is_rejected(self):
  values,_=stay_blocks.expand(self.blocks,7);values[0]['name']='different'
  self.assertEqual(self.post(stays=values).status_code,422)
  self.assertEqual(self.store.record['rev'],3)
 def test_four_city_guidance_counts_one_guest_session_and_four_global_calls(self):
  from test_stay_blocks import trip
  self.store.record['payload']=trip()
  class Quota:
   def __init__(self):self.calls=[]
   def consume(self,kind,key,limit):
    if sum(k==kind for k,_ in self.calls)>=limit:raise HTTPException(429,detail='quota')
    self.calls.append((kind,key))
   def refund(self,kind,key):self.calls.remove((kind,key))
  quota=Quota()
  async def build(view,points,pref):
   return {'summary':'test','areas':[{'name':view['location']+' central','stats':{'latitude':points[0]['lat'],'longitude':points[0]['lng']}}]}
  with patch.object(stay,'is_owner',return_value=False),patch.object(stay,'get_quota',return_value=quota),patch.object(stay,'_build',build):
   for n in range(1,5):
    # Give every day's geographic group two points, as the real area recommender requires.
    for day in self.store.record['payload']['itinerary']:
     if len(day['activities'])==1:day['activities'].append({**day['activities'][0],'name':'B'})
    response=self.client.post(f'/api/travel-plan/test/stay-plan/stay-{n}/recommend')
    self.assertEqual(response.status_code,200,response.text)
  self.assertEqual(sum(k=='stay' for k,_ in quota.calls),1)
  self.assertEqual(sum(k=='stay_all' for k,_ in quota.calls),4)
 def test_read_proposal_has_no_model_or_budget_work(self):
  r=self.client.get('/api/travel-plan/test/stay-plan');self.assertEqual(r.status_code,200);self.assertEqual(r.json()['total_nights'],7);self.mocks[4].assert_not_called();self.assertEqual(self.store.record['rev'],3)
if __name__=='__main__':unittest.main()
