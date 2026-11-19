"""Refresh route-derived text atomically; no network/LLM inside the store lock."""
from .itinerary_edit import ordered_items, parse_range
from .route_service import get_route_service, haversine_m, straight_leg


def point(item):
    try:
        lat, lng = float(item['latitude']), float(item['longitude'])
        return (lat, lng) if -90 <= lat <= 90 and -180 <= lng <= 180 else None
    except (KeyError, TypeError, ValueError):
        return None


def mode_for(a, b, meta):
    if haversine_m(a, b) <= 1600:
        return 'walking'
    if meta.get('driving_strategy') == 'park_ride':
        return 'transit'
    return 'driving' if any(x in str(meta.get('transportation') or '') for x in ('自驾', '租车', '开车')) else 'transit'


def rebuild(payload, old_itinerary=None):
    meta, svc, places = payload.get('trip_meta') or {}, get_route_service(), []
    for index, day in enumerate(payload.get('itinerary') or []):
        rows = ordered_items(day)
        names = [r['item']['name'] for r in rows]
        old = old_itinerary[index] if old_itinerary and index < len(old_itinerary) else None
        signature = lambda d: [(r['item'].get('name'), r['item'].get('time'), point(r['item'])) for r in ordered_items(d)]
        if old is None or signature(old) != signature(day):
            day['title'] = (' → '.join(names[:3]) + ('等' if len(names) > 3 else '')) if names else '自由安排'
            day['route_summary'] = ' → '.join(names) if names else '当天暂无活动，可继续添加地点。'
            for key in ('description', 'summary', 'arrangement_reason'):
                if key in day:
                    day[key] = day['route_summary']
        previous = None
        for row in rows:
            item = row['item']
            item.pop('route_desc', None)
            item.pop('route_connection', None)
            if previous:
                a, b = point(previous), point(item)
                prefix = '从%s前往%s' % (previous['name'], item['name'])
                if a is None or b is None:
                    item['route_desc'] = prefix + '；地点坐标待确认，请核实交通与所需时间。'
                else:
                    mode = mode_for(a, b, meta)
                    leg = svc.cached(svc.key(a, b, mode)) if mode != 'transit' else None
                    leg = leg or straight_leg(a, b, mode)
                    estimated = leg.get('provider') != 'mapbox'
                    minutes = max(1, round(leg['duration_s'] / 60))
                    km = leg['distance_m'] / 1000
                    info = {'from': previous['name'], 'to': item['name'], 'mode': mode, 'distance_m': leg['distance_m'], 'provider': leg['provider']}
                    if mode == 'transit':
                        text = '%s；公共交通，直线约 %.1f 公里，实际班次与耗时待查询。' % (prefix, km)
                    else:
                        info['duration_s'] = leg['duration_s']
                        text = '%s；%s%s约 %d 分钟、%.1f 公里%s。' % (prefix, '估算' if estimated else '', {'walking': '步行', 'driving': '驾车'}[mode], minutes, km, '，以实际路线为准' if estimated else '')
                    start, _ = parse_range(item.get('time'))
                    _, end = parse_range(previous.get('time'))
                    if mode != 'transit' and start is not None and end is not None and start - end < minutes:
                        text += '当前活动间隔不足，请调整时间。'
                        info['time_conflict'] = True
                    item['route_desc'], item['route_connection'] = text, info
            previous = item
            if not row['is_meal']:
                places.append(item)
    if 'attractions' in payload:
        payload['attractions'] = list({p['name']: p for p in places}.values())
    payload['route_sync_v'], payload['review_stale'] = 1, True
    payload['review'] = {'status': 'pending', 'verdict': 'revise', 'issues': [], 'quality_gate': {'state': 'needs_attention', 'summary': '行程已调整，正在重新评审交通、时间和活动安排。'}}
    payload['planning_status'] = 'needs_attention'
    if payload.get('story'):
        payload['story_stale'] = True
