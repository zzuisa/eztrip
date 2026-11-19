module.exports=function({source,ast,walk,replacements,vnode}){let timeline=0;walk(ast,n=>{
 if(n.type==='ConditionalExpression'&&n.test.type==='MemberExpression'&&source.slice(n.test.start,n.test.end)==='D.description'){
  replacements.push({start:n.start,end:n.end,text:`${vnode}('div',null,[${source.slice(n.start,n.end)},__xhsBadge(${vnode},D.xhs_sources)])`});timeline++;
 }
 if(n.type==='CallExpression'&&n.arguments[0]?.value==='section'&&n.arguments[2]?.type==='ArrayExpression'&&source.slice(n.start,n.end).includes('m(e.item.description)')){
  replacements.push({start:n.start,end:n.end,text:`${vnode}('div',null,[${source.slice(n.start,n.end)},__xhsBadge(${vnode},e.item.xhs_sources)])`});
 }
});if(timeline!==1)throw Error('Unexpected XHS badge timeline boundary '+timeline);};
