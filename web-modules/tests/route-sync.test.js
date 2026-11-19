import test from 'node:test';import assert from 'node:assert/strict';
import {mapRevision,invalidatePlanDays,planRevision} from '../src/route-sync.js';
test('map updates for reorder, mode, descriptions and times at identical coordinates',()=>{
 const original=[{key:'a',dayIndex:0,order:1,lat:1,lng:2,hint:'walk',name:'A',description:'old',time:'09:00'}];
 for(const patch of [{order:2},{dayIndex:1},{hint:'transit'},{travelMode:'driving'},{description:'new'},{time:'11:00'}])assert.notEqual(mapRevision(original),mapRevision([{...original[0],...patch}]));
});
test('optimistic edits invalidate old route text, hotel transfers and fallback map points',()=>{
 const plan={review:{status:'ok'},days:[]};const changed=[{transit_start:{from:'old'},display_title:'old',attractions:[{name:'removed',location:{latitude:9,longitude:9}}],activities:[{name:'B',time:'10:00',route_desc:'from removed A',latitude:1,longitude:2}],meals:[]}];
 const next=invalidatePlanDays(plan,changed);assert.equal(next.days[0].activities[0].route_desc,'');assert.equal(next.days[0].transit_start,undefined);assert.equal(next.days[0].attractions[0].name,'B');assert.equal(next.days[0].display_title,'B');assert.equal(next.review.verdict,'revise');assert.equal(changed[0].activities[0].route_desc,'from removed A');
});

test('photo enrichment leaves playback running, while changed itinerary text invalidates it',()=>{
 const days=[{activities:[{name:'A',description:'venue',image_url:'old'}],meals:[]}];const changed=structuredClone(days);changed[0].activities[0].image_url='new';assert.equal(planRevision(days),planRevision(changed));changed[0].activities[0].description='new venue description';assert.notEqual(planRevision(days),planRevision(changed));
});
