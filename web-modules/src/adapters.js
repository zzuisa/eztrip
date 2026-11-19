import {StayPlanner} from './stay-planner.js';

export function createStayPlanner(h,api,Original,mode='inline') {
 if(mode==='inline')return {name:'StaySummary',props:Original.props,emits:['recommend','saved'],
 mounted(){this.onStaySaved=e=>{if(e.detail?.id===this.tripId)this.$emit('saved',e.detail.data)};window.addEventListener('eztrip:stay-saved',this.onStaySaved);window.addEventListener('eztrip:budget-saved',this.onStaySaved)},
 beforeUnmount(){window.removeEventListener('eztrip:stay-saved',this.onStaySaved);window.removeEventListener('eztrip:budget-saved',this.onStaySaved)},render(){
  if(!this.nights)return null;
  const selected=(this.stays||[]).filter(s=>s.kind==='hotel');
  const names=[...new Set(selected.map(s=>s.name).filter(Boolean))];
  return h('section',{class:'ez-stay-summary','aria-label':'住宿安排概览'},[
   h('div',null,[h('b',null,'住宿安排'),h('p',{class:'ez-note'},names.length?names.join(' · '):'前往「住在哪里」，按城市选择片区和具体酒店。')]),
   h('button',{type:'button',class:'ez-secondary',onClick:()=>this.$emit('recommend')},'住在哪里')
  ]);
 }};
 return {
  name:mode==='input'?'StayBlocksInput':mode==='modal'?'StayBlocksSheet':'StayBlocksPlanner',
  props:{...Original.props,travelers:{},rooms:{},startDate:{}},inheritAttrs:false,
  render(){return h('div',{class:mode==='modal'?'ez-stay-sheet-host':'ez-stay-component'});},
  mounted(){this.stayController=new StayPlanner(this.$el,api,this.$props,{input:mode==='input',modal:mode==='modal',onSaved:data=>this.$emit('saved',data),onClose:()=>this.$emit('close'),onModel:values=>this.$emit('update:modelValue',values)});},
  updated(){this.stayController?.update(this.$props)},
  beforeUnmount(){this.stayController?.destroy()},
 };
}

export function readOnlyStayRow(h,Original){
 return {name:'ReadOnlyStayRow',props:Original.props,inheritAttrs:false,render(){
  if(this.kind==='stay-none')return null;
  Original.__scopeId=this.$options.__scopeId;
  return h(Original,{...this.$props,...this.$attrs,...(this.kind==='stay'?{action:undefined,onAction:undefined}:{})});
 }};
}

function missingReason(report,missing) {
 if(report?.status==='date_required')return '还没有选择出行日期，选定日期后即可查询对应天气。';
 const dates=missing.map(d=>d.date).filter(Boolean).sort();
 const today=new Date().toISOString().slice(0,10);
 const far=dates.length&&dates[0]>new Date(Date.now()+16*86400000).toISOString().slice(0,10);
 if(far)return '出行时间还较远，尚未进入可靠的天气预报范围。临近出发时再查看即可。';
 if(dates.length&&dates.at(-1)<today)return '该日期的历史天气暂时不可用，稍后可再次查询。';
 return '天气服务暂未提供这些日期的数据，可能超出预报范围或服务暂时不可用。临近出发时再查看即可。';
}
function notice(h,report,missing){return h('details',{class:'ez-weather-pending'},[
 h('summary',{'aria-label':'天气待更新，查看原因'},[h('span',{'aria-hidden':'true',class:'ez-weather-cloud'},'☁'),h('span',null,'天气待更新'),h('span',{'aria-hidden':'true',class:'ez-weather-info'},'ⓘ')]),
 h('p',null,missingReason(report,missing))
]);}
export function compactWeather(h,Original) {
 return {name:'CompactWeather',props:Original.props,inheritAttrs:false,
  render(){
   Original.__scopeId=this.$options.__scopeId;
   const report=this.report;const days=report?.days||[];
   const valid=days.filter(d=>d.status!=='unavailable'&&(d.temp_max!=null||d.temp_min!=null||d.weather_code!=null));
   const missing=days.filter(d=>!valid.includes(d));
   if(report&&(missing.length||['date_required','unavailable'].includes(report.status))){
    if(!valid.length)return notice(h,report,missing);
    const filtered={...report,days:valid,period:report.period?.status==='unavailable'?null:report.period};
    return h('div',{class:'ez-weather-mixed'},[h(Original,{...this.$props,...this.$attrs,report:filtered}),notice(h,report,missing)]);
   }
   return h(Original,{...this.$props,...this.$attrs});
  }
 };
}
export function compactDayWeather(h,Original) {
 return {name:'DayWithoutEmptyWeather',props:Original.props,inheritAttrs:false,
  render(){Original.__scopeId=this.$options.__scopeId;return h(Original,{...this.$props,...this.$attrs,weather:this.weather?.status==='unavailable'?undefined:this.weather});}
 };
}

export function createDayWindows(h) {
 return {name:'DayWindowPresets',props:{modelValue:{type:Array,default:()=>[]}},emits:['update:modelValue'],
  data(){return {expanded:false}},
  methods:{
   applyWindow(start,end){this.$emit('update:modelValue',this.modelValue.map(w=>({...w,start,end})))},
   updateDay(index,key,value){this.$emit('update:modelValue',this.modelValue.map((w,i)=>i===index?{...w,[key]:value}:w))}
  },
  render(){const presets=[['09:00','19:00','轻松'],['09:00','21:00','标准'],['08:00','20:00','早出']];return h('section',{class:'ez-window-picker','aria-label':'每日出行时间'},[
   h('b',null,'每天的出行时间'),h('p',{class:'ez-note'},'一键设置全部日期；首日出发和末日返回也计入这段时间。'),
   h('div',{class:'ez-window-presets'},presets.map(([start,end,label])=>h('button',{type:'button',class:'ez-secondary'+(this.modelValue.every(w=>w.start===start&&w.end===end)?' on':''),'aria-pressed':this.modelValue.every(w=>w.start===start&&w.end===end),onClick:()=>this.applyWindow(start,end)},[h('b',null,label),h('small',null,start+'–'+end)]))),
   h('details',{open:this.expanded},[h('summary',{onClick:e=>{e.preventDefault();this.expanded=!this.expanded}},'高级设置 · 每天旅途时间微调'),...(this.expanded?this.modelValue.map((w,i)=>h('div',{class:'ez-window-day'},[h('span',null,'第 '+w.day+' 天'),h('label',null,['开始',h('input',{type:'time',value:w.start,'aria-label':'第'+w.day+'天开始时间',onInput:e=>this.updateDay(i,'start',e.target.value)})]),h('label',null,['结束',h('input',{type:'time',value:w.end,'aria-label':'第'+w.day+'天结束时间',onInput:e=>this.updateDay(i,'end',e.target.value)})])])):[])])
  ])}
 };
}
