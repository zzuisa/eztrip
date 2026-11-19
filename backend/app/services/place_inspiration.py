"""On-demand public note cards for saved itinerary places; private tokens stay in cache."""
from __future__ import annotations
import hashlib,json,os,threading,time,re
from pathlib import Path
from urllib.parse import urlsplit
from .xiaohongshu_service import get_xiaohongshu_service,XiaohongshuError
from .xhs_research import count,norm,detail_text

TTL=6*3600
ALIASES={
 'vangoghmuseum':['Van Gogh Museum','梵高博物馆','梵高'],
 '荷蘭國立博物館':['Rijksmuseum','荷兰国立博物馆','荷蘭國立博物館'],
 '荷兰国立博物馆':['Rijksmuseum','荷兰国立博物馆'],
 '安妮弗兰克之家':['Anne Frank House','安妮之家','安妮弗兰克'],
 '九街':['九街','De 9 Straatjes','Nine Streets'],
 '约旦区':['Jordaan','约旦区'],
}
_STOP={'museum','restaurant','amsterdam','centre','center','coffee','corner','breakfast','brunch','lunch','house','the','city'}


def aliases(name):
    import re
    values=[name,*ALIASES.get(norm(name),[])]
    for word in re.findall(r'[A-Za-zÀ-ž]{5,}',name):
        if word.casefold() not in _STOP:
            values.append(word);break
    return list(dict.fromkeys(values))


def cover(card):
    data=card.get('cover') or {};urls=[data.get('urlDefault'),data.get('urlPre'),data.get('url')]+[i.get('url') for i in (data.get('infoList') or []) if isinstance(i,dict)]
    for value in urls:
        if not isinstance(value,str):continue
        u=urlsplit(value)
        if u.scheme=='http':u=u._replace(scheme='https');value=u.geturl()
        if u.scheme=='https' and u.hostname and any(u.hostname==h or u.hostname.endswith('.'+h) for h in ('xhscdn.com','rednotecdn.com')) and not u.username and len(value)<3000:return value
    return None


def short_excerpt(text,title,name):
    body=text.replace(title,'',1).strip();limit=max(0,min(60,80-len(title)))
    indexes=[body.casefold().find(a.casefold()) for a in aliases(name) if a and body.casefold().find(a.casefold())>=0]
    start=max(0,min(indexes)-12) if indexes else 0
    return body[start:start+limit]+('…' if len(body)>start+limit and limit else '') if limit else ''


class PlaceInspirationService:
    def __init__(self,cache_dir=None,upstream=None):
        self.directory=Path(cache_dir) if cache_dir else Path(__file__).resolve().parents[2]/'cache'/'xhs-place-details'
        self.directory.mkdir(parents=True,exist_ok=True)
        self.upstream=upstream
        self._guard=threading.Lock();self._locks={}
    def key(self,name,city):return hashlib.sha256((norm(city)+'|'+norm(name)).encode()).hexdigest()[:40]
    def _lock(self,key):
        with self._guard:
            if len(self._locks)>512:self._locks.clear()
            return self._locks.setdefault(key,threading.Lock())
    def _read(self,key):
        try:
            d=json.loads((self.directory/(key+'.json')).read_text())
            return d if d['expires']>time.time() else None
        except (OSError,ValueError,KeyError,TypeError):return None
    def _write(self,key,data):
        target=self.directory/(key+'.json');temp=self.directory/(key+f'.{threading.get_ident()}.tmp')
        temp.write_text(json.dumps(data,ensure_ascii=False));temp.chmod(0o600);os.replace(temp,target)
    def peek(self,name,city):
        packet=self._read(self.key(name,city));return packet['public'] if packet else None
    def lookup(self,name,city):
        key=self.key(name,city)
        with self._lock(key):
            packet=self._read(key)
            if packet:return {**packet['public'],'cached':True}
            names=aliases(name);query_name=names[1] if len(names)==2 and re.fullmatch(r'[A-Za-zÀ-ž]+',names[1]) else name
            query=f'{city} {query_name} '+('参观 攻略' if 'museum' in name.lower() or '博物' in name else '体验 攻略')
            service=self.upstream or get_xiaohongshu_service()
            response=service.search_feeds(query[:120]);feeds=(response.get('data') or {}).get('feeds') or []
            rows=[];private={}
            for feed in feeds:
                card=feed.get('noteCard') or feed.get('note_card') or feed
                if not isinstance(card,dict):continue
                identity=str(feed.get('feed_id') or feed.get('id') or '')
                if not re.fullmatch(r'[A-Za-z0-9_-]{4,80}',identity):continue
                title=str(feed.get('title') or card.get('displayTitle') or '')[:100]
                if not title:continue
                interactions=card.get('interactInfo') or card.get('interact_info') or {}
                likes=count(interactions.get('likedCount'));saves=count(interactions.get('collectedCount'))
                matches=sum(norm(a) in norm(title+' '+str(feed.get('desc') or '')) for a in names if len(norm(a))>=2)
                row={'id':identity,'title':title,'url':'https://www.xiaohongshu.com/explore/'+identity,'likes':likes,'collections':saves,'cover_url':cover(card),'metrics_at':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'matched_place':True,'metrics_approximate':any(re.search(r'[万萬w亿億k+.]',str(interactions.get(k,'')),re.I) for k in ('likedCount','collectedCount'))}
                rows.append((matches,(likes or 0)+(saves or 0),row))
                if feed.get('xsec_token'):private[identity]={'token':feed['xsec_token'],'title':title}
            rows.sort(key=lambda r:(r[0],r[1]),reverse=True)
            related=[r for r in rows if r[0]>0];previews={}
            # A general food/travel title may name the venue only in its body.
            # Check at most one candidate; never fill the page with unrelated notes.
            if not related and rows:
                row=rows[0][2];entry=private.get(row['id'])
                if entry:
                    detail=service.get_feed_detail(row['id'],entry['token'],load_all_comments=False,limit=1)
                    text=detail_text(detail.get('data') or {})
                    if any(norm(a) in norm(text) for a in names if len(norm(a))>=2):
                        related=[rows[0]];row['excerpt']=short_excerpt(text,row['title'],name)
                        previews[row['id']]={'status':'available','excerpt':row['excerpt'],'cached':False}
            notes=list({r[2]['id']:r[2] for r in related}.values())[:4]
            public={'status':'available' if notes else 'empty','notes':notes,'query':query[:120],'cached':False,'source':'小红书','name':name}
            packet={'expires':time.time()+(TTL if notes else 600),'public':public,'private':{n['id']:private[n['id']] for n in notes if n['id'] in private},'previews':previews}
            self._write(key,packet);return public
    def preview(self,name,city,note_id):
        key=self.key(name,city)
        with self._lock(key):
            packet=self._read(key)
            if not packet or note_id not in {n['id'] for n in packet['public']['notes']}:return {'status':'expired','excerpt':''}
            if note_id in packet.get('previews',{}):return {**packet['previews'][note_id],'cached':True}
            entry=packet.get('private',{}).get(note_id)
            if not entry:return {'status':'unavailable','excerpt':''}
            response=(self.upstream or get_xiaohongshu_service()).get_feed_detail(note_id,entry['token'],load_all_comments=False,limit=1)
            text=detail_text(response.get('data') or {})
            if not any(norm(a) in norm(text) for a in aliases(name) if len(norm(a))>=2):return {'status':'unrelated','excerpt':''}
            # Short attributed preview, not republication of the full note.
            excerpt=short_excerpt(text,entry['title'],name)
            data={'status':'available' if excerpt else 'empty','excerpt':excerpt,'cached':False}
            packet.setdefault('previews',{})[note_id]=data;self._write(key,packet);return data

_service=None
_service_lock=threading.Lock()
def get_place_inspiration_service():
    global _service
    with _service_lock:
        if _service is None:_service=PlaceInspirationService()
        return _service
