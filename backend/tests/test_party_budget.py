import copy,unittest
from unittest.mock import patch,AsyncMock
from app.services import budget,party

class BudgetTests(unittest.TestCase):
 def plan(self):return [{'day':1,'activities':[{'ticket_price':20}], 'meals':[{'estimated_cost':10}]}]
 def test_shared_car_costs_are_split_but_personal_costs_are_not(self):
  meta={'travelers':4,'transportation':'租车自驾','rental':{'daily_eur':40,'source':'test','note':''}}
  with patch.object(budget,'_legs',return_value=[100]):b=budget.sum_budget(self.plan(),1,meta,None,None)
  self.assertEqual(b['detail']['group_totals']['transport'],67)
  self.assertEqual(b['transport'],16.75);self.assertEqual(b['tickets'],20);self.assertEqual(b['food'],10)
  self.assertEqual(b['total'],46.75);self.assertEqual(b['detail']['group_totals']['total'],187)
  car=b['detail']['transport'];self.assertEqual(car['fuel'],11);self.assertEqual(car['parking'],16);self.assertEqual(car['rental'],40)
 def test_large_party_requires_multiple_cars(self):
  with patch.object(budget,'_legs',return_value=[100]):b=budget.sum_budget(self.plan(),1,{'travelers':8,'transportation':'租车自驾','rental':{'daily_eur':40}},None,None)
  self.assertEqual(b['detail']['party']['vehicles'],2);self.assertEqual(b['detail']['group_totals']['transport'],134);self.assertEqual(b['transport'],16.75)
 def test_public_transport_remains_per_person_and_uses_combined_day_pass(self):
  day={'day':1,'activities':[],'meals':[],'transit_start':{'mode':'transit','cost':2.4},'transit_end':{'mode':'transit','cost':2.4}}
  with patch.object(budget,'_legs',return_value=[2,2,2]):b=budget.sum_budget([day],1,{'travelers':4,'transportation':'公共交通'},None,None)
  self.assertEqual(b['transport'],7.5);self.assertEqual(b['detail']['group_totals']['transport'],30)
 def test_existing_group_route_price_is_not_multiplied_twice(self):
  day={'day':1,'activities':[],'transit_start':{'kind':'arrival','mode':'transit','cost':80,'route_choice':{'passengers':4}}}
  with patch.object(budget,'_legs',return_value=[]):b=budget.sum_budget([day],1,{'travelers':4},None,None)
  self.assertEqual(b['transport'],20);self.assertEqual(b['detail']['group_totals']['transport'],80)
 def test_long_distance_fuel_tolls_and_parking_are_shared_once(self):
  day={'day':1,'activities':[],'transit_start':{'kind':'arrival','mode':'drive','cost':160,'distance_km':1000}}
  with patch.object(budget,'_legs',return_value=[]):b=budget.sum_budget([day],1,{'travelers':4,'transportation':'自驾'},None,None)
  self.assertEqual(b['transport'],44);self.assertEqual(b['detail']['transport']['fuel'],110);self.assertEqual(b['detail']['transport']['tolls'],50);self.assertEqual(b['detail']['transport']['parking'],16)
 def test_explicit_hotel_commutes_replace_implicit_commutes(self):
  day={'day':1,'activities':[],'transit_start':{'mode':'drive','cost':1},'transit_end':{'mode':'drive','cost':1}}
  with patch.object(budget,'_legs',return_value=[]) as legs:budget.sum_budget([day],1,{'travelers':2,'stay_name':'Hotel','stay_lat':41.9,'stay_lng':12.49},None,None)
  self.assertTrue(legs.call_args.args[2]);self.assertTrue(legs.call_args.args[3])
 def test_hotel_uses_channel_mean_room_count_and_nights(self):
  m={'travelers':4,'rooms':2,'stay_name':'Hotel','start_date':'2027-01-01','end_date':'2027-01-04'}
  q={'ok':True,'occupancy_verified':True,'adults':4,'rooms':2,'check_in':m['start_date'],'check_out':m['end_date'],'price_unit':'per_room_per_night','per_night_mean':150,'per_night_min':10}
  l=budget.lodging_from(m,3,q,{})
  self.assertEqual(l['total'],900);self.assertEqual(l['per_person_total'],225);self.assertEqual(l['confidence'],'quote')
 def test_wrong_occupancy_and_dates_never_become_real_quotes(self):
  m={'travelers':4,'rooms':2,'stay_name':'Hotel','start_date':'2027-01-01','end_date':'2027-01-04'}
  q={'ok':True,'occupancy_verified':True,'adults':1,'rooms':1,'check_in':m['start_date'],'check_out':m['end_date'],'per_night_mean':10,'price_unit':'per_room_per_night'}
  l=budget.lodging_from(m,3,q,{'ok':True,'confidence':'range','per_night':100})
  self.assertEqual(l['confidence'],'range');self.assertEqual(l['total'],600);self.assertFalse(l['occupancy_verified'])
 def test_wrong_party_city_sample_cannot_be_labelled_as_dated_mean(self):
  meta={'travelers':4,'rooms':2,'start_date':'2027-01-01','end_date':'2027-01-03'}
  cp={'ok':True,'confidence':'quote_sample','occupancy_verified':True,'adults':2,'rooms':1,'check_in':'2027-01-01','check_out':'2027-01-03','per_night':100}
  result=budget.lodging_from(meta,2,{},cp)
  self.assertEqual(result['confidence'],'estimate');self.assertFalse(result['occupancy_verified'])
 def test_fallback_also_scales_rooms_and_is_explicitly_estimated(self):
  l=budget.lodging_from({'travelers':5},2,{},{});self.assertEqual(l['rooms'],3);self.assertEqual(l['total'],450);self.assertEqual(l['confidence'],'estimate')
 def test_legacy_presentation_does_not_mutate_saved_budget_or_activities(self):
  original={'days':2,'itinerary':self.plan(),'trip_meta':{'travelers':4},'total_budget':{'detail':{'lodging':{'nights':1,'per_night':100,'total':100,'confidence':'quote'}}}}
  stored=copy.deepcopy(original);view=dict(original);budget.present_legacy(view)
  self.assertEqual(original,stored);self.assertEqual(view['total_budget']['lodging'],50);self.assertTrue(view['total_budget']['detail']['needs_price_refresh'])

class BuildTests(unittest.IsolatedAsyncioTestCase):
 def p(self):return {'location':'Rome','days':3,'itinerary':[{'day':i+1,'title':'Rome','activities':[{'name':'stop','latitude':41.9,'longitude':12.49}]} for i in range(3)]}
 async def test_each_actual_hotel_block_is_quoted_for_its_own_dates_and_party(self):
  p=self.p();m={'travelers':4,'rooms':2,'start_date':'2027-01-01','stays':[{'night':1,'name':'A','lat':41.9,'lng':12.49,'kind':'hotel'},{'night':2,'name':'B','lat':41.9,'lng':12.49,'kind':'hotel'}]}
  calls=[]
  async def prices(tool,args):
   calls.append((tool,args));return {'single':2.4} if tool=='transit_fares' else {'ok':True,'occupancy_verified':True,'currency':'EUR','price_unit':'per_room_per_night','per_night_mean':100,'adults':args['adults'],'rooms':args['rooms'],'check_in':args['check_in'],'check_out':args['check_out']}
  with patch.object(budget,'_acall',prices),patch.object(budget.tp,'build'):b=await budget.build_budget(p,m)
  quotes=[a for t,a in calls if t=='hotel_quote'];self.assertEqual(len(quotes),2)
  self.assertEqual([(q['check_in'],q['check_out']) for q in quotes],[('2027-01-01','2027-01-02'),('2027-01-02','2027-01-03')])
  self.assertTrue(all(q['adults']==4 and q['rooms']==2 for q in quotes));self.assertEqual(b['detail']['lodging']['total'],400);self.assertEqual(b['lodging'],100)
 async def test_reuse_is_invalidated_by_party_changes(self):
  p=self.p();m={'travelers':2,'start_date':'2027-01-01'}
  with patch.object(budget,'_acall',new=AsyncMock(return_value={})),patch.object(budget.tp,'build'):old=await budget.build_budget(p,m)
  with patch.object(budget,'_acall',new=AsyncMock(return_value={})) as prices,patch.object(budget.tp,'build'):
   await budget.build_budget(p,m,reuse=old);prices.assert_not_awaited()
   await budget.build_budget(p,{**m,'travelers':4},reuse=old);self.assertTrue(prices.await_count>0)

if __name__=='__main__':unittest.main()
