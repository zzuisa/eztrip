"""Location/date-specific weather with bounded public-provider calls and honest gaps.

Daily values are forecast-model output or historical reanalysis, never an official
weather warning. No IP geolocation: the server cannot locate a remote user's device.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import copy
import math
import re
import threading
import time
from zoneinfo import ZoneInfo

import httpx

FORECAST = 'https://api.open-meteo.com/v1/forecast'
ARCHIVE = 'https://archive-api.open-meteo.com/v1/archive'
SOURCE = 'Open-Meteo'
_cache: dict = {}
_lock = threading.Lock()
_CODES = {0: '晴', 1: '晴间多云', 2: '局部多云', 3: '阴', 45: '雾', 48: '冻雾',
          51: '小毛毛雨', 53: '毛毛雨', 55: '较强毛毛雨', 56: '冻毛毛雨', 57: '冻毛毛雨',
          61: '小雨', 63: '雨', 65: '大雨', 66: '冻雨', 67: '强冻雨',
          71: '小雪', 73: '雪', 75: '大雪', 77: '雪粒', 80: '阵雨', 81: '较强阵雨',
          82: '强阵雨', 85: '阵雪', 86: '强阵雪', 95: '雷暴', 96: '雷暴伴冰雹', 99: '强雷暴伴冰雹'}
DAILY = 'weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum,precipitation_probability_max,wind_speed_10m_max,wind_gusts_10m_max,uv_index_max,sunrise,sunset'
HOURLY = 'temperature_2m,apparent_temperature,precipitation_probability,precipitation,weather_code,wind_speed_10m,wind_gusts_10m'


def outdoor_preference(text: str) -> bool:
    return bool(re.search(r'city\s*walk|outdoor|hik(?:e|ing)|cycl(?:e|ing)|户外|徒步|步行|漫步|骑行|爬山|登山|露营|自然|河畔|海滩|日出', text or '', re.I))


def _num(value):
    return value if isinstance(value, (int, float)) and math.isfinite(value) else None


_RAIN_CODES = (51, 53, 55, 61, 63, 65, 80, 81, 82)


def meaningful_rain(row: dict) -> bool:
    """有实际意义的降雨信号：概率或降水量任一达到阈值。概率 0% + 零星毫米数不算（否则会出现 0% 却提示带伞）。"""
    prob, mm, code = row.get('precipitation_probability'), row.get('precipitation_mm') or 0, row.get('weather_code')
    if prob is not None:
        return prob >= 40 or mm >= 3 or (code in _RAIN_CODES and prob >= 30 and mm >= 0.5)
    return mm >= 3 or (code in _RAIN_CODES and mm >= 1)      # 历史数据没有概率：只看降水量


def _calm_code(row: dict) -> None:
    """逐日代码取“当天最差”，会让 0% 概率的日子也显示成毛毛雨；没有实质降雨信号时按多云/阴展示。"""
    if row.get('weather_code') in _RAIN_CODES and not meaningful_rain(row):
        row['weather_code'] = 3
        row['summary'] = _CODES[3]


def advice(row: dict, preferences: str = '') -> dict:
    """Travel comfort guidance; missing values never become 0 / 'safe'."""
    reasons, level = [], 'low'
    _calm_code(row)
    code = row.get('weather_code')
    if code in (95, 96, 99):
        reasons.append('有雷暴信号，避免开阔地、山顶与水边，改选可确认开放的室内地点'); level = 'high'
    if code in (56, 57, 66, 67, 71, 73, 75, 77, 85, 86) or (row.get('temp_min') is not None and row['temp_min'] <= 0):
        reasons.append('雨雪或低温可能使路面湿滑，减少长距离步行，注意保暖防滑'); level = 'high'
    if (row.get('wind_kmh') or 0) >= 40 or (row.get('gust_kmh') or 0) >= 60:
        reasons.append('风较大，避开暴露的观景台、树林和河岸，增加室内停留'); level = 'high'
    if meaningful_rain(row):
        reasons.append('有降雨可能（概率 %s%%），带防水外套；citywalk 分成短段，中间安排室内休息' % int(row['precipitation_probability']) if row.get('precipitation_probability') is not None else '有降雨可能，带防水外套；citywalk 分成短段，中间安排室内休息')
        if level != 'high': level = 'moderate'
    if row.get('temp_max') is not None and row['temp_max'] >= 30:
        reasons.append('白天气温较高，长距离户外安排在早晚，午间休息并补水'); level = 'high'
    if (row.get('uv_index') or 0) >= 6:
        reasons.append('紫外线较强，避开长时间暴晒，准备遮阳和防晒')
        if level != 'high': level = 'moderate'
    if code in (45, 48):
        reasons.append('雾可能降低能见度，户外与驾车都需留缓冲，避开视线不佳的路段')
        if level != 'high': level = 'moderate'
    if row.get('status') == 'unavailable':
        level = 'unknown'; reasons = [row.get('reason') or '暂无该日期的可靠天气数据，出发前再查，不据此保证适合户外']
    elif not reasons:
        reasons = ['目前未见上述明显不利信号，天气仍可能变化；出发前再核对逐小时预报']
        if any(row.get(k) is None for k in ('weather_code', 'temp_max', 'temp_min', 'wind_kmh', 'precipitation_mm')):
            level = 'unknown'; reasons = ['部分天气要素缺失，无法完整评估户外条件；出发前再查']
    if outdoor_preference(preferences):
        reasons.append('你偏好户外 / citywalk：保留就近室内备选，遇不利天气缩短步行；日落后避免偏僻路段')
    return {'risk': level, 'advice': reasons, 'indoor_alternative': level in ('high', 'moderate', 'unknown')}


def _get(url, params):
    key = (url, tuple(sorted((k, str(v)) for k, v in params.items())))
    with _lock:
        hit = _cache.get(key)
        if hit and time.monotonic() - hit[0] < 900:
            return copy.deepcopy(hit[1])
    with httpx.Client(timeout=httpx.Timeout(8, connect=4)) as client:
        response = client.get(url, params=params)
        response.raise_for_status()
        data = response.json()
    if data.get('error'): raise ValueError('weather provider unavailable')
    with _lock:
        if len(_cache) >= 256: _cache.clear()
        _cache[key] = (time.monotonic(), copy.deepcopy(data))
    return data


def _day(value: str) -> date:
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value): raise ValueError('日期须为 YYYY-MM-DD')
    return date.fromisoformat(value)


def _clock(value: str) -> str:
    if not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', value): raise ValueError('时间须为 HH:MM（查询地点当地时间）')
    return value


def query_weather(location: str = '', lat: float | None = None, lng: float | None = None,
                  start_date: str = '', end_date: str = '', start_time: str = '', end_time: str = '',
                  preferences: str = '') -> dict:
    """Dates inclusive; optional times bound the entire interval in destination-local time."""
    base = {'location': location[:120], 'source': SOURCE, 'source_url': 'https://open-meteo.com/',
            'attribution': 'Weather data by Open-Meteo.com (CC BY 4.0)',
            'fetched_at': datetime.now(timezone.utc).isoformat(), 'days': [], 'hourly': [],
            'disclaimer': '旅行参考，非官方气象预警；预报可能变化，出发前请复查当地气象部门。'}
    if not start_date:
        return {**base, 'status': 'date_required', 'message': '选择出行日期后才能查询对应天气；暂不按今天的天气推断行程。'}
    start, end = _day(start_date), _day(end_date or start_date)
    if end < start or (end - start).days > 30: raise ValueError('天气查询时间段须为 1–31 天，结束日期不得早于开始日期')
    if (lat is None) != (lng is None): raise ValueError('经纬度须成对提供')
    if start_time: _clock(start_time)
    if end_time: _clock(end_time)
    if start == end and start_time and end_time and end_time < start_time: raise ValueError('结束时间不得早于开始时间')
    if lat is None:
        if not location.strip(): raise ValueError('请提供地点或经纬度')
        from . import geo_service
        try:
            found = geo_service.search(location)
        except Exception:
            found = []
        if not found:
            return {**base, 'status': 'unavailable', 'message': '无法确认地点，请在地图上选取后重试。'}
        point = found[0]
        if point.get('type') in ('country', 'region'):
            return {**base, 'status': 'unavailable', 'message': '地点范围较大，请选择具体城市或景点后查询天气。'}
        lat, lng = point['lat'], point['lng']
        base['location'] = str(point.get('label') or location)[:120]
    if not all(isinstance(v, (float, int)) and math.isfinite(v) for v in (lat, lng)) or not -90 <= lat <= 90 or not -180 <= lng <= 180:
        raise ValueError('无效的经纬度')
    lat, lng = round(float(lat), 3), round(float(lng), 3)
    base.update(lat=lat, lng=lng, start_date=start.isoformat(), end_date=end.isoformat(), start_time=start_time, end_time=end_time)
    now = datetime.now(timezone.utc)
    # The provider's local clock determines its forecast window. Keep one extra UTC
    # day at either edge, then let returned daily dates decide availability.
    today = now.date()
    chunks = []
    hist_end = min(end, today - timedelta(days=6))
    if start <= hist_end and start >= date(1940, 1, 1):
        chunks.append((ARCHIVE, start, hist_end, 'historical'))
    fstart, fend = max(start, today - timedelta(days=5)), min(end, today + timedelta(days=16))
    if fstart <= fend:
        chunks.append((FORECAST, fstart, fend, 'forecast'))
    rows, hours, tzname = {}, [], ''
    failed = False
    for url, a, b, kind in chunks:
        params = {'latitude': lat, 'longitude': lng, 'timezone': 'auto', 'daily': DAILY,
                  'wind_speed_unit': 'kmh', 'temperature_unit': 'celsius', 'precipitation_unit': 'mm'}
        if start_time or end_time: params['hourly'] = HOURLY
        # Archive has no probability or UV fields. Missing values remain None.
        if kind == 'historical':
            params['daily'] = DAILY.replace(',precipitation_probability_max', '').replace(',uv_index_max', '')
            if 'hourly' in params: params['hourly'] = HOURLY.replace(',precipitation_probability', '')
            params.update(start_date=a.isoformat(), end_date=b.isoformat())
        else:
            params.update(past_days=7, forecast_days=16)
        try:
            data = _get(url, params)
            tzname = data.get('timezone') or 'UTC'
            local_today = now.astimezone(ZoneInfo(tzname)).date()
            daily = data.get('daily') or {}
            def val(container, name, i):
                values = container.get(name) or []
                return values[i] if i < len(values) else None
            for i, ds in enumerate(daily.get('time') or []):
                if not start.isoformat() <= ds <= end.isoformat(): continue
                code = _num(val(daily, 'weather_code', i))
                row = {'date': ds, 'location': base['location'], 'timezone': tzname,
                       'status': 'historical' if ds < local_today.isoformat() else 'forecast',
                       'weather_code': code, 'summary': _CODES.get(code, '天气状况待确认'),
                       'temp_max': _num(val(daily, 'temperature_2m_max', i)), 'temp_min': _num(val(daily, 'temperature_2m_min', i)),
                       'precipitation_probability': _num(val(daily, 'precipitation_probability_max', i)),
                       'precipitation_mm': _num(val(daily, 'precipitation_sum', i)),
                       'wind_kmh': _num(val(daily, 'wind_speed_10m_max', i)), 'gust_kmh': _num(val(daily, 'wind_gusts_10m_max', i)),
                       'uv_index': _num(val(daily, 'uv_index_max', i)), 'sunrise': val(daily, 'sunrise', i), 'sunset': val(daily, 'sunset', i)}
                if code is None and row['temp_max'] is None:
                    row.update(status='unavailable', reason='该日期天气数据缺失')
                row.update(advice(row, preferences)); rows[ds] = row
            hourly = data.get('hourly') or {}
            for i, ts in enumerate(hourly.get('time') or []):
                if not start.isoformat() <= ts[:10] <= end.isoformat(): continue
                if start_time and ts < start.isoformat()+'T'+start_time[:2]+':00': continue
                if end_time and ts > end.isoformat()+'T'+end_time: continue
                code = _num(val(hourly, 'weather_code', i))
                hours.append({'time': ts, 'timezone': tzname, 'weather_code': code, 'summary': _CODES.get(code, '待确认'),
                              **{k: _num(val(hourly, field, i)) for k, field in [('temperature', 'temperature_2m'), ('feels_like', 'apparent_temperature'), ('precipitation_probability', 'precipitation_probability'), ('precipitation_mm', 'precipitation'), ('wind_kmh', 'wind_speed_10m'), ('gust_kmh', 'wind_gusts_10m')]}})
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            failed = True
    for n in range((end-start).days+1):
        ds = (start+timedelta(days=n)).isoformat()
        if ds not in rows:
            row = {'date': ds, 'location': base['location'], 'status': 'unavailable', 'summary': '暂无预报',
                   'reason': '天气服务暂时不可用，请稍后重试' if failed else '超出可用预报范围或历史数据尚未发布；出发前再查',
                   **{k: None for k in ('weather_code', 'temp_max', 'temp_min', 'precipitation_mm', 'precipitation_probability', 'wind_kmh', 'gust_kmh', 'uv_index')}}
            row.update(advice(row, preferences));rows[ds] = row
    # Keep a compact per-day time breakdown for planning, even when the flattened
    # hourly response is capped. A long itinerary must not lose days 8–15.
    for ds, row in rows.items():
        windows = []
        for label, begin, finish in [('上午',6,12),('下午',12,18),('晚间',18,24)]:
            hs = [h for h in hours if h['time'][:10] == ds and begin <= int(h['time'][11:13]) < finish]
            if not hs: continue
            def vals(k): return [h[k] for h in hs if h.get(k) is not None]
            slot = {'label':label, 'start':f'{begin:02d}:00', 'end':f'{finish:02d}:00', 'status':row['status'],
                    'temp_min':min(vals('temperature'),default=None), 'temp_max':max(vals('temperature'),default=None),
                    'weather_code':max(vals('weather_code'),default=None),
                    'precipitation_probability':max(vals('precipitation_probability'),default=None),
                    'precipitation_mm':sum(vals('precipitation_mm')) if vals('precipitation_mm') else None,
                    'wind_kmh':max(vals('wind_kmh'),default=None), 'gust_kmh':max(vals('gust_kmh'),default=None)}
            slot.update(advice(slot, preferences));windows.append(slot)
        if windows: row['time_windows'] = windows
    ordered = [rows[k] for k in sorted(rows)]
    count = sum(d['status'] != 'unavailable' for d in ordered)
    period = None
    if start_time or end_time:
        def values(key): return [h[key] for h in hours if h.get(key) is not None]
        period = {'date': start.isoformat(), 'status': ('historical' if end < now.astimezone(ZoneInfo(tzname)).date() else 'forecast') if hours else 'unavailable',
                  'temp_min': min(values('temperature'), default=None), 'temp_max': max(values('temperature'), default=None),
                  'weather_code': max(values('weather_code'), default=None), 'wind_kmh': max(values('wind_kmh'), default=None),
                  'gust_kmh': max(values('gust_kmh'), default=None),
                  'precipitation_probability': max(values('precipitation_probability'), default=None),
                  'precipitation_mm': sum(values('precipitation_mm')) if values('precipitation_mm') else None,
                  'reason': '所选时段暂无逐小时天气数据，不能据全天概况判断该时段一定适宜户外'}
        period.update(advice(period, preferences))
    return {**base, 'period': period, 'timezone': tzname, 'status': 'available'  if count == len(ordered) else 'partial' if count else 'unavailable',
            'message': '按查询地点当地时间展示；逐小时为整点参考，非分钟级预报。未来天气是预报，过去天气为模型历史资料。',
            'days': ordered, 'hourly': sorted(hours, key=lambda h:h['time'])[:168], 'hourly_truncated': len(hours)>168}


def planning_block(report: dict | None, day: int | None = None) -> str:
    if not report: return ''
    days = report.get('days') or []
    if day is not None: days = days[day-1:day]
    lines = [f"天气约束（{report.get('location', '')}；当地时区 {report.get('timezone') or '待确认'}）："]
    if not days: lines.append(report.get('message') or '天气未知，不得编造晴雨或承诺适合户外。')
    for d in days:
        lines.append(f"{d['date']} {d.get('status')} {d.get('summary')}，{d.get('temp_min')}–{d.get('temp_max')}°C，雨概率 {d.get('precipitation_probability')}%，风 {d.get('wind_kmh')}km/h，日落 {d.get('sunset')}；"+'；'.join(d.get('advice') or []))
        if d.get('time_windows'):
            lines.append('分时参考：'+'；'.join(f"{w['label']} {w['start']}-{w['end']} 雨概率{w.get('precipitation_probability')}%，风{w.get('wind_kmh')}km/h，{w.get('temp_min')}–{w.get('temp_max')}°C，户外风险{w['risk']}" for w in d['time_windows']))
    lines.append('天气数据不是官方预警。雨雪/雷暴/强风/高低温时优先检索真实室内候选、缩短暴露步行，安排避雨休息；citywalk 不应硬排全天户外。没有核验的室内地点不可编造。未知日期只给条件性建议。')
    return '\n'.join(lines)+'\n'


def for_plan(location: str, start_date: str = '', days: int = 1, preferences: str = '', lat=None, lng=None) -> dict:
    end = (_day(start_date)+timedelta(days=days-1)).isoformat() if start_date else ''
    report = query_weather(location, lat, lng, start_date, end, '00:00' if start_date else '', '23:59' if start_date else '', preferences=preferences)
    report.pop('period', None)
    return report


def attach(payload: dict, report: dict) -> None:
    payload['weather'] = report
    payload['weather_info'] = report.get('days') or []
    warnings = list(payload.get('warnings') or [])
    for d in report.get('days') or []:
        if d.get('status') != 'unavailable' and d.get('risk') in ('high', 'moderate'):
            warnings.append(f"{d['date']} 天气："+'；'.join(d.get('advice') or []))
    # Unknown forecasts are a single collapsible UI indicator, not daily alerts.
    payload['warnings'] = list(dict.fromkeys(warnings))
    compact_presentation(payload)


def compact_presentation(payload: dict) -> None:
    """Hide legacy daily missing-forecast warnings without rewriting saved plans."""
    report=payload.get('weather') or {}
    dates={str(d.get('date')) for d in report.get('days') or [] if d.get('status')=='unavailable'}
    exact={report.get('message')} if report.get('status')=='date_required' else set()
    payload['warnings']=[w for w in payload.get('warnings') or [] if str(w) not in exact and not any(str(w).startswith(ds+' 天气：') for ds in dates)]
