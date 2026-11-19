"""A stricter, explicit acceptance policy for trips of eight days or longer."""
from __future__ import annotations
import copy
VERSION='long-trip-v1'

def policy(days, cfg):
    out=dict(cfg)
    out['min_passes']=2 if days>=8 else 1
    if days>=8:
        out['max_rounds']=max(4,out.get('max_rounds',2))
        out['target_score']=max(90,out.get('target_score',85))
        out['max_revisions']=max(days,out.get('max_revisions',6))
        out['total_timeout_seconds']=max(600,out.get('total_timeout_seconds',200))
        out['timeout_seconds']=max(120,out.get('timeout_seconds',90))
    return out

def apply(review,payload,meta,passes=1):
    days=len(payload.get('itinerary') or [])
    if days<8:return review
    from . import finalize
    critical=[i for i in review.get('issues') or [] if i.get('severity')=='high' or i.get('severity')=='medium' and i.get('type') in ('timing','geography','meal','duplicate','theme')]
    hard=finalize.hard_checks(payload,meta)
    nights=max(0,days-1)
    covered={s.get('night') for s in meta.get('stays') or [] if s.get('name')}
    lodging=bool(meta.get('stay_name')) or covered==set(range(1,nights+1))
    if review.get('status')!='ok' or passes<2:state='unverified'
    elif critical or hard or int(review.get('score') or 0)<90:state='needs_attention'
    elif not lodging:state='needs_accommodation'
    else:state='passed'
    review['quality_gate']={'policy':VERSION,'state':state,'passes':passes,'required_passes':2,
                            'critical_issues':len({str(i.get('message')) for i in [*critical,*hard]}),'accommodation_complete':lodging,
                            'summary':{'passed':'长行程复核完成','needs_attention':'跨城衔接或时间安排仍需调整，当前为行程草案',
                                       'unverified':'长行程复核尚未完成，先保留草案','needs_accommodation':'先确认各城住宿，再复核首末交通'}[state]}
    if state!='passed':review['verdict']='revise'
    return review

def merge(first,second):
    out=copy.deepcopy(second if second.get('status')=='ok' else first)
    if first.get('status')=='ok' and second.get('status')=='ok':
        seen=set();issues=[]
        for item in [*(first.get('issues') or []),*(second.get('issues') or [])]:
            key=(item.get('day'),item.get('type'),item.get('message'))
            if key not in seen:seen.add(key);issues.append(item)
        out['issues']=issues[:32];out['score']=min(int(first.get('score') or 0),int(second.get('score') or 0))
        if any(i.get('severity')=='high' for i in issues):out['verdict']='revise'
    return out


def include_hard_checks(review, checks):
    """Deterministic conflicts must reach the revision loop even if the model omits them."""
    if review.get('status')!='ok':return review
    issues=list(review.get('issues') or []);seen={(i.get('day'),i.get('message')) for i in issues}
    for c in checks:
        if (c.get('day'),c.get('message')) in seen:continue
        issues.append({'day':int(c.get('day') or 0),'severity':'high','type':'timing','message':str(c.get('message') or '时间衔接冲突'),
                       'fix':str(c.get('message') or '')+'；按真实抵达、返程与每日时间窗重排这一天，保留交通缓冲并减少放不下的地点'})
    review['issues']=issues
    if issues and any(i.get('severity')=='high' for i in issues):review['verdict']='revise'
    return review
