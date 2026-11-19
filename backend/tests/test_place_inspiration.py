import tempfile,unittest,json,copy
from pathlib import Path
from unittest.mock import Mock,patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.services.place_inspiration import PlaceInspirationService,cover,aliases
from app.api.routes import place_details as api
from app.services.xiaohongshu_service import XiaohongshuError

class PlaceNotesTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.upstream=Mock();self.service=PlaceInspirationService(self.temp.name,self.upstream)
  self.upstream.search_feeds.return_value={'data':{'feeds':[{'feed_id':'note1234','xsec_token':'PRIVATE_TOKEN','title':'梵高博物馆实用攻略','noteCard':{'interactInfo':{'likedCount':'1.2万','collectedCount':'850'},'cover':{'urlDefault':'https://sns-webpic-qc.xhscdn.com/a.jpg'}}},{'feed_id':'other123','title':'无关城市购物','noteCard':{}}]}}
  self.upstream.get_feed_detail.return_value={'data':{'note':{'title':'梵高博物馆实用攻略','desc':'梵高博物馆参观体验。'+('建议预留足够时间欣赏画作。'*30)},'comments':[{'content':'do not expose comments'}]}}
 def tearDown(self):self.temp.cleanup()
 def test_public_cards_are_related_ranked_and_no_private_tokens_leave_cache(self):
  data=self.service.lookup('Van Gogh Museum','Amsterdam');self.assertEqual(len(data['notes']),1);self.assertEqual(data['notes'][0]['likes'],12000);self.assertTrue(data['notes'][0]['metrics_approximate']);self.assertNotIn('PRIVATE_TOKEN',json.dumps(data));self.assertTrue(self.service.lookup('Van Gogh Museum','Amsterdam')['cached']);self.upstream.search_feeds.assert_called_once()
 def test_short_attributed_preview_is_cached_and_comment_text_is_excluded(self):
  self.service.lookup('Van Gogh Museum','Amsterdam');preview=self.service.preview('Van Gogh Museum','Amsterdam','note1234');self.assertEqual(preview['status'],'available');self.assertLessEqual(len(preview['excerpt'])+len('梵高博物馆实用攻略'),81);self.assertNotIn('comments',preview['excerpt']);self.assertTrue(self.service.preview('Van Gogh Museum','Amsterdam','note1234')['cached']);self.upstream.get_feed_detail.assert_called_once()
 def test_unknown_note_cannot_trigger_upstream_read(self):
  self.service.lookup('Van Gogh Museum','Amsterdam');self.assertEqual(self.service.preview('Van Gogh Museum','Amsterdam','invented')['status'],'expired');self.upstream.get_feed_detail.assert_not_called()
 def test_unsafe_covers_and_street_only_aliases_are_rejected(self):
  for url in ['javascript:alert(1)','https://xhscdn.com.evil.org/a','https://evil.org/a']:self.assertIsNone(cover({'cover':{'urlDefault':url}}))
  self.assertEqual(cover({'cover':{'infoList':None,'urlDefault':'http://sns-webpic-qc.xhscdn.com/a.jpg'}}),'https://sns-webpic-qc.xhscdn.com/a.jpg')
  self.assertIn('Greenwoods',aliases('Greenwoods Singel'));self.assertNotIn('Singel',aliases('Greenwoods Singel'))
 def test_cache_files_are_private_and_malformed_results_do_not_write_tokens_publicly(self):
  data=self.service.lookup('Van Gogh Museum','Amsterdam');p=next(Path(self.temp.name).glob('*.json'));self.assertEqual(p.stat().st_mode&0o777,0o600)
 def test_plan_membership_and_adopted_labels_are_checked_without_editing_trip(self):
  rec={'payload':{'location':'Amsterdam','itinerary':[{'day':1,'activities':[{'name':'Van Gogh Museum','xhs_sources':[{'id':'note1234'}]}],'meals':[]}]}};old=copy.deepcopy(rec)
  app=FastAPI();app.include_router(api.router,prefix='/api');client=TestClient(app)
  with patch('app.services.travel_plan_store.get_travel_plan_store',return_value=Mock(get=lambda _:copy.deepcopy(rec))),patch('app.services.place_inspiration.get_place_inspiration_service',return_value=self.service),patch('app.config.get_settings',return_value=Mock(enable_xiaohongshu_mcp=True)),patch.object(api,'_xhs_quota',return_value=None):
   url='/api/travel-plan/results/test/place-inspiration';r=client.get(url,params={'day':1,'name':'Van Gogh Museum'});self.assertEqual(r.status_code,200);self.assertTrue(r.json()['notes'][0]['adopted']);self.assertEqual(client.get(url,params={'day':1,'name':'Made Up'}).status_code,404);self.assertEqual(client.get(url+'/invented',params={'day':1,'name':'Van Gogh Museum'}).status_code,404)
  self.assertEqual(rec,old)
 def test_quota_does_not_call_upstream_and_errors_preserve_page(self):
  rec={'payload':{'location':'Amsterdam','itinerary':[{'activities':[{'name':'Van Gogh Museum'}]}]}};app=FastAPI();app.include_router(api.router,prefix='/api');client=TestClient(app)
  with patch('app.services.travel_plan_store.get_travel_plan_store',return_value=Mock(get=lambda _:rec)),patch('app.services.place_inspiration.get_place_inspiration_service',return_value=self.service),patch('app.config.get_settings',return_value=Mock(enable_xiaohongshu_mcp=True)),patch.object(api,'_xhs_quota',return_value='quota'):
   response=client.get('/api/travel-plan/results/test/place-inspiration',params={'day':1,'name':'Van Gogh Museum'});self.assertEqual(response.json()['status'],'quota');self.upstream.search_feeds.assert_not_called()
