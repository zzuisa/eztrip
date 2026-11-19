"""Deterministic retiming: preserve durations, gaps and every item; never silently drop bookings."""
import copy
from .itinerary_edit import parse_range, fmt_range


def retime(day, start, end):
    low, _ = parse_range(start)
    high, _ = parse_range(end)
    if low is None or high is None or low >= high:
        raise ValueError('结束时间须晚于开始时间')
    result = copy.deepcopy(day)
    rows = [x for key in ('activities', 'meals') for x in result.get(key, []) if isinstance(x, dict)]
    timed = []
    for row in rows:
        s, e = parse_range(row.get('time'))
        if s is None:
            raise ValueError('存在未明确时间的活动，请先补充时间或使用智能优化')
        e = e if e is not None else s + int(row.get('duration_minutes') or 60)
        if e <= s:
            raise ValueError('存在跨夜或无效活动时间，请使用智能优化核实')
        timed.append((s, e, row))
    if not timed:
        raise ValueError('当天没有可调整的活动')
    delta = low - min(s for s, _, _ in timed)
    if max(e for _, e, _ in timed) + delta > high:
        raise ValueError('所选时间不足以容纳全部活动及交通间隔，请延后结束、减少活动或使用智能优化')
    for s, e, row in timed:
        row['time'] = fmt_range(s + delta, e + delta)
    result['day_window'] = {'start': start, 'end': end}
    return result
