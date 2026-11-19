"""Shared cuisine preferences for discovery, search and composition."""
import re
CUISINES={'local':'当地特色','chinese':'中餐','french':'法餐','italian':'意餐','japanese':'日料','korean':'韩餐','vegetarian':'素食','any':'不挑菜系'}
SEARCH={'local':'local cuisine restaurant','chinese':'Chinese restaurant','french':'French restaurant','italian':'Italian restaurant','japanese':'Japanese restaurant','korean':'Korean restaurant','vegetarian':'vegetarian restaurant','any':'local restaurant'}

def preferences(text='',explicit=None):
    match=re.search(r'\[dining:([a-z,]+)\]',text or '')
    values=(explicit or {}).get('cuisines') or (match.group(1).split(',') if match else [])
    if not values:
        values=[key for key,label in CUISINES.items() if key not in ('any','local') and label in (text or '')]
    values=list(dict.fromkeys(x for x in values if x in CUISINES))[:3] or ['local']
    return ['any'] if 'any' in values else values

def prompt(config):
    values=preferences(explicit=config)
    return '[dining:'+','.join(values)+'] 餐饮倾向：'+'、'.join(CUISINES[v] for v in values)+'。餐馆须通过地图验证；结合路线、用餐时段和预算，尽量轮换所选菜系，避免每天重复同一家。[/dining]'

def queries(city,text):
    values=preferences(text)
    return [f'{city} {SEARCH[v]}' for v in values][:3]
