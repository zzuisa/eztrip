import unittest
from unittest.mock import patch,Mock
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.api.routes import stay,itinerary_edit

def place(name,lat=41.9,lng=12.49,types=None):
 return {'id':name,'displayName':{'text':name},'location':{'latitude':lat,'longitude':lng},
         'types':types or ['hotel','lodging'],'rating':4.5,'userRatingCount':100}

class HotelSearchTests(unittest.TestCase):
 def setUp(self):
  app=FastAPI();app.include_router(stay.router,prefix='/api');self.client=TestClient(app)
 def test_only_real_local_accommodation_is_returned(self):
  search=Mock();search.search.return_value=[place('Rome hotel'),place('Far hotel',45.46,9.19),place('Museum',types=['museum'])]
  with patch.object(stay.sa,'get_hotel_search',return_value=search),patch.object(itinerary_edit,'_consume') as quota:
   r=self.client.get('/api/travel-plan/hotels/search',params={'city':'Rome','q':'Centro','lat':41.9,'lng':12.49})
  self.assertEqual(r.status_code,200,r.text);self.assertEqual([p['name'] for p in r.json()['items']],['Rome hotel'])
  self.assertFalse(r.json()['availability_checked']);quota.assert_called_once()
 def test_manual_city_search_does_not_need_coordinates(self):
  search=Mock();search.search.return_value=[place('Rome hotel')]
  with patch.object(stay.sa,'get_hotel_search',return_value=search),patch.object(itinerary_edit,'_consume'):
   r=self.client.get('/api/travel-plan/hotels/search',params={'city':'Rome','q':'hotel'})
  self.assertEqual(r.status_code,200);self.assertNotIn('avg_km',r.json()['items'][0]);self.assertIsNone(search.search.call_args.args[2])
 def test_partial_coordinates_rejected_before_provider_call(self):
  with patch.object(stay.sa,'get_hotel_search') as search:
   r=self.client.get('/api/travel-plan/hotels/search',params={'city':'Rome','lat':41.9})
  self.assertEqual(r.status_code,422);search.assert_not_called()
 def test_provider_error_is_redacted(self):
  with patch.object(stay.sa,'get_hotel_search',side_effect=RuntimeError('secret provider detail')),patch.object(itinerary_edit,'_consume'):
   r=self.client.get('/api/travel-plan/hotels/search',params={'city':'Rome'})
  self.assertEqual(r.status_code,502);self.assertNotIn('secret',r.text)

if __name__=='__main__':unittest.main()
