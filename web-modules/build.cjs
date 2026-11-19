/** Reproducible, scoped adapter build for the preserved production frontend.
 * The original Vue sources were removed before this change. Keep the new UI in
 * ordinary modules; use AST component boundaries for integration, never regex
 * surgery inside rendering functions. Every affected dependency gets a new URL.
 */
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const acorn=require('acorn');
const [base,out,version]=process.argv.slice(2);if(!base||!out||!version||!/^[a-z0-9-]+$/.test(version))throw new Error('Usage: node build.cjs base-html output-html unique-release-version');
const assetRoot=path.join(base,'assets');const html=fs.readFileSync(path.join(base,'index.html'),'utf8');
const entry=html.match(/src="\/assets\/([^"/]+\.js)"/)?.[1];if(!entry)throw new Error('No module entry');
const expectedBase='bde970733817f64cf391f6544095647018209e506b8f4c3f68e8f34f035306e0';
if(crypto.createHash('sha256').update(fs.readFileSync(path.join(assetRoot,entry))).digest('hex')!==expectedBase)throw new Error('Unsupported frontend baseline: review component and runtime bindings before changing this checksum');
const files=new Map();const queue=[entry];while(queue.length){const name=queue.shift();if(files.has(name))continue;const s=fs.readFileSync(path.join(assetRoot,name),'utf8');files.set(name,s);for(const m of s.matchAll(/["'](?:\.\/|assets\/)([^"'/?]+\.js)["']/g))if(fs.existsSync(path.join(assetRoot,m[1])))queue.push(m[1]);}
const result=[...files].find(([n,s])=>s.includes('__name:"TripNights"'));if(!result)throw new Error('No current TripNights component');
const root=path.join(__dirname,'src');const assetNames=new Map();const moduleSources=new Map();
for(const name of ['dom.js','stay-planner.js','adapters.js','playback-camera.js','budget-ui.js','trip-guidance.js','route-sync.js','xhs-ui.js','place-notes.js']){
 let source=fs.readFileSync(path.join(root,name),'utf8');
 for(const [dep,built]of assetNames)source=source.replaceAll('./'+dep,'./'+built);
 const built='eztrip-'+name.replace('.js','')+'-'+crypto.createHash('sha256').update(source).digest('hex').slice(0,12)+'.js';assetNames.set(name,built);moduleSources.set(built,source);
}
const adapterName=assetNames.get('adapters.js');const edited=new Set();
function walk(node,visit){if(!node||typeof node!=='object')return;visit(node);for(const [k,v]of Object.entries(node)){if(k==='start'||k==='end')continue;if(Array.isArray(v))v.forEach(x=>walk(x,visit));else if(v&&typeof v==='object')walk(v,visit);}}
function routePartyComponent(original){
 const parsed=acorn.parse('('+original+')',{ecmaVersion:'latest',sourceType:'module'}),patches=[];let props=0,init=0,reset=0,cache=0,note=0,selection=0;
 walk(parsed,node=>{
  if(node.type==='Property'&&node.key?.name==='props'&&node.value.type==='ObjectExpression'&&node.value.properties.some(p=>p.key?.name==='chosen')){patches.push({start:node.value.end-2,end:node.value.end-2,text:',travelers:{}'});props++;}
  if(node.type==='VariableDeclarator'&&node.id.name==='f'&&node.init?.arguments?.[0]?.type==='CallExpression'&&node.init.arguments[0].callee.name==='sd'){const a=node.init.arguments[0];patches.push({start:a.start-1,end:a.end-1,text:'({...sd(),passengers:Math.min(8,Math.max(1,Number(t.travelers)||1))})'});init++;}
  if(node.type==='VariableDeclarator'&&node.id.name==='K'&&node.init?.body?.type==='BlockStatement'&&original.slice(node.init.body.start-1,node.init.body.end-1).includes('ue.prefs')){const pos=node.init.body.start;patches.push({start:pos,end:pos,text:'f.value=sn({...sd(),passengers:Math.min(8,Math.max(1,Number(t.travelers)||1))});'});reset++;}
  if(node.type==='VariableDeclaration'&&node.declarations.length===1&&node.declarations[0].id.name==='ue'&&original.slice(node.start-1,node.end-1).includes('le.compare')){const pos=node.end-1;patches.push({start:pos,end:pos,text:'if(ue?.prefs?.passengers!==Math.min(8,Math.max(1,Number(t.travelers)||1))||(le.choice_parties?.[qb(t.day,t.kind)]&&le.choice_parties[qb(t.day,t.kind)]!==t.travelers))p.value="";'});selection++;}
  if(node.type==='IfStatement'&&original.slice(node.consequent.start-1,node.consequent.end-1).includes('f.value=sn(ue.prefs)')){patches.push({start:node.test.start-1,end:node.test.end-1,text:'('+original.slice(node.test.start-1,node.test.end-1)+')&&ue.prefs?.passengers===Math.min(8,Math.max(1,Number(t.travelers)||1))'});cache++;}
  if(node.type==='Literal'&&node.value==='出行方式对比')patches.push({start:node.start-1,end:node.end-1,text:'"地面交通对比"'});
  if(node.type==='CallExpression'&&node.arguments[0]?.value==='div'&&node.arguments[1]?.name==='Xb'&&node.arguments[2]?.type==='ArrayExpression'){const pos=node.arguments[2].start;patches.push({start:pos,end:pos,text:'l("p",{class:"ez-route-scope"},"仅比较火车、巴士等地面公共交通与自驾，不含航班；长途可能跨天。"),'});note++;}
 });
 if([props,init,reset,cache,note,selection].some(n=>n!==1))throw new Error('Unexpected route party bindings '+[props,init,reset,cache,note,selection]);
 for(const p of patches.sort((a,b)=>b.start-a.start))original=original.slice(0,p.start)+p.text+original.slice(p.end);
 return original;
}
function integrate(name,isResult){let source=files.get(name);let ast=acorn.parse(source,{ecmaVersion:'latest',sourceType:'module'});let vnode,api;
 for(const n of ast.body){if(n.type==='ImportDeclaration'&&/vendor-vue/.test(n.source.value))vnode=n.specifiers.find(s=>s.imported?.name==='k')?.local.name;
 if(isResult&&n.type==='ImportDeclaration'&&n.source.value.includes(entry))api=n.specifiers.find(s=>s.imported?.name==='a')?.local.name;
 if(!isResult&&n.type==='ExportNamedDeclaration')api=api||n.specifiers?.find(s=>s.exported?.name==='a')?.local.name;}
 if(!vnode||!api)throw new Error('Cannot locate runtime VNode / existing API client in '+name);
 if(isResult){for(const builder of ['./place-details-build.cjs','./xhs-build.cjs']){const patches=[];require(builder)({source,ast,walk,replacements:patches,vnode});for(const p of patches.sort((a,b)=>b.start-a.start))source=source.slice(0,p.start)+p.text+source.slice(p.end);ast=acorn.parse(source,{ecmaVersion:'latest',sourceType:'module'});}}
 const replacements=[];const counts={};
 require("./route-sync-build.cjs")({source,ast,walk,replacements,isResult});

 if(isResult){
  let tripRef,revRef,budgetRef,budgetCalls=0,routeCalls=0;
  walk(ast,node=>{if(node.type!=='ObjectExpression')return;const trip=node.properties.find(p=>p.key?.value==='trip-id');if(trip){tripRef=source.slice(trip.value.start,trip.value.end);const rev=node.properties.find(p=>p.key?.name==='rev');if(rev)revRef=source.slice(rev.value.start,rev.value.end)}});
  walk(ast,node=>{if(node.type!=='ObjectExpression'||!node.properties.some(p=>p.key?.name==='onRefresh')||!node.properties.some(p=>p.key?.value==='diff-text'))return;
   if(!tripRef||!revRef)throw new Error('Missing budget trip references');
   const b=node.properties.find(p=>p.key?.name==='budget');budgetRef=source.slice(b.value.start,b.value.end);
   replacements.push({start:node.end-1,end:node.end-1,text:`,resultId:${tripRef},rev:${revRef}`});budgetCalls++;
  });if(budgetCalls!==1)throw new Error('Unexpected budget render bindings '+budgetCalls);
  walk(ast,node=>{if(node.type==='ObjectExpression'&&node.properties.some(p=>p.key?.name==='chosen')&&node.properties.some(p=>p.key?.value==='result-id')){replacements.push({start:node.end-1,end:node.end-1,text:`,travelers:(${budgetRef})?.detail?.party?.travelers||1`});routeCalls++;}});
  if(routeCalls!==1)throw new Error('Unexpected route traveler binding '+routeCalls);
 }
 if(isResult){
  let frame=0,trigger=0;
  walk(ast,node=>{
   if(node.type==='VariableDeclarator'&&node.id.name==='fn'&&source.slice(node.init.start,node.init.end).includes('cameraForBounds')){
    replacements.push({start:node.init.start,end:node.init.end,text:`(E,M,B)=>__framePlaybackLeg(o.value,e.value,kt,E,M,B,{bottomInset:T,maxZoom:On,pitch:le()?Eo:0,bearing:le()?o.value.getBearing():0,follow:le(),reducedMotion:Ft()})`});frame++;
   }
   if(node.type==='LogicalExpression'&&source.slice(node.start,node.end)==='le()&&o.value&&(ve=o.value.getBearing(),fn(z,E,M))'){
    replacements.push({start:node.start,end:node.end,text:'o.value&&(ve=o.value.getBearing(),fn(z,E,M))'});trigger++;
   }
  });
  if(frame!==1||trigger!==1)throw new Error('Unexpected playback camera boundaries '+frame+'/'+trigger);
 }
 walk(ast,node=>{if(node.type!=='VariableDeclarator'||node.init?.type!=='CallExpression')return;const object=node.init.arguments.find(x=>x.type==='ObjectExpression');const marker=object?.properties.find(p=>p.key?.name==='__name');const component=marker?.value.value;if(!component)return;let expression;
 if(component==='TripNights')expression=`__stayPlanner(${vnode},${api},${source.slice(node.init.start,node.init.end)},'inline')`;
 if(component==='StaySheet')expression=`__stayPlanner(${vnode},${api},${source.slice(node.init.start,node.init.end)},'modal')`;
 if(component==='NightStays')expression=`__stayPlanner(${vnode},${api},${source.slice(node.init.start,node.init.end)},'input')`;
 if(component==='WeatherSummary'||component==='WeatherStrip')expression=`__compactWeather(${vnode},${source.slice(node.init.start,node.init.end)})`;
 if(component==='DayTimeline')expression=`__compactDayWeather(${vnode},${source.slice(node.init.start,node.init.end)})`;
 if(component==='BaseRow')expression=`__readOnlyStayRow(${vnode},${source.slice(node.init.start,node.init.end)})`;
 if(component==='BudgetSheet')expression=`__budgetSheet(${vnode},${api},${source.slice(node.init.start,node.init.end)})`;
 if(component==='PlanNotice')expression=`__auditNotice(${vnode},${source.slice(node.init.start,node.init.end)})`;
 if(component==='RouteCompareSheet')expression=routePartyComponent(source.slice(node.init.start,node.init.end));
 if(component==='DayRhythm')expression=source.slice(node.init.start,node.init.end).replaceAll('"调整第 "','"高级设置 · 调整第 "');
 if(component==='ResultHero')expression=`__budgetHero(${vnode},${source.slice(node.init.start,node.init.end).replaceAll('"预估总费用"','"人均预估总费用"').replaceAll('住宿为酒店实时报价','住宿按日期与人数查询的渠道均价').replaceAll('住宿为经验估算','住宿价格来源见费用明细')})`;
 if(expression){counts[component]=(counts[component]||0)+1;replacements.push({start:node.init.start,end:node.init.end,text:expression});}});
 if(!isResult){
  let travelers,travelerId,roomsBound=0,labelNode,staysArray,dateRef,transportRef,transportArray;
  walk(ast,node=>{if(node.type==='Property'&&node.key?.name==='travelers'&&node.value.type==='MemberExpression'&&node.value.property.name==='value'){travelers=source.slice(node.value.start,node.value.end);travelerId=node.value.object.name}
   if(node.type==='CallExpression'&&node.arguments[0]?.value==='label'&&source.slice(node.start,node.end).includes('同行人数'))labelNode=node;
   if(node.type==='CallExpression'&&node.arguments[1]?.type==='ObjectExpression'&&node.arguments[1].properties.some(p=>p.key.name==='key'&&p.value.value===5)&&node.arguments[2]?.type==='ArrayExpression')staysArray=node.arguments[2];
   if(node.type==='CallExpression'&&node.arguments[1]?.type==='ObjectExpression'&&node.arguments[1].properties.some(p=>p.key.name==='key'&&p.value.value===3)&&node.arguments[2]?.type==='ArrayExpression'&&source.slice(node.start,node.end).includes('transportation'))transportArray=node.arguments[2];
   if(node.type==='ArrowFunctionExpression'&&source.slice(node.start,node.end).includes('travelers:')&&node.body.type==='BlockStatement'&&node.end-node.start<3000){walk(node,child=>{if(child.type==='VariableDeclarator'&&child.id.type==='ArrayPattern'&&child.init?.type==='LogicalExpression'&&child.init.left.type==='MemberExpression')dateRef=source.slice(child.init.left.start,child.init.left.end)})}
   if(node.type==='Property'&&node.key?.name==='transportation'&&node.value.type==='MemberExpression'&&node.value.property.name==='transportation')transportRef=source.slice(node.value.start,node.value.end);
  });
  if(!travelers||!travelerId||!labelNode||!staysArray||!dateRef||!transportRef)throw new Error('Missing home party / date bindings');
  if(!transportArray)throw new Error('No transport guidance boundary');
  replacements.push({start:labelNode.start,end:labelNode.end,text:`${vnode}('div',null,[${vnode}(__ExperiencePicker,{modelValue:__experience.value,city:${transportRef.split('.')[0]}.city,'onUpdate:modelValue':v=>(__experience.value=v)}),${vnode}(__DiningPicker,{modelValue:__dining.value,'onUpdate:modelValue':v=>(__dining.value=v)})])`});
  replacements.push({start:transportArray.end-1,end:transportArray.end-1,text:`,${vnode}(__LonghaulPicker,{modelValue:__longhaulMode.value,transportation:${transportRef},'onUpdate:modelValue':v=>(__longhaulMode.value=v)})`});
  replacements.push({start:staysArray.start+1,end:staysArray.start+1,text:`${vnode}(__PartyPicker,{travelers:${travelers},rooms:__partyRooms.value,vehicles:__partyVehicles.value,transportation:${transportRef},'onUpdate:travelers':v=>(${travelers}=v),'onUpdate:rooms':v=>(__partyRooms.value=v),'onUpdate:vehicles':v=>(__partyVehicles.value=v)}),`});
  walk(ast,node=>{
   if(node.type==='VariableDeclarator'&&node.id.name===travelerId){const ref=node.init.callee.name;replacements.push({start:node.end,end:node.end,text:`,__partyRooms=${ref}(null),__partyVehicles=${ref}(null),__experience=${ref}({mode:'balanced',interests:[]}),__longhaulMode=${ref}('ground'),__dining=${ref}({cuisines:['local']})`})}
   if(node.type==='Property'&&node.key?.name==='travelers'&&source.slice(node.value.start,node.value.end)===travelers)replacements.push({start:node.end,end:node.end,text:',rooms:__partyRooms.value,vehicle_count:__partyVehicles.value,experience:__experience.value,longhaul_mode:__longhaulMode.value,dining:__dining.value'});
   if(node.type==='ObjectExpression'&&node.properties.some(p=>p.key?.name==='modelValue'&&p.value.type==='MemberExpression')&&node.properties.some(p=>p.key?.name==='nights')&&node.properties.some(p=>p.key?.name==='city')){
    replacements.push({start:node.end-1,end:node.end-1,text:`,travelers:${travelers},rooms:__partyRooms.value,startDate:${dateRef}?.[0]?.format('YYYY-MM-DD')`});roomsBound++;
   }
  });if(roomsBound!==1)throw new Error('Unexpected hotel input party binding '+roomsBound);
  let windows=0;walk(ast,node=>{
   if(node.type!=='CallExpression'||node.arguments?.[0]?.value!=='details'||!source.slice(node.start,node.end).includes('每日游览时间'))return;
   let ref;walk(node,child=>{if(!ref&&child.type==='CallExpression'&&child.arguments?.[0]?.type==='MemberExpression'&&child.arguments[0].property?.name==='value'&&child.arguments[1]?.type==='ArrowFunctionExpression')ref=source.slice(child.arguments[0].start,child.arguments[0].end)});
   if(!ref)throw new Error('Cannot locate day-window model');
   replacements.push({start:node.start,end:node.end,text:`${vnode}(__DayWindows,{modelValue:${ref},'onUpdate:modelValue':values=>(${ref}=values)})`});windows++;
  });if(windows!==1)throw new Error('Unexpected daily-window template count '+windows);
 }
 for(const item of replacements.sort((a,b)=>b.start-a.start))source=source.slice(0,item.start)+item.text+source.slice(item.end);
 const required=isResult?['TripNights','StaySheet','WeatherSummary','DayTimeline','BaseRow','BudgetSheet','ResultHero','PlanNotice','RouteCompareSheet','DayRhythm']:['NightStays','WeatherStrip'];for(const c of required)if(counts[c]!==1)throw new Error('Unexpected component count '+c+':'+counts[c]);
 if(!isResult)source=source.replaceAll('逐晚填写酒店或住宿区域','按入住时间分段选择住宿').replaceAll('每晚住在哪里？','这次打算住在哪里？').replaceAll('已订可逐晚填写；未订先生成草案，再确认每晚住宿区域。优先连住，减少搬运行李。','已订可按连续入住时间分段选择；未订先看路线，再按城市点选推荐片区。无需逐晚重复填写。');
 source=`import {createPlaceNotes as __createPlaceNotes,createLazyInsights as __createLazyInsights} from './${assetNames.get('place-notes.js')}';\n${isResult?'const __PlaceNotes=__createPlaceNotes('+vnode+','+api+');const __LazyInsights=__createLazyInsights('+vnode+');':''}\nimport {createDiningPicker as __createDiningPicker,xhsBadge as __xhsBadge} from './${assetNames.get('xhs-ui.js')}';\nimport {planRevision as __planRevision,mapRevision as __mapRevision,invalidatePlanDays as __invalidatePlanDays} from './${assetNames.get('route-sync.js')}';\nimport {createExperiencePicker as __createExperiencePicker,createLonghaulPicker as __createLonghaulPicker,createAuditNotice as __auditNotice} from './${assetNames.get('trip-guidance.js')}';\nimport {createPartyPicker as __createPartyPicker,createBudgetHero as __budgetHero,createBudgetSheet as __budgetSheet} from './${assetNames.get('budget-ui.js')}';\nimport {framePlaybackLeg as __framePlaybackLeg} from './${assetNames.get('playback-camera.js')}';\nimport {createStayPlanner as __stayPlanner,readOnlyStayRow as __readOnlyStayRow,compactWeather as __compactWeather,compactDayWeather as __compactDayWeather,createDayWindows as __createDayWindows} from './${adapterName}';\n${!isResult?'const __DiningPicker=__createDiningPicker('+vnode+');const __ExperiencePicker=__createExperiencePicker('+vnode+');const __LonghaulPicker=__createLonghaulPicker('+vnode+');const __PartyPicker=__createPartyPicker('+vnode+');const __DayWindows=__createDayWindows('+vnode+');':''}\n`+source;
 acorn.parse(source,{ecmaVersion:'latest',sourceType:'module'});files.set(name,source);edited.add(name);console.log(name,counts);
}
// Keep the save API adapter's complete response, including the authoritative itinerary.
const formatFile=[...files].find(([n,s])=>s.includes('transits:a.data.transits||null'));
if(!formatFile)throw Error('Missing save response adapter');
const formatSource=formatFile[1].replace('transits:a.data.transits||null','transits:a.data.transits||null,data:a.data.data||null');
files.set(formatFile[0],formatSource);edited.add(formatFile[0]);
const timelineFile=[...files].find(([n])=>n.startsWith('result-timeline-'));
if(!timelineFile)throw Error('Missing normalized timeline');
{let source=timelineFile[1],ast=acorn.parse(source,{ecmaVersion:'latest',sourceType:'module'}),patches=[];
walk(ast,n=>{if(n.type==='ObjectExpression'&&n.properties.some(p=>p.key?.name==='dayIndex')&&n.properties.some(p=>p.key?.name==='description')&&n.properties.some(p=>p.key?.name==='kind')){patches.push({start:n.end-1,text:',xhs_sources:Array.isArray(n.xhs_sources)?n.xhs_sources:[]'});}});
if(patches.length!==2)throw Error('Unexpected timeline source boundaries '+patches.length);
for(const patch of patches.sort((a,b)=>b.start-a.start))source=source.slice(0,patch.start)+patch.text+source.slice(patch.start);
files.set(timelineFile[0],source);edited.add(timelineFile[0]);}
integrate(result[0],true);integrate(entry,false);
let grew=true;while(grew){grew=false;for(const [name,s]of files)if(!edited.has(name)&&[...edited].some(target=>s.includes(target))){edited.add(name);grew=true;}}
const renamed=new Map([...edited].map(n=>[n,n.replace(/\.js$/,'-'+version+'.js')]));
fs.mkdirSync(out,{recursive:true});fs.cpSync(base,out,{recursive:true});const outAssets=path.join(out,'assets');
for(const [name,source]of files){let next=source;for(const [from,to]of renamed)next=next.replaceAll(from,to);if(renamed.has(name)){acorn.parse(next,{ecmaVersion:'latest',sourceType:'module'});fs.writeFileSync(path.join(outAssets,renamed.get(name)),next);}}
for(const [name,source]of moduleSources)fs.writeFileSync(path.join(outAssets,name),source);
const css=fs.readFileSync(path.join(root,'styles.css'),'utf8');const cssName='eztrip-lodging-'+crypto.createHash('sha256').update(css).digest('hex').slice(0,12)+'.css';fs.writeFileSync(path.join(outAssets,cssName),css);
let nextHtml=html;for(const [from,to]of renamed)nextHtml=nextHtml.replaceAll(from,to);nextHtml=nextHtml.replace('</head>',`<link rel="stylesheet" href="/assets/${cssName}">\n  </head>`);fs.writeFileSync(path.join(out,'index.html'),nextHtml);
fs.writeFileSync(path.join(out,'lodging-build.json'),JSON.stringify({version,baseEntry:entry,entry:renamed.get(entry),components:result[0],renamed:[...renamed],baseIndexSha256:crypto.createHash('sha256').update(html).digest('hex')},null,2)+'\n');
console.log('Built',out,'renamed',renamed.size,'modules');
