/** Route revisions include ordering and content, not just the set of coordinates. */
export function mapRevision(stops) {
 return JSON.stringify(stops.map(s=>[s.key,s.dayIndex,s.order,s.lng,s.lat,s.hint,s.travelMode,s.name,s.time,s.description]));
}

export function invalidatePlanDays(plan,days) {
 const pendingReview={status:'pending',verdict:'revise',issues:[],quality_gate:{state:'needs_attention',summary:'行程已调整，正在重新评审交通、时间和活动安排。'}};
 return {...plan,review:pendingReview,days:days.map(day=>{
  const activities=(day.activities||[]).map(i=>({...i,route_desc:'',route_connection:undefined}));
  const meals=(day.meals||[]).map(i=>({...i,route_desc:'',route_connection:undefined}));
  const sequence=[...activities,...meals].sort((a,b)=>String(a.time||'').localeCompare(String(b.time||'')));
  const summary=sequence.map(i=>i.name).join(' → ')||'当天暂无活动，可继续添加地点。';
  // Recreate fallback attraction data as well: old coordinates must never survive a move.
  const attractions=activities.map(i=>({...i,location:Number.isFinite(i.latitude)&&Number.isFinite(i.longitude)?{latitude:i.latitude,longitude:i.longitude}:undefined}));
  return {...day,activities,meals,attractions,display_title:sequence.slice(0,3).map(i=>i.name).join(' → ')||'自由安排',description:summary,arrangement_reason:summary,transit_start:undefined,transit_end:undefined};
 })};
}

export function planRevision(days) {
 return JSON.stringify(days.map(d=>[d.display_title,d.description,d.arrangement_reason,d.transit_start,d.transit_end,...['activities','meals'].map(k=>(d[k]||[]).map(i=>[i.name,i.time,i.latitude,i.longitude,i.description,i.route_desc]))]));
}
