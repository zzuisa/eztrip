const styles=[['balanced','观光与体验均衡','当地代表性景点为主，留约1/4时间体验当地生活。'],['culture','人文深度','愿意多看艺术、历史与展馆，仍保留休息和生活体验。'],['playful','当地玩乐优先','保留必看景点，增加约4成手作、表演和当地娱乐。'],['relax','放松慢游','少换地点，多留休息、温泉、公园或咖啡时光。']];
const interests=[['spa','温泉水疗'],['skiing','滑雪'],['skating','滑冰'],['markets','当地市集'],['live_show','现场演出'],['local_craft','手作 / 烹饪体验'],['cruise','游船'],['nature','自然与轻户外'],['family','亲子娱乐']];

export function createExperiencePicker(h){return {name:'ExperiencePicker',props:{modelValue:{type:Object,default:()=>({mode:'balanced',interests:[]})},city:{}},emits:['update:modelValue'],
 methods:{setMode(mode){this.$emit('update:modelValue',{...this.modelValue,mode})},toggle(id){const selected=this.modelValue.interests||[];this.$emit('update:modelValue',{...this.modelValue,interests:selected.includes(id)?selected.filter(x=>x!==id):[...selected,id].slice(0,5)})}},
 render(){const selected=this.modelValue.interests||[];return h('section',{class:'ez-experience-picker','aria-label':'旅行体验偏好'},[
  h('h3',null,'这趟旅行，想怎样搭配观光和体验？'),h('p',{class:'ez-note'},'默认兼顾当地代表性景点与生活体验，避免连续堆叠博物馆。比例是引导，会按城市特色、交通和体力调整。'),
  h('div',{class:'ez-experience-modes'},styles.map(([id,title,description])=>h('button',{type:'button',class:'ez-area'+(this.modelValue.mode===id?' selected':''),'aria-pressed':this.modelValue.mode===id,onClick:()=>this.setMode(id)},[h('b',null,title),h('span',null,description)]))),
  h('b',null,'还想尝试什么？最多选5项'),h('div',{class:'ez-experience-interests'},interests.map(([id,title])=>h('button',{type:'button',class:'ez-secondary'+(selected.includes(id)?' on':''),'aria-pressed':selected.includes(id),disabled:selected.length>=5&&!selected.includes(id),onClick:()=>this.toggle(id)},title))),
  h('p',{class:'ez-note'},'系统会在线检索适合当地的场所与开放信息。季节、天气、装备和预约需核实；温泉、滑雪等通常需要半天，不适合时改选其他体验。')
 ])}
};}

export function createLonghaulPicker(h){return {name:'LonghaulPicker',props:['modelValue','transportation'],emits:['update:modelValue'],render(){if(/自驾|租车|开车/.test(this.transportation||''))return null;return h('section',{class:'ez-longhaul-picker','aria-label':'跨国长途设置'},[
 h('label',null,[h('span',null,'跨城 / 跨国长途方式'),h('select',{'aria-label':'长途交通方式',value:this.modelValue||'ground',onChange:e=>this.$emit('update:modelValue',e.target.value)},[
 h('option',{value:'ground'},'地面交通：火车 / 巴士'),h('option',{value:'flight'},'允许飞机：实际航班待核实'),h('option',{value:'auto'},'综合比较：未核实航班作为备选')])]),
 h('p',{class:'ez-note'},'地面交通不会因为距离长而自动变成飞机。长途可能跨天；地面路线对比仅含公交、火车与自驾，不代表已经查询航班。')
 ])}};}

export function createAuditNotice(h,Original){return {name:'TruthfulAuditNotice',props:Original.props,inheritAttrs:false,render(){
 const r=this.review||{},gate=r.quality_gate;const unresolved=r.verdict==='revise'||gate&&gate.state!=='passed'||['failed','skipped'].includes(r.status);
 if(!unresolved){Original.__scopeId=this.$options.__scopeId;return h(Original,{...this.$props,...this.$attrs})}
 const messages=[...new Set([...(this.warnings||[]),...(r.issues||[]).filter(i=>i.severity==='high').map(i=>i.message)])];
 return h('aside',{class:'ez-audit-notice',role:'status'},[h('b',null,'行程草案 · 仍需调整'),h('p',null,gate?.summary||'评审尚未通过，请先处理交通、时间或偏好问题。'),...(r.projection_note?[h('p',null,r.projection_note)]:[]),
 ...(messages.length?[h('details',null,[h('summary',null,`查看待调整问题（${messages.length}项）`),h('ul',null,messages.map(m=>h('li',null,m)))])]:[])
 ]);
 }};}
