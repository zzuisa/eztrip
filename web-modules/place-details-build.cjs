module.exports=function({source,ast,walk,replacements,vnode}){let matches=0;walk(ast,n=>{
 if(n.type!=='ArrayExpression'||!n.elements?.some(e=>e?.type==='CallExpression'&&e.arguments[0]?.name==='Yy'))return;
 const elements=n.elements;const google=elements.find(e=>e?.type==='CallExpression'&&e.arguments[0]?.name==='Yy');
 const slice=e=>source.slice(e.start,e.end);const googleIndex=elements.indexOf(google);
 const description=elements.find(e=>e&&slice(e).includes('u("section",Th,'));
 const remaining=elements.slice(googleIndex+1).filter(e=>e!==description);
 const feedback=remaining.findIndex(e=>e?.type==='CallExpression'&&e.arguments[0]?.name==='Di');
 if(feedback<0)throw Error('No detail feedback boundary');
 const props=source.slice(google.arguments[1].start,google.arguments[1].end);
 const collapsed=`${vnode}(__LazyInsights,{component:Yy,...${props}})`;
 const panel=`${vnode}(__PlaceNotes,{key:e.item.key,resultId:e.resultId,item:e.item})`;
 const content=[...elements.slice(0,googleIndex).map(slice),...(description?[slice(description)]:[]),panel,...remaining.slice(0,feedback).map(slice),collapsed,...remaining.slice(feedback).map(slice)];
 replacements.push({start:n.start,end:n.end,text:'['+content.join(',')+']'});matches++;
});if(matches!==1)throw Error('Unexpected detail layout boundary '+matches);};
