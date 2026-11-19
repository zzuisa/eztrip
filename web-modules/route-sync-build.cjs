/** Scoped AST patches for the preserved frontend's editing and playback state. */
module.exports=function({source,ast,walk,replacements,isResult}){
 const counts={};const add=(node,text,key)=>{replacements.push({start:node.start,end:node.end,text});counts[key]=(counts[key]||0)+1};
 if(!isResult)return;
 const src=n=>source.slice(n.start,n.end);
 walk(ast,node=>{
  // Ignore an old save response if the user has continued editing while it was in flight.
  if(node.type==='IfStatement'&&node.test.type==='SequenceExpression'&&src(node.test).includes('R.filled.length')){
   add(node,`if(x===P){if(R.data){t.value=La(R.data);Bo(n,R.data)}else{${src(node)}}}`,'save');
  }
  if(node.type==='AssignmentExpression'&&src(node)==='t.value={...t.value,days:X}')add(node,'t.value=__invalidatePlanDays(t.value,X)','commit');
  if(node.type==='VariableDeclarator'&&node.id.name==='B'&&node.init?.type==='ArrowFunctionExpression'&&src(node.init).includes('V.key+V.lng+V.lat'))add(node.init,'G=>__mapRevision(G)','map');
  if(node.type==='ObjectExpression'&&node.properties.some(p=>p.key?.name==='onConflict')&&node.properties.some(p=>p.key?.name==='tripPlan')){
   replacements.push({start:node.end-1,end:node.end-1,text:',onSaved:()=>A()'});counts.saved=1;
  }
  // Slideshow routes must use the same travel mode as the map, never a driving duration for transit.
  if(node.type==='FunctionDeclaration'&&node.id.name==='lc'){
   let found=0;walk(node,child=>{if(child.type==='CallExpression'&&child.callee.name==='oi'){
    add(child,`oi(t.map(({from:d,to:f,hint})=>{const vehicle=is({hint,pref:n,distanceM:qu([d.lng,d.lat],[f.lng,f.lat])});return {from:d,to:f,mode:vehicle==='walk'?'walking':['car','taxi'].includes(vehicle)?'driving':'transit'}}))`,'storyMode');found++;
   }});if(found!==1)throw Error('Missing slideshow route query');
  }
  // Every change invalidates the slideshow, captions, route distances and late async responses.
  if(node.type==='VariableDeclaration'&&node.kind==='let'&&node.declarations.length===1&&node.declarations[0].id.name==='ea'){
   replacements.push({start:node.end,end:node.end,text:`let __storyEpoch=0;_e(()=>__planRevision(s.value?.days||[]),()=>{__storyEpoch++;Xt.value=null;Zt.value={legs:{},vehicles:{},distanceM:0};ea=!1;Xe.value=!1;});`});counts.story=1;
  }
  if(node.type==='VariableDeclarator'&&node.id.name==='pn'&&node.init?.type==='ArrowFunctionExpression'&&src(node.init).includes('sc(a).then')){
   let code=src(node.init).replace('ea=!0,','ea=!0,');
   code=code.replace('lc(E.value,ta.value).then(_=>{Zt.value=_})','((epoch)=>lc(E.value,ta.value).then(_=>{if(epoch===__storyEpoch)Zt.value=_}))(__storyEpoch)');
   code=code.replace('sc(a).then(_=>{_?Xt.value=_:xt({auto:!0})}).catch(()=>{xt({auto:!0})})','((epoch)=>sc(a).then(_=>{if(epoch===__storyEpoch){_?Xt.value=_:xt({auto:!0})}}).catch(()=>{if(epoch===__storyEpoch)xt({auto:!0})}))(__storyEpoch)');
   add(node.init,code,'loadStory');
  }
  if(node.type==='VariableDeclarator'&&node.id.name==='xt'&&node.init?.type==='ArrowFunctionExpression'&&src(node.init).includes('await oc(a,')){
   const code=src(node.init).replace('try{Xt.value=await oc(a,!!g.force)}','try{const epoch=__storyEpoch;const story=await oc(a,!!g.force);if(epoch===__storyEpoch)Xt.value=story}');
   add(node.init,code,'generateStory');
  }
 });
 for(const key of ['save','commit','map','saved','story','loadStory','generateStory','storyMode'])if(counts[key]!==1)throw Error('Unexpected route sync boundary '+key+': '+counts[key]);
};
