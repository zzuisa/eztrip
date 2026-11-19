import {request,message} from './dom.js';

export const money=(value,currency='EUR')=>new Intl.NumberFormat('zh-CN',{style:'currency',currency,maximumFractionDigits:2}).format(Number(value)||0);
const confidence=c=>({quote:'所选酒店渠道均价',quote_sample:'同日期酒店样本均价',range:'历史价位参考',estimate:'参考估算',mixed:'实价与参考估算混合'})[c]||'参考估算';

export function createPartyPicker(h){return {name:'PartyPicker',props:['travelers','rooms','vehicles','transportation','disabled'],emits:['update:travelers','update:rooms','update:vehicles'],
 render(){const n=Number(this.travelers)||1;const driving=/自驾|开车|租车|驾车/.test(this.transportation||'');
  const select=(label,value,options,change)=>h('label',null,[h('span',null,label),h('select',{'aria-label':label,disabled:this.disabled,value:value??'',onChange:e=>change(e.target.value?Number(e.target.value):null)},options.map(([v,t])=>h('option',{value:v},t)))]);
  return h('section',{class:'ez-party-picker','aria-label':'同行与住宿安排'},[
   select('同行人数',n,Array.from({length:20},(_,i)=>[i+1,(i+1)+'人']),v=>{this.$emit('update:travelers',v);this.$emit('update:rooms',null);this.$emit('update:vehicles',null)}),
   select('房间数量',this.rooms,[['',`自动（${Math.ceil(n/2)}间）`],...Array.from({length:n},(_,i)=>[i+1,(i+1)+'间'])],v=>this.$emit('update:rooms',v)),
   ...(driving?[select('车辆数量',this.vehicles,[['',`自动（${Math.ceil(n/5)}辆）`],...Array.from({length:n-Math.ceil(n/5)+1},(_,i)=>[i+Math.ceil(n/5),(i+Math.ceil(n/5))+'辆'])],v=>this.$emit('update:vehicles',v))]:[]),
   h('p',{class:'ez-note'},'人数暂按成人计；默认每间最多2人、每辆车5座。酒店查询会使用这里的人数和房间数。')
  ]);
 }};}

export function createBudgetHero(h,Original){return {name:'PerPersonBudgetHero',props:Original.props,inheritAttrs:false,render(){
 Original.__scopeId=this.$options.__scopeId;
 const d=this.budget?.detail,p=d?.party;
 return h('div',{class:'ez-budget-hero'},[h(Original,{...this.$props,...this.$attrs}),...(p?[h('p',{class:'ez-budget-group'},
  [h('span',null,`${p.travelers}人同行 · ${p.rooms}间房${p.vehicles?' · '+p.vehicles+'辆车':''} ｜ 整团预估 ${money(d.group_totals?.total,this.currency)}${d.needs_price_refresh?' · 价格待重新查询':''}`),h('button',{type:'button',class:'ez-secondary','aria-label':'调整同行人数',onClick:()=>this.$emit('open-budget')},'调整同行人数 / 房间数')])]:[])]);
 }};}

export function createBudgetSheet(h,api,Original){const Party=createPartyPicker(h);return {
 name:'PartyBudgetSheet',props:{...Original.props,resultId:{},rev:{}},emits:['close','open-stay'],inheritAttrs:false,
 data(){return {fresh:null,loading:false,error:'',travelers:1,rooms:null,vehicles:null,localRev:null}},
 computed:{value(){return this.fresh||this.budget},detail(){return this.value?.detail||{}},party(){return this.detail.party||{travelers:1,rooms:1,vehicles:0}}},
 watch:{open(value){if(value){this.fresh=null;this.localRev=null;this.error='';this.initialize();this.lock();this.$nextTick(()=>this.$refs.dialog?.focus())}else this.unlock()},budget(){if(!this.loading)this.fresh=null}},
 mounted(){if(this.open){this.initialize();this.lock()}},beforeUnmount(){this.unlock()},
 methods:{
  initialize(){const p=this.party;this.travelers=p.travelers;this.rooms=p.rooms_assumed?null:p.rooms;this.vehicles=p.vehicles_assumed?null:p.vehicles},
  lock(){if(this.locked)return;this.returnFocus=document.activeElement;this.oldOverflow=document.documentElement.style.overflow;document.documentElement.style.overflow='hidden';this.locked=true},
  unlock(){if(!this.locked)return;document.documentElement.style.overflow=this.oldOverflow||'';this.locked=false;this.returnFocus?.isConnected&&this.returnFocus.focus({preventScroll:true})},
  close(){if(!this.loading)this.$emit('close')},
  keydown(e){if(e.key==='Escape')this.close();if(e.key==='Tab'){const controls=[...this.$refs.dialog.querySelectorAll('button:not([disabled]),select:not([disabled]),a[href]')];const first=controls[0],last=controls.at(-1);if(e.shiftKey&&(document.activeElement===first||document.activeElement===this.$refs.dialog)){e.preventDefault();last?.focus()}else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first?.focus()}}},
  async refresh(){if(this.loading||!this.canEdit||!this.resultId)return;this.loading=true;this.error='';try{
   const data=await request(api,`/api/travel-plan/${encodeURIComponent(this.resultId)}/budget/refresh`,{travelers:this.travelers,rooms:this.rooms,vehicle_count:this.vehicles,rev:this.localRev??this.rev});
   this.fresh={...data.total_budget,total_attractions:data.total_budget.tickets,total_meals:data.total_budget.food,total_transportation:data.total_budget.transport,total_hotels:data.total_budget.lodging};this.localRev=data.rev;
   window.dispatchEvent(new CustomEvent('eztrip:budget-saved',{detail:{id:this.resultId,data}}));
  }catch(e){this.error=message(e)}finally{this.loading=false}},
 },
 render(){if(!this.open)return null;const d=this.detail,p=this.party,b=this.value;const m=v=>money(v,this.currency);const group=d.group_totals||{},person=d.per_person||{};
 const section=(title,children)=>h('section',{class:'ez-budget-section'},[h('h3',null,title),...children]);
 const rows=[['tickets','门票'],['food','餐饮'],['transport','交通'],['lodging','住宿']];
 const car=d.transport||{},rental=d.rental;
 const shared=[['rental','租车费'],['fuel','油费 / 电费'],['tolls','过路费'],['parking','停车费'],['taxi','打车费']].filter(([k])=>Number(car[k])>0);
 const content=[
  h('header',{class:'ez-dialog-head'},[h('h2',null,'费用明细'),h('button',{class:'ez-icon',type:'button','aria-label':'关闭费用明细',disabled:this.loading,onClick:this.close},'×')]),
  h('div',{class:'ez-budget-total'},[h('span',null,'人均预估总费用'),h('strong',null,m(b?.total)),h('p',null,`${p.travelers}人同行 · 整团预估 ${m(group.total)}`)]),
  h(Party,{disabled:this.loading||!this.canEdit,travelers:this.travelers,rooms:this.rooms,vehicles:this.vehicles,transportation:car.pref,'onUpdate:travelers':v=>this.travelers=v,'onUpdate:rooms':v=>this.rooms=v,'onUpdate:vehicles':v=>this.vehicles=v}),
  h('button',{type:'button',class:'ez-primary',disabled:this.loading||!this.canEdit,onClick:this.refresh},this.loading?'正在按日期与人数查价…':'按人数与房间数重新查价'),
  ...(!this.canEdit?[h('p',{class:'ez-note'},'当前是共享只读视图。请在创建行程的浏览器中打开，或登录站长后修改同行人数；共享访客不能改写此行程。')]:[]),
  ...(this.error?[h('p',{class:'ez-error',role:'alert'},this.error)]:[]),
  ...(d.needs_price_refresh?[h('p',{class:'ez-review-note'},'目前按已有参考价换算人均费用，重新查价后更新酒店日期与人数匹配价格。')]:[]),
  h('table',{class:'ez-budget-table'},[h('thead',null,[h('tr',null,[h('th',null,'项目'),h('th',null,'人均'),h('th',null,'整团')])]),h('tbody',null,rows.map(([key,title])=>h('tr',null,[h('th',null,title),h('td',null,m(person[key]??b?.[{tickets:'total_attractions',food:'total_meals',transport:'total_transportation',lodging:'total_hotels'}[key]])),h('td',null,m(group[key]))])))]),
  ...shared.length?[section('车辆费用分摊',[
   h('p',{class:'ez-note'},`自驾按${p.vehicles||1}辆车计；${p.travelers}人均摊。公共交通、门票与餐饮按每人计。`),h('p',{class:'ez-note'},'油费、过路费和停车费按路线与城市参考价估算；租车优先使用填写的平台单车日价。'),
   h('table',{class:'ez-budget-table'},[h('thead',null,[h('tr',null,[h('th',null,'项目'),h('th',null,'人均'),h('th',null,'整团')])]),h('tbody',null,shared.map(([key,title])=>h('tr',null,[h('th',null,title),h('td',null,m(car.per_person?.[key])),h('td',null,m(car[key]))])))]),
   ...(rental?[h('p',{class:'ez-note'},`${m(rental.daily_eur)} / 辆 / 天 × ${rental.days}天 × ${rental.vehicles}辆；${rental.source||''}。${rental.note||''}`)]:[])
  ])]:[],
  ...(car.public_transport>0?[section('公共交通费用',[
   h('p',null,`人均 ${m(car.per_person?.public_transport)} · 整团 ${m(car.public_transport)}`),
   h('p',{class:'ez-note'},'按个人票价汇总；市内交通比较单程票与日票，已选路线按该方案人数换算。'),
   h('p',{class:'ez-note'},'来源：'+(car.source||'路线与城市参考票价'))
  ])]:[]),
  ...(d.long_haul?.some(leg=>leg.group_total>0)?[section('到达、城际与返程',[
   ...d.long_haul.filter(leg=>leg.group_total>0).map(leg=>h('article',{class:'ez-hotel-price'},[
    h('b',null,`第${leg.day}天 · ${leg.from||'出发地'} → ${leg.to||'目的地'}`),
    h('p',null,`${leg.label||'交通'} · 人均 ${m(leg.cost)} · 整团 ${m(leg.group_total)}`),
    h('p',{class:'ez-note'},leg.confidence==='live'?'按已选路线报价换算；以订票页面为准。':'按路线与参考票价估算；以铁路、航空或出行平台为准。')
   ]))
  ])]:[]),
  ...(d.lodging?[section('住宿价格',[
   h('p',{class:'ez-note'},`${d.lodging.nights}晚 · ${p.rooms}间房 · 整团 ${m(d.lodging.total)} · 人均 ${m(d.lodging.total/p.travelers)}`),
   ...(d.lodging.by_city||[d.lodging]).map(part=>h('article',{class:'ez-hotel-price'},[
    h('b',null,[part.city,part.stay_name||part.hotel].filter(Boolean).join(' · ')||'住宿'),
    h('span',{class:'ez-price-tag'},confidence(part.confidence)),
    h('p',null,`${part.check_in||''} → ${part.check_out||''} · ${part.nights}晚`),
    h('p',null,part.per_room_per_night!=null?`${m(part.per_room_per_night)} / 间 / 晚 × ${part.rooms||p.rooms}间 × ${part.nights}晚 = ${m(part.total)}`:`整段 ${m(part.total)}`),
    h('p',{class:'ez-note'},part.note||''),h('small',null,`来源：${part.source||'参考估算'}${part.sample_count?' · '+part.sample_count+'个报价样本':''}`)
   ])),h('button',{type:'button',class:'ez-secondary',disabled:this.loading,onClick:()=>{this.unlock();this.$emit('open-stay')}},'住在哪里')
  ])]:[]),
  ...(d.per_day?.length?[section('每天人均费用',[h('p',{class:'ez-note'},'含门票、餐饮与交通；住宿和整段租车费用在上方单列。'),h('ul',{class:'ez-budget-days'},d.per_day.map(day=>h('li',null,[h('span',null,'第'+day.day+'天'),h('b',null,m(day.total))])))])]:[]),
  h('ul',{class:'ez-note'},(d.notes||[]).map(note=>h('li',null,note)))
 ];
 return h('div',{class:'ez-stay-backdrop',onClick:e=>{if(e.target===e.currentTarget)this.close()}},[h('section',{class:'ez-stay-dialog ez-budget-dialog',role:'dialog','aria-modal':'true','aria-label':'费用明细',tabindex:-1,ref:'dialog',onKeydown:this.keydown},content)]);
 }
};}
