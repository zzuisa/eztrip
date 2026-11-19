export const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export const clone = value => JSON.parse(JSON.stringify(value));
export const pointValid = p => p && Number.isFinite(Number(p.lat)) && Number.isFinite(Number(p.lng)) && Math.abs(Number(p.lat))<=90 && Math.abs(Number(p.lng))<=180;
export function message(error) { const detail=error?.response?.data?.detail;return typeof detail==='string'?detail:detail?.message || error?.message || '暂时无法完成，请稍后重试'; }
export async function request(api,path,body,signal) { const response=body===undefined?await api.get(path,{signal,timeout:60000}):await api.post(path,body,{signal,timeout:90000});return response.data; }
export function fromNights(values,total,city) {
 const blocks=[];const by=new Map((values||[]).map(v=>[v.night,v]));
 for(let n=1;n<=total;n++){
  const s=by.get(n);const prev=blocks.at(-1);
  if(prev && ((!s&&!prev.selection)||(s&&prev.selection&&['name','lat','lng','kind'].every(k=>s[k]===prev.selection[k])))){prev.night_end=n;continue;}
  blocks.push({id:`custom-${n}`,city:city||'住宿',night_start:n,night_end:n,areas:[],selection:s?{name:s.name,lat:s.lat,lng:s.lng,kind:s.kind||'hotel'}:null});
 }
 return blocks;
}
export function expandBlocks(blocks,total) {
 const values=[];let expected=1;
 for(const b of blocks){
  if(b.night_start!==expected || b.night_end<b.night_start || b.night_end>total || b.selection?.kind!=='hotel' || !b.selection?.name || !pointValid(b.selection))return null;
  for(let n=b.night_start;n<=b.night_end;n++)values.push({...b.selection,night:n});
  expected=b.night_end+1;
 }
 return expected===total+1?values:null;
}
export function shiftBoundary(blocks,index,value) {
 const left=blocks[index],right=blocks[index+1];if(!left||!right)return;
 const boundary=Math.max(left.night_start,Math.min(right.night_end-1,Math.round(Number(value))));
 left.night_end=boundary;right.night_start=boundary+1;
}
