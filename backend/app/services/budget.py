"""行程预算（纯代码汇总，不让 LLM 算账）：交通按「每一段路程 + 出行方式」、住宿按「晚数 × 单价」。

价格来源是 travel_prices MCP（经 LiteLLM 网关）：
- 酒店实时报价（已选定住宿且有日期）= confidence "quote"；
- 城市酒店价位区间 = "range"；参考表兜底 = "estimate"。
MCP 不可用时全部回退到内置参考价，预算照常给出但标注为估算。保存的行程只存结果与来源，旧行程没有这些字段也能正常显示。
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import copy
import math
import os
import re
import threading
from typing import Any, Dict, List, Optional, Tuple

from . import stay_plan as sp
from . import transit_plan as tp
from .journey import rental_budget
from .party import counts as party_counts
from .itinerary_edit import item_start

CALL_TIMEOUT = 35.0
FUEL_PER_KM = 0.11
DEFAULT_FARES = {"single": 2.4, "day_pass": 7.5, "taxi_base": 3.5, "taxi_per_km": 1.6, "parking_per_day": 16,
                 "confidence": "low", "basis": "region_default"}

_gw = None
_gw_lock = threading.Lock()


def _gateway():
    global _gw
    with _gw_lock:
        if _gw is None:
            from ..tools.db.mcp_gateway import DbMcpGateway
            _gw = DbMcpGateway(server=os.getenv("EZTRIP_PRICES_MCP_SERVER", "travel_prices"))
        return _gw


def mcp_available() -> bool:
    if os.getenv("EZTRIP_PRICES_MCP", "1") == "0":
        return False
    from ..config import get_settings
    s = get_settings()
    return bool(s.enable_db_mcp and (s.db_mcp_sse_url or "").rstrip("/").lower().endswith("/mcp"))


def call_prices(tool: str, args: Dict[str, Any]) -> Dict[str, Any]:
    raw = _gateway().call_tool(tool, args)
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except Exception:  # noqa: BLE001
        return {}
    return data if isinstance(data, dict) else {}


async def _acall(tool: str, args: Dict[str, Any]) -> Dict[str, Any]:
    if not mcp_available():
        return {}
    try:
        return await asyncio.wait_for(asyncio.to_thread(call_prices, tool, args), CALL_TIMEOUT)
    except Exception as e:  # noqa: BLE001
        print(f"[budget] prices mcp {tool} failed: {type(e).__name__}: {e}")
        return {}


# ---------------------------------------------------------------- 出行方式 / 交通成本


def mode_for(pref: str, dist_km: float) -> str:
    """按用户的出行偏好 + 单段路程，决定这一段怎么走。"""
    p = pref or ""
    if "步行" in p:
        return "walk" if dist_km <= 3.0 else "transit"
    if any(x in p for x in ("自驾", "开车", "租车", "驾车")):
        return "walk" if dist_km <= 0.4 else "drive"
    if "混合" in p:
        return "walk" if dist_km <= 1.0 else ("taxi" if 8.0 < dist_km <= tp.TAXI_MAX_KM else "transit")
    return "walk" if dist_km <= 0.9 else "transit"  # 公共交通（默认）


def _legs(day: Dict[str, Any], stay: Optional[Tuple[float, float]], skip_start: bool = False, skip_end: bool = False) -> List[float]:
    pts = sp.day_points(day)
    if stay and pts and sp.km(stay, pts[0]) > tp.STAY_NEAR_KM:
        stay = None  # 多地点切换：当天第一站离住宿很远，住宿不是这一天的起点（城际路段另计）
    seq = ([stay] if stay and not skip_start else []) + pts + ([stay] if stay and pts and not skip_end else [])
    return [sp.road_km(seq[i], seq[i + 1]) for i in range(len(seq) - 1) if seq[i] != seq[i + 1]]


def transport_for_day(day: Dict[str, Any], pref: str, fares: Dict[str, Any], stay: Optional[Tuple[float, float]], skip_start: bool = False, skip_end: bool = False) -> Dict[str, Any]:
    cost, rides, walk_km, taxi_km, drive_km, taxi_n = 0.0, 0, 0.0, 0.0, 0.0, 0
    for d in _legs(day, stay, skip_start, skip_end):
        m = mode_for(pref, d)
        if m == "walk":
            walk_km += d
        elif m == "transit":
            rides += 1
        elif m == "taxi":
            taxi_km += d
            taxi_n += 1
            cost += fares["taxi_base"] + fares["taxi_per_km"] * d
        else:
            drive_km += d
    transit_cost = rides * fares["single"]
    day_pass = False
    if rides and transit_cost > fares["day_pass"]:
        transit_cost, day_pass = fares["day_pass"], True  # 买日票更划算
    taxi_cost=cost
    cost += transit_cost
    cost += drive_km * FUEL_PER_KM
    parking = fares["parking_per_day"] if drive_km >= 1.0 else 0.0
    cost += parking
    return {"cost": cost, "taxi_cost":taxi_cost, "fuel":drive_km*FUEL_PER_KM, "rides": rides, "day_pass": day_pass, "walk_km": walk_km, "taxi_km": taxi_km, "taxi_n": taxi_n,
            "drive_km": drive_km, "parking": parking}


# ---------------------------------------------------------------- 住宿


def nights_of(meta: Dict[str, Any], days: int) -> int:
    try:
        a, b = dt.date.fromisoformat(str(meta.get("start_date"))[:10]), dt.date.fromisoformat(str(meta.get("end_date"))[:10])
        if b > a:
            return min((b - a).days, 30)
    except Exception:  # noqa: BLE001
        pass
    return max(0, min(int(days or 1) - 1, 30))


def tier_of(accommodation: str) -> str:
    a = accommodation or ""
    if "豪华" in a:
        return "high"
    if "舒适" in a or "民宿" in a:
        return "mid"
    return "budget"


def city_of(location: str) -> str:
    s = re.split(r"[/,，、+＋;；|→]| 和 | and ", str(location or ""))[0].strip()
    return s[:40]


def _verified_price(data, meta, party):
    return bool(data.get('ok') and data.get('occupancy_verified') and data.get('adults')==party['travelers']
                and data.get('rooms')==party['rooms'] and data.get('check_in')==meta.get('start_date')
                and data.get('check_out')==meta.get('end_date') and data.get('currency','EUR')=='EUR')


def lodging_from(meta, nights, q, city_prices):
    if nights <= 0:return None
    party=party_counts(meta);rooms=party['rooms'];cp=city_prices or {};q=q or {}
    exact=_verified_price(q,meta,party) and q.get('price_unit')=='per_room_per_night' and positive(q.get('per_night_mean'))>0
    sample=_verified_price(cp,meta,party) and cp.get('confidence')=='quote_sample' and positive(cp.get('per_night'))>0
    if exact:
        pn=positive(q['per_night_mean']);confidence='quote';source=q.get('source') or 'Xotelo';note=q.get('note','')
    elif cp.get('ok') and positive(cp.get('per_night')):
        pn=positive(cp['per_night']);confidence='quote_sample' if sample else cp.get('confidence','estimate') if cp.get('confidence') in ('range','estimate') else 'estimate'
        if confidence not in ('quote_sample','range','estimate'):confidence='estimate'
        source=cp.get('source','');note=cp.get('note') or '同城同档位酒店参考价，非已选酒店实价'
    else:
        pn={'budget':75,'mid':135,'high':270}[tier_of(str(meta.get('accommodation') or ''))]
        confidence='estimate';source='内置参考价';note='未获取所选日期和人数的报价，按每间每晚参考价估算'
    total=round(pn*rooms*nights,2)
    if not exact and sp.clean_stay(meta.get('stay_name')):note='未获取该酒店匹配日期与人数的报价；'+note
    return {'nights':nights,'rooms':rooms,'travelers':party['travelers'],'per_room_per_night':round(pn,2),
            'per_night':round(pn*rooms,2),'total':total,'per_person_total':round(total/party['travelers'],2),
            'confidence':confidence,'source':source,'hotel':q.get('hotel','') if exact else '',
            'stay_name':sp.clean_stay(meta.get('stay_name')),'check_in':meta.get('start_date',''),'check_out':meta.get('end_date',''),
            'sample_count':q.get('sample_count',0) if exact else cp.get('sample_count',0) if sample else 0,
            'occupancy_verified':bool(exact or sample),'price_basis':'group','quote_reason':q.get('reason',''),
            'url':q.get('tripadvisor_url','') if exact else '', 'note':note}


def segments_of(plan):
    segs=[x for x in plan.get('segments') or [] if isinstance(x,dict) and x.get('city')]
    return segs if len(segs)>=2 else []


def positive(value):
    try:
        n=float(value or 0)
        return max(0,n) if math.isfinite(n) else 0.0
    except (TypeError,ValueError,OverflowError):return 0.0


def lodging_blocks(plan,meta,nights):
    from . import stay_blocks as sb
    proposal=sb.propose({**plan,'trip_meta':meta})
    groups=proposal.get('blocks') or []
    by_night={int(s['night']):s for s in meta.get('stays') or [] if isinstance(s,dict) and isinstance(s.get('night'),int)}
    explicit=[b for b in meta.get('stay_blocks') or [] if isinstance(b,dict)]
    runs=[]
    for night in range(1,nights+1):
        g=next((b for b in explicit if b.get('night_start',0)<=night<=b.get('night_end',0)),None)
        if not g:g=next((b for b in groups if b['night_start']<=night<=b['night_end']),{})
        city=str(g.get('city') or city_of(plan.get('location') or ''))
        stay=by_night.get(night) or {}
        name=sp.clean_stay(stay.get('name')) if stay.get('kind')=='hotel' else ''
        if not name and meta.get('stay_name'):name=sp.clean_stay(meta['stay_name'])
        if runs and runs[-1]['city']==city and runs[-1]['name']==name:runs[-1]['night_end']=night
        else:runs.append({'city':city,'name':name,'night_start':night,'night_end':night})
    for b in runs:
        b['nights']=b['night_end']-b['night_start']+1
        try:
            start=dt.date.fromisoformat(str(meta.get('start_date') or ''))
            b['check_in']=(start+dt.timedelta(days=b['night_start']-1)).isoformat()
            b['check_out']=(start+dt.timedelta(days=b['night_end'])).isoformat()
        except ValueError:b.update(check_in='',check_out='')
    return runs


def pricing_context(plan,meta,days):
    p=party_counts(meta)
    return {'version':3,'travelers':p['travelers'],'rooms':p['rooms'],'vehicles':p['vehicles'],
            'transportation':meta.get('transportation',''),'rental':meta.get('rental'),
            'accommodation':meta.get('accommodation',''),'start_date':meta.get('start_date',''),'end_date':meta.get('end_date',''),
            'lodging_blocks':lodging_blocks(plan,meta,nights_of(meta,days))}


def _leg_cost(leg,fares):
    """One explicit leg: personal fares and shared vehicle costs stay separate."""
    out={'personal':0.0,'taxi':0.0,'fuel':0.0,'tolls':0.0,'drive_km':0.0,'rides':0}
    if not isinstance(leg,dict):return out
    if leg.get('legs') and not leg.get('route_choice'):
        for sub in leg['legs']:
            for k,v in _leg_cost(sub,fares).items():out[k]+=v
        return out
    mode=leg.get('mode');cost=positive(leg.get('cost'));choice=leg.get('route_choice') or {}
    if mode in ('walk','walking'):return out
    if mode in ('drive','driving'):
        km=positive(leg.get('distance_km'));c=choice.get('cost') or {}
        fuel=positive(c.get('energy_cost')) if c.get('energy_cost') is not None else min(cost,km*FUEL_PER_KM)
        out.update(fuel=fuel,tolls=max(0,cost-fuel),drive_km=km)
    elif mode=='taxi':out['taxi']=cost
    elif mode in ('transit','train','flight'):
        if choice:
            out['personal']=cost/max(1,positive(choice.get('passengers') or 1))
        elif mode=='transit' and not leg.get('intercity'):
            out['rides']=1
        else:out['personal']=cost
    else:out['personal']=cost
    return out


def sum_budget(itinerary, days, meta, fares, lodging, fares_src=''):
    f={**DEFAULT_FARES,**(fares or {})};party=party_counts(meta);n=party['travelers'];cars=party['vehicles'] or 1
    pref=str(meta.get('transportation') or '');stay=sp.stay_point(meta)
    totals={'transport':0.0,'tickets':0.0,'food':0.0,'lodging':positive((lodging or {}).get('total'))}
    shared={'fuel':0.0,'tolls':0.0,'parking':0.0,'taxi':0.0,'rental':0.0,'public_transport':0.0}
    per_day=[];long_haul=[];drive_km=walk_km=taxi_km=0.0;rides_all=passes=0
    for i,day in enumerate(itinerary):
        ticket=sum(positive(a.get('ticket_price')) for a in day.get('activities') or [] if isinstance(a,dict))
        food=sum(positive(a.get('estimated_cost')) for a in day.get('meals') or [] if isinstance(a,dict))
        ts=day.get('transit_start');te=day.get('transit_end')
        park=meta.get('driving_strategy')=='park_ride' and meta.get('parking_point')
        # Explicit first/last legs replace the corresponding hotel commute.
        tr=transport_for_day(day,'公共交通' if park else pref,f,None if park or meta.get('stays') else stay,
                             skip_start=isinstance(ts,dict),skip_end=isinstance(te,dict))
        local={'personal':0.0,'taxi':tr['taxi_cost'],'fuel':tr['fuel'],'tolls':0.0,'drive_km':tr['drive_km'],'rides':tr['rides']}
        walk_km+=tr['walk_km'];taxi_km+=tr['taxi_km']
        for leg in (ts,te):
            lc=_leg_cost(leg,f)
            for k,v in lc.items():local[k]+=v
            if isinstance(leg,dict) and leg.get('via_stay'):
                pts=sp.day_points(day);p=leg.get('to') or {}
                if pts and p.get('lat') is not None and p.get('lng') is not None:
                    d=sp.road_km((p['lat'],p['lng']),pts[0]);mode=mode_for(pref,d)
                    if mode=='drive':local['fuel']+=d*FUEL_PER_KM;local['drive_km']+=d
                    elif mode=='taxi':local['taxi']+=f['taxi_base']+f['taxi_per_km']*d
                    elif mode=='transit':local['rides']+=1
            if isinstance(leg,dict) and leg.get('kind') in ('arrival','intercity','return'):
                g=lc['personal']*n+(lc['fuel']+lc['tolls'])*cars+lc['taxi']*party['taxi_vehicles']+lc['rides']*f['single']*n
                long_haul.append({'day':day.get('day',i+1),'kind':leg['kind'],'mode':leg.get('mode'),'label':leg.get('mode_label'),
                                  'from':(leg.get('from') or {}).get('name'),'to':(leg.get('to') or {}).get('name'),
                                  'cost':round(g/n,2),'group_total':round(g,2),'confidence':leg.get('confidence','estimate')})
        local_fare=min(local['rides']*f['single'],f['day_pass']) if local['rides'] else 0
        passes+=int(local['rides']*f['single']>f['day_pass']);rides_all+=local['rides']
        public=(local['personal']+local_fare)*n;fuel=local['fuel']*cars;tolls=local['tolls']*cars
        parking=f['parking_per_day']*cars if local['drive_km']>=1 or park or party['vehicles'] and (stay or meta.get('stays')) else 0.0
        taxi=local['taxi']*party['taxi_vehicles'];group_tr=public+fuel+tolls+parking+taxi
        for k,v in [('public_transport',public),('fuel',fuel),('tolls',tolls),('parking',parking),('taxi',taxi)]:shared[k]+=v
        drive_km+=local['drive_km'];totals['tickets']+=ticket*n;totals['food']+=food*n;totals['transport']+=group_tr
        per_day.append({'day':day.get('day',i+1),'transport':round(group_tr/n,2),'tickets':round(ticket,2),'food':round(food,2),
                        'total':round(group_tr/n+ticket+food,2),'group_total':round(group_tr+(ticket+food)*n,2)})
    rental=rental_budget(meta,days)
    if rental:
        rental={**rental,'vehicles':cars,'per_vehicle_total':rental['total'],'total':round(rental['total']*cars,2)}
        rental['per_person_total']=round(rental['total']/n,2);shared['rental']=rental['total'];totals['transport']+=rental['total']
    totals={k:round(v,2) for k,v in totals.items()};totals['total']=round(sum(totals.values()),2)
    per_person={k:round(v/n,2) for k,v in totals.items()}
    notes=['门票、餐饮与公共交通按每人计；酒店按房间计，车辆相关费用按整车计，再按同行人数均摊。']
    if party['rooms_assumed']:notes.append(f"默认每间最多2人，{n}人按{party['rooms']}间房估算，可在费用明细调整。")
    if party['vehicles_assumed']:notes.append(f"车辆暂按5座车估算，共{cars}辆；含行李时请核实车型与座位。")
    if not lodging and nights_of(meta,days)>0:notes.append('住宿费用未计入')
    if not stay and not meta.get('stays'):notes.append('尚未选定住宿，住宿往返交通可能不完整。')
    detail={'version':3,'basis':'per_person','party':party,'group_totals':totals,'per_person':per_person,'per_day':per_day,
            'transport':{'pref':pref,'has_stay':bool(stay or meta.get('stays')),'rides':rides_all,'day_passes':passes,
                         'drive_km':round(drive_km,1),'walk_km':round(walk_km,1),'taxi_km':round(taxi_km,1),
                         'vehicles':party['vehicles'],'single':f['single'],'day_pass':f['day_pass'],
                         **{k:round(v,2) for k,v in shared.items()},'per_person':{k:round(v/n,2) for k,v in shared.items()},
                         'confidence':f.get('confidence','low'),'source':fares_src or '内置交通参考价'},
            'fares':f,'long_haul':long_haul,'notes':notes}
    if lodging:detail['lodging']=lodging
    if rental:detail['rental']=rental;notes.append(rental.get('source','')+'；'+rental.get('note',''))
    return {**per_person,'currency':'EUR','detail':detail}


async def build_budget(plan, meta, reuse=None, adapt=False):
    itinerary=[d for d in plan.get('itinerary') or [] if isinstance(d,dict)]
    days=int(plan.get('days') or len(itinerary) or 1);party=party_counts(meta);context=pricing_context(plan,meta,days)
    if reuse and (reuse.get('detail') or {}).get('pricing_context')==context:
        old=reuse['detail'];tp.build(plan,meta,old.get('fares'))
        result=sum_budget(itinerary,days,meta,old.get('fares'),old.get('lodging'),(old.get('transport') or {}).get('source',''))
        result['detail']['pricing_context']=context;return result
    blocks=context['lodging_blocks'];tier=tier_of(str(meta.get('accommodation') or ''))
    def args(b):return {'city':city_of(b['city']),'check_in':b['check_in'],'check_out':b['check_out'],'adults':party['travelers'],'rooms':party['rooms']}
    jobs={'fares':_acall('transit_fares',{'city':city_of(plan.get('location') or ''),'country':''})}
    for i,b in enumerate(blocks):
        jobs[str(i)]=_acall('hotel_quote',{'hotel_name':b['name'],**args(b)}) if b['name'] else _acall('city_hotel_prices',{'tier':tier,**args(b)})
    got=dict(zip(jobs,await asyncio.gather(*jobs.values())))
    failed={str(i):_acall('city_hotel_prices',{'tier':tier,**args(b)}) for i,b in enumerate(blocks) if b['name'] and not _verified_price(got[str(i)],{'start_date':b['check_in'],'end_date':b['check_out']},party)}
    fallback=dict(zip(failed,await asyncio.gather(*failed.values()))) if failed else {}
    parts=[]
    for i,b in enumerate(blocks):
        bm={**meta,'start_date':b['check_in'],'end_date':b['check_out'],'stay_name':b['name']}
        q=got[str(i)] if b['name'] else {};cp=fallback.get(str(i),{}) if b['name'] else got[str(i)]
        part=lodging_from(bm,b['nights'],q,cp);parts.append({**part,'city':b['city'],'night_start':b['night_start'],'night_end':b['night_end']})
    lodging=None
    if parts:
        total=round(sum(p['total'] for p in parts),2);nights=sum(p['nights'] for p in parts)
        conf=parts[0]['confidence'] if all(p['confidence']==parts[0]['confidence'] for p in parts) else 'mixed'
        lodging={'nights':nights,'rooms':party['rooms'],'travelers':party['travelers'],'total':total,'per_night':round(total/nights,2),
                 'per_room_per_night':round(total/nights/party['rooms'],2),'per_person_total':round(total/party['travelers'],2),
                 'confidence':conf,'source':'按各入住段查询与汇总','by_city':parts,'price_basis':'group',
                 'occupancy_verified':all(p['occupancy_verified'] for p in parts),
                 'note':'各段优先使用所选酒店按日期与人数查询的渠道均价；未获取时使用同城样本或参考估算。'}
    fares=got['fares'] if got['fares'].get('single') else None
    if adapt:
        note=tp.adapt_day1(plan,meta,fares)
        if note:plan['day1_shifted']=True;plan.setdefault('warnings',[]).append(note)
    else:tp.build(plan,meta,fares)
    result=sum_budget(itinerary,days,meta,fares,lodging,(fares or {}).get('source',''))
    result['detail']['pricing_context']=context
    return result


def present_legacy(plan):
    old=plan.get('total_budget') or {};detail=old.get('detail') or {}
    if detail.get('version')==3:
        if plan.get('transport_projection'):
            meta=plan.get('trip_meta') or {}
            refreshed=sum_budget(plan.get('itinerary') or [],int(plan.get('days') or len(plan.get('itinerary') or []) or 1),meta,detail.get('fares'),copy.deepcopy(detail.get('lodging')),(detail.get('transport') or {}).get('source',''))
            refreshed['detail']['transport_projection']=True
            refreshed['detail']['notes'].append('交通费用已按保存的地面偏好换算；实际班次和票价请在地面交通对比中核实。')
            plan['total_budget']=refreshed
        return
    meta=plan.get('trip_meta') or {};party=party_counts(meta);lodging=copy.deepcopy(detail.get('lodging'))
    if not lodging and positive(old.get('lodging')) and nights_of(meta,int(plan.get('days') or 1))>0:
        nights=nights_of(meta,int(plan.get('days') or 1));lodging={'nights':nights,'total':old['lodging'],'per_night':positive(old['lodging'])/nights}
    if lodging:
        lodging['total']=positive(lodging.get('total'))*party['rooms'];lodging['per_night']=positive(lodging.get('per_night'))*party['rooms']
        lodging.update(rooms=party['rooms'],confidence='estimate',occupancy_verified=False,price_basis='group',
                       note='旧版参考住宿价格按房间数换算，尚未重新查询所选日期与人数的酒店报价')
        for p in lodging.get('by_city') or []:
            p['total']=positive(p.get('total'))*party['rooms'];p['per_night']=positive(p.get('per_night'))*party['rooms']
            p.update(confidence='estimate',occupancy_verified=False)
    result=sum_budget(plan.get('itinerary') or [],int(plan.get('days') or len(plan.get('itinerary') or []) or 1),meta,detail.get('fares'),lodging)
    result['detail']['needs_price_refresh']=True;result['detail']['notes'].append('当前为已有参考价的人均换算；点击重新查价获取日期与人数匹配价格。')
    plan['total_budget']=result


def diff_budget(old,new):
    return {k:round(float(new.get(k,0) or 0)-float((old or {}).get(k,0) or 0),2) for k in ('transport','tickets','food','lodging','total')}
