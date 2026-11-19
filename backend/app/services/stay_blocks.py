"""Contiguous overnight blocks, derived from itinerary geography; no model calls.

Night n is the night following day n. The final travel day has no overnight.
A proposal is read-only until the editor explicitly confirms every block.
"""
from __future__ import annotations
import copy
import hashlib
import math
import re
from datetime import date,timedelta
from collections import defaultdict
from .stay_advisor import km

MAX_NIGHTS=14

def point(item):
    try:
        a=float(item.get('lat',item.get('latitude')));b=float(item.get('lng',item.get('longitude')))
        if math.isfinite(a) and math.isfinite(b) and -90<=a<=90 and -180<=b<=180 and (a or b):return (a,b)
    except (ValueError,TypeError):pass
    return None

def _center(points):return (sum(p[0] for p in points)/len(points),sum(p[1] for p in points)/len(points))

def day_center(day):
    points=[p for a in (day.get('activities') or []) if isinstance(a,dict) and (p:=point(a))]
    if not points:points=[p for a in (day.get('meals') or []) if isinstance(a,dict) and (p:=point(a))]
    if not points:return None
    # A single outlying meal / stop must not move an entire city's accommodation.
    anchor=max(points,key=lambda p:sum(km(p,q)<45 for q in points))
    return _center([p for p in points if km(anchor,p)<45])

def _label(day, fallback):
    if day.get('city'):return str(day['city'])[:60]
    title=re.sub(r'^(?:Day\s*\d+|第[\d一二三四五六七八九十]+天)[\s｜|:：·—-]*','',str(day.get('title') or ''),flags=re.I)
    city=re.split(r'市中心|历史中心|古城|老城|梵蒂冈|核心|城市|文艺复兴|运河|：|｜|与|及|综合|中心|周边|[·|]',title)[0].strip()
    if 1<len(city)<=12 and not re.search(r'游览|主题|之旅|漫步|艺术|博物馆',city):return city
    return fallback

def _date(meta, night):
    try:return (date.fromisoformat(str(meta.get('start_date') or ''))+timedelta(days=night-1)).isoformat()
    except (ValueError,TypeError):return None

def area_choice(area, center):
    stats=area.get('stats') or {};p=point(stats)
    if not p:return None
    distance=km(center,p)
    if distance>55:return None
    name=str(area.get('name') or '')[:120]
    if not name:return None
    return {'id':'area-'+hashlib.sha256((name+str(p)).encode()).hexdigest()[:12],
            'name':name,'lat':p[0],'lng':p[1],'kind':'area','why':str(area.get('why') or '靠近本段游览区域'),
            'transit':str(area.get('transit') or ''),'distance_km':round(distance,1),
            'source':'saved_recommendation','query':str(area.get('query') or name)}

def propose(payload, rev=0):
    days=[d for d in (payload.get('itinerary') or []) if isinstance(d,dict)];total=max(0,len(days)-1)
    meta=payload.get('trip_meta') or {};areas=list((payload.get('stay') or {}).get('areas') or [])
    centers=[day_center(d) for d in days]
    groups=[]
    for i in range(total):
        center=centers[i]
        if center is None:center=next((p for p in centers[i+1:] if p),None) or next((p for p in reversed(centers[:i]) if p),None)
        if groups and center and groups[-1]['center'] and km(tuple(groups[-1]['center']),center)<55:
            groups[-1]['night_end']=i+1;groups[-1]['day_indices'].append(i)
        else:
            fallback=f'第{i+1}站'
            groups.append({'id':f'stay-{len(groups)+1}','city':_label(days[i],fallback),'night_start':i+1,'night_end':i+1,
                           'center':list(center) if center else None,'day_indices':[i]})
    saved={}
    for s in meta.get('stays') or []:
        try:
            n=int(s.get('night'))
            if 1<=n<=total and s.get('name') and point(s):saved[n]=s
        except (TypeError,ValueError,AttributeError):pass
    for group in groups:
        labels=[_label(days[i],group['city']) for i in group['day_indices']]
        shortest=min(labels,key=len)
        if len(shortest)>=2 and all(x.startswith(shortest) for x in labels):group['city']=shortest
        a,b=group['night_start'],group['night_end'];center=group['center'];group.update(nights=b-a+1,check_in=_date(meta,a),check_out=_date(meta,b+1))
        group['areas']=[c for area in areas if center and (c:=area_choice(area,center))]
        cached=(payload.get('stay_recommendations') or {}).get(group['id'])
        if cached and cached.get('city')==group['city'] and cached.get('rev')==rev:
            group['areas']=[c for area in cached.get('areas') or [] if center and (c:=area_choice(area,center))] or group['areas']
        values=[saved.get(n) for n in range(a,b+1)]
        if all(values) and len({(s['name'],s['lat'],s['lng']) for s in values})==1:
            group['selection']={k:values[0].get(k) for k in ('name','lat','lng','kind')}
        if not group['areas'] and center:
            # A transparent route-centre option, not a fabricated named neighbourhood.
            group['areas']=[{'id':'route-center','name':group['city']+' · 游览中心周边','lat':center[0],'lng':center[1],
                             'kind':'area','why':'按本段真实行程地点计算的中心，可先确定住宿区域，酒店稍后再订。',
                             'source':'itinerary_center','query':group['city']}]
        group['can_recommend']=bool(center)
    # Existing hotel assignments can differ from the recommendation: preserve them
    # as editable runs rather than silently overwriting them on open.
    saved_blocks=[]
    if len(saved)==total and total:
        for n in range(1,total+1):
            s=saved[n];same=saved_blocks and all(saved_blocks[-1]['selection'].get(k)==s.get(k) for k in ('name','lat','lng','kind'))
            if same:saved_blocks[-1]['night_end']=n
            else:
                group=next((g for g in groups if g['night_start']<=n<=g['night_end']),{})
                saved_blocks.append({'id':f'custom-{n}','city':group.get('city','住宿'),'night_start':n,'night_end':n,
                                     'selection':{k:s.get(k) for k in ('name','lat','lng','kind')},'areas':copy.deepcopy(group.get('areas') or [])})
        for b in saved_blocks:b.update(nights=b['night_end']-b['night_start']+1,check_in=_date(meta,b['night_start']),check_out=_date(meta,b['night_end']+1))
    return {'rev':rev,'total_nights':total,'start_date':meta.get('start_date'),'blocks':groups,'saved_blocks':saved_blocks,
            'complete':len(saved)==total,'proposal':'按城市连住，减少换房与搬运行李；可拖动分界调整入住范围。',
            'review':payload.get('review'),'planning_status':payload.get('planning_status')}

def expand(blocks, total):
    if not 0<=total<=MAX_NIGHTS:raise ValueError('住宿晚数超出支持范围')
    if not isinstance(blocks,list) or len(blocks)>MAX_NIGHTS:raise ValueError('住宿分段无效')
    result=[];seen=set();clean=[]
    for raw in sorted(blocks,key=lambda b:int(b.get('night_start',0))):
        try:
            a,b=raw['night_start'],raw['night_end']
            if isinstance(a,bool) or isinstance(b,bool) or not isinstance(a,int) or not isinstance(b,int) or not 1<=a<=b<=total:raise ValueError('入住范围无效')
            name=re.sub(r'[\r\n\t]',' ',str(raw.get('name') or '')).strip()[:120];p=point(raw)
            if not name or not p:raise ValueError('请为每段选择住宿区域或酒店')
            kind=raw.get('kind') or 'area'
            if kind not in ('area','hotel'):raise ValueError('住宿类型无效')
            for n in range(a,b+1):
                if n in seen:raise ValueError('住宿日期重叠，请调整时间条')
                seen.add(n);result.append({'night':n,'name':name,'lat':p[0],'lng':p[1],'kind':kind})
            clean.append({'night_start':a,'night_end':b,'name':name,'lat':p[0],'lng':p[1],'kind':kind,'city':str(raw.get('city') or '')[:60]})
        except (KeyError,TypeError):raise ValueError('住宿分段信息不完整')
    if seen!=set(range(1,total+1)):raise ValueError('还有未安排的住宿晚数，请完成所有分段')
    return result,clean
