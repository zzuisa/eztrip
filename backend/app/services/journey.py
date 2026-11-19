"""Structured journey constraints shared by planning, transport and budget.

Rental references are published regional starting prices, never date-specific
quotes. The server owns their amounts; a supplied daily rate is user input.
"""
from .origin import clean_origin

RENTAL_REFERENCES = {
    'sixt': {'name': 'SIXT', 'daily_eur': 55, 'region': '德国', 'url': 'https://www.skyscanner.ie/car-hire/provider-in-country/sixt/germany/673/29475381'},
    'europcar': {'name': 'Europcar', 'daily_eur': 54, 'region': '德国', 'url': 'https://www.skyscanner.ie/car-hire/provider-in-country/europcar/germany/663/29475381'},
    'hertz': {'name': 'Hertz', 'daily_eur': 40, 'region': '德国不来梅 Hansator 门店历史低价', 'url': 'https://www.hertz.com/us/en/location/germany/bremen/brec61'},
}


def metadata(req):
    out = {'stays': [s.model_dump() for s in req.stays],
           'day_windows': [w.model_dump() for w in req.day_windows],
           'experience':req.experience.model_dump(),'dining':req.dining.model_dump(),'longhaul_mode':req.longhaul_mode,'longhaul_timing': req.longhaul_timing, 'travelers': req.travelers, 'rooms':req.rooms, 'vehicle_count':req.vehicle_count}
    total = sum(s.days for s in req.segments) if req.segments else req.days
    out['stay_status'] = 'pending' if total > 1 and not req.stay_name and len(req.stays) < total - 1 else 'confirmed'
    for field in ('destination_lat', 'destination_lng', 'driving_strategy'):
        value = getattr(req, field, None)
        if value is not None:
            out[field] = value
    if req.return_point:
        out['return_point'] = {**req.return_point.model_dump(), 'name': clean_origin(req.return_point.name)}
    elif clean_origin(req.origin) and req.origin_lat is not None and req.origin_lng is not None:
        out['return_point'] = {'name': clean_origin(req.origin), 'lat': req.origin_lat, 'lng': req.origin_lng}
    if req.parking_point:
        out['parking_point'] = {**req.parking_point.model_dump(), 'name': clean_origin(req.parking_point.name)}
    if '租车' in (req.transportation or ''):
        choice = req.rental
        provider = choice.provider if choice else 'sixt'
        ref = RENTAL_REFERENCES[provider]
        manual = choice is not None and choice.daily_eur is not None
        out['rental'] = {**ref, 'provider': provider, 'daily_eur': choice.daily_eur if manual else ref['daily_eur'],
                         'confidence': 'user_quote' if manual else 'reference', 'reference_date': '2026-11-10',
                         'source': '用户填写的平台报价' if manual else '平台公开地区起价参考，非所选日期报价',
                         'note': '不含押金、额外保险、异地还车及跨境附加费；取还车日期、门店与实际报价请在平台核实。'}
    return out


def constraints(req, include_return=True):
    point = req.return_point
    end = clean_origin(point.name if point else req.origin)
    mode = clean_origin(req.transportation) or '公共交通'
    lines = [f'；交通约束：全程优先使用「{mode}」，景点顺序、交通时间及游览时间必须按此安排。']
    if end and include_return:
        lines.append(f'最终返回点为「{end}」，末日（包括一日游）必须预留返回交通与换乘时间，不要默认返回其他地点。')
    if req.driving_strategy == 'park_ride' and req.parking_point:
        park = clean_origin(req.parking_point.name)
        lines.append(f'自驾至「{park}」停车，市内优先公共交通/步行；每次离开市内前先回该停车点取车，停车、换乘和取车均预留时间。不得把车留在别处后直接从景点驾车离开。')
    lines.append('长途交通约束：'+{'ground':'地面公共交通，不自动换成飞机；长途需核实跨天抵达。','flight':'用户允许优先考虑飞机，但航班、机场、日期和票价必须核实，不把门到门估算当实际航班。','auto':'允许比较多种方式，未核实航班仅作待确认备选，不宣称已落实。'}[req.longhaul_mode])
    if '租车' in mode:
        lines.append('需要在出发地取车并在最终返回点还车，首末日各预留45分钟办理手续；异地还车费用另核实。')
    lines.append('门票ticket_price与餐饮estimated_cost始终填写单人成人费用，不乘同行人数；整团预算由服务端按人数、房间和车辆单独计算。')
    lines.append(f'同行{req.travelers}人；选择住宿区域时考虑房型、人数、行李与换酒店成本，优先连续住宿。')
    for w in req.day_windows:
        lines.append(f'第{w.day}天旅途时间窗{w.start}–{w.end}：指从出发地出发（含取车）到回到出发地（含还车）的整段时间，不是景点游览时间。不得早于{w.start}出发；第一个景点要排在出发、路程、取车之后并紧接抵达（不要留大段空档）；最后一个景点必须为返程与还车留足时间，{w.end}前要到家；不得硬塞景点。')
    for s in req.stays:
        lines.append(f'第{s.night}晚住在「{s.name}」（{s.kind}，{s.lat},{s.lng}），当天在这里结束、次日从这里开始，换住宿预留行李寄存和入住时间。')
    if not req.stays and not req.stay_name and req.days > 1:
        lines.append('住宿未定：先按人数和偏好形成路线草案，每晚建议交通便利的住宿区域，优先连住；待确认区域后再细化，不得声称酒店已订。')
    timing = req.longhaul_timing
    if timing == 'overnight':
        lines.append('愿意考虑夜间长途公共交通：约5–9小时路段优先对比直达卧铺/可躺座与白天方案，核实真实班次、日期、票价、换乘及安全到站条件；抵达后安排寄存行李和休息，不能默认酒店可提前入住。未核实不得把夜班当作已落实，也不得自动扣除住宿费。自驾不采用熬夜策略。')
    elif timing == 'day':
        lines.append('优先白天出行，避免凌晨出发或到达，舒适休息优先于节省一晚住宿。')
    else:
        lines.append('平衡票价、总耗时与舒适度；长途同时比较白天和可休息的夜班，未经用户确认不自动选择夜班。')
    return ''.join(lines)


def rental_budget(meta, days):
    rental = meta.get('rental')
    if not isinstance(rental, dict):
        if '租车' not in str(meta.get('transportation') or ''):return None
        rental={**RENTAL_REFERENCES['sixt'],'confidence':'reference','source':'平台公开地区起价参考，非所选日期报价','note':'租车参考价未含保险、押金及异地还车费用'}
    return {**rental, 'days': days, 'total': round(float(rental['daily_eur']) * days, 2)}
