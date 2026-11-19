import {esc,clone,pointValid,message,request,fromNights,expandBlocks,shiftBoundary} from './dom.js';

export class StayPlanner {
 constructor(root,api,props,options={}) {
  this.root=root;this.api=api;this.props={...props};this.options=options;this.id=props.tripId||props.resultId;
  this.reviewPolls=0;this.active=0;this.blocks=[];this.proposal=null;this.busy=false;this.error='';this.accepted=false;this.alive=true;this.recommendBusy=false;this.requests=new Set();this.searchResults=[];this.searching=false;this.hotelToken=0;this.uid=Math.random().toString(36).slice(2);
  this.handleClick=e=>this.click(e);this.handleInput=e=>this.input(e);this.handleChange=e=>this.change(e);this.handleKey=e=>{if(e.key==='Escape'&&options.modal)this.close();if(e.key==='Tab'&&options.modal){const dialog=this.root.querySelector('[role=dialog]');const controls=[...(dialog?.querySelectorAll('button:not([disabled]),input:not([disabled]),summary,[tabindex="0"]')||[])].filter(el=>el.offsetParent!==null);if(!controls.length)return;const first=controls[0],last=controls.at(-1);if(e.shiftKey&&(document.activeElement===first||document.activeElement===dialog)){e.preventDefault();last.focus()}else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first.focus()}}};
  root.addEventListener('click',this.handleClick);root.addEventListener('input',this.handleInput);root.addEventListener('change',this.handleChange);root.addEventListener('keydown',this.handleKey);
  this.externalSave=e=>{if(e.detail?.id===this.id&&e.detail.source!==this.uid){this.options.onSaved?.();void this.load();}};
  window.addEventListener('eztrip:stay-saved',this.externalSave);
  if(options.input){this.total=Number(props.nights)||0;this.blocks=fromNights(props.modelValue,this.total,props.city);this.normalizeAreas();this.accepted=true;this.render();}
  else if(!options.modal || props.open){this.lock();void this.load();}else this.render();
 }
 controller(){const ctl=new AbortController();this.requests.add(ctl);return ctl;}
 async call(path,body){const ctl=this.controller();try{return await request(this.api,path,body,ctl.signal)}finally{this.requests.delete(ctl)}}
 get party(){const n=Number(this.options.input?this.props.travelers:this.proposal?.party?.travelers)||1;return {travelers:n,rooms:Number(this.options.input?this.props.rooms:this.proposal?.party?.rooms)||Math.ceil(n/2)}}
 dates(b){const start=this.proposal?.start_date||this.props.startDate;if(!start)return {};const date=n=>{const d=new Date(start+'T12:00:00Z');d.setUTCDate(d.getUTCDate()+n-1);return d.toISOString().slice(0,10)};return {check_in:date(b.night_start),check_out:date(b.night_end+1)}}
 get totalNights(){return this.total||0}
 get writable(){return this.options.input || Boolean(this.props.canEdit)}
 get complete(){return Boolean(expandBlocks(this.blocks,this.totalNights))}
 get draftKey(){return `eztrip.stay-blocks.v1.${this.id}`}
 saveDraft(){if(!this.id||!this.proposal)return;try{localStorage.setItem(this.draftKey,JSON.stringify({rev:this.proposal.rev,blocks:this.blocks,accepted:this.accepted}));}catch{}}
 restoreDraft(){try{const d=JSON.parse(localStorage.getItem(this.draftKey)||'null');if(d?.rev===this.proposal.rev&&Array.isArray(d.blocks)&&d.blocks.length&&d.blocks[0].night_start===1&&d.blocks.at(-1).night_end===this.total){this.blocks=d.blocks;this.accepted=Boolean(d.accepted);this.active=Math.max(0,this.blocks.findIndex(b=>b.selection?.kind!=='hotel'));}}catch{}}
 async load() {
  if(!this.id)return;this.resetHotels();this.busy=true;this.error='';this.render();
  try{const data=await this.call(`/api/travel-plan/${encodeURIComponent(this.id)}/stay-plan`);if(!this.alive)return;
   this.proposal=data;this.total=data.total_nights;this.blocks=clone(data.saved_blocks?.length?data.saved_blocks:data.blocks);this.accepted=Boolean(data.complete&&this.total);this.active=0;this.restoreDraft();this.scheduleReviewPoll();
   this.normalizeAreas();
  }catch(e){if(this.alive)this.error=message(e)}finally{if(this.alive){this.busy=false;this.render();if(this.proposal&&this.accepted)this.resumeHotels()}}
 }
 update(props){
  const previous=this.props;this.props={...props};
  if(this.options.modal){if(!previous.open&&props.open){this.lock();void this.load();return;}if(previous.open&&!props.open){this.resetHotels();this.focused=false;this.dragging=false;clearTimeout(this.reviewTimer);this.unlock();this.render();return;}}
  if(this.options.input){
   const sig=JSON.stringify(props.modelValue||[]);
   if(sig===this.lastEmitted&&Number(props.nights)===this.total&&props.city===previous.city&&props.travelers===previous.travelers&&props.rooms===previous.rooms&&props.startDate===previous.startDate)return;
   if(Number(props.nights)!==this.total){this.total=Number(props.nights)||0;this.blocks=fromNights(props.modelValue,this.total,props.city);this.active=0;}
   else if(sig!==this.lastEmitted&&sig!==JSON.stringify(previous.modelValue||[])){this.blocks=fromNights(props.modelValue,this.total,props.city);this.active=0;}
   this.normalizeAreas();if(props.travelers!==previous.travelers||props.rooms!==previous.rooms||props.startDate!==previous.startDate){this.resetHotels();this.resumeHotels()}this.render();return;
  }
  const id=props.tripId||props.resultId;if(id!==this.id){this.id=id;void this.load();return}
  if(props.rev!==previous.rev&&!this.busy)void this.load();
  else if(props.canEdit!==previous.canEdit)this.render();
 }
 lock(){if(this.options.modal&&!this.locked){this.returnFocus=document.activeElement;this.previousOverflow=document.documentElement.style.overflow;document.documentElement.style.overflow='hidden';this.locked=true;}}
 unlock(){if(this.locked){document.documentElement.style.overflow=this.previousOverflow||'';this.locked=false;if(this.returnFocus?.isConnected)this.returnFocus.focus({preventScroll:true});}}
 close(){this.resetHotels();this.dragging=false;clearTimeout(this.reviewTimer);this.focused=false;this.saveDraft();this.unlock();this.options.onClose?.();}
 destroy(){this.alive=false;clearTimeout(this.searchTimer);clearTimeout(this.reviewTimer);for(const ctl of this.requests)ctl.abort();this.unlock();window.removeEventListener('eztrip:stay-saved',this.externalSave);this.root.removeEventListener('click',this.handleClick);this.root.removeEventListener('input',this.handleInput);this.root.removeEventListener('change',this.handleChange);this.root.removeEventListener('keydown',this.handleKey);}
 normalizeAreas(){for(const b of this.blocks)if(b.selection?.kind==='area'){b.area=b.selection;b.selection=null;}}
 emitInput(){if(!this.options.input)return;const values=expandBlocks(this.blocks,this.total)||[];this.lastEmitted=JSON.stringify(values);this.options.onModel?.(values);}
 changed(){this.saveDraft();this.emitInput();this.render();}
 rangeText(b){
  const count=b.night_end-b.night_start+1;const start=this.proposal?.start_date;
  if(start&&/^\d{4}-\d{2}-\d{2}$/.test(start)){const day=n=>{const d=new Date(start+'T12:00:00Z');d.setUTCDate(d.getUTCDate()+n-1);return `${d.getUTCMonth()+1}月${d.getUTCDate()}日`};return `${day(b.night_start)}入住 · ${day(b.night_end+1)}退房 · ${count}晚`;}
  return `第${b.night_start}${b.night_end!==b.night_start?'–'+b.night_end:''}晚 · 连住${count}晚`;
 }
 render(){
  if(!this.alive||this.dragging)return;if(this.options.modal&&!this.props.open){this.root.innerHTML='';return}
  if(!this.options.modal&&!this.options.input&&Number(this.props.nights)===0){this.root.innerHTML='';return;}
  const active=document.activeElement;const owned=this.root.contains(active);const selector=owned?(active.matches('[role=dialog]')?'[role=dialog]':active.matches('[data-search]')?'[data-search]':active.matches('[data-boundary]')?'[data-boundary="'+active.dataset.boundary+'"]':active.matches('.ez-step-label')?'.ez-step-label':active.dataset.action?'[data-action="'+active.dataset.action+'"]'+(active.dataset.index?'[data-index="'+active.dataset.index+'"]':''):null):null;
  const caret=selector==='[data-search]'?[active.selectionStart,active.selectionEnd]:null;
  const body=this.content();
  if(this.options.modal){this.root.innerHTML=`<div class="ez-stay-backdrop" data-action="backdrop"><section class="ez-stay-dialog" role="dialog" aria-modal="true" aria-label="住在哪里" tabindex="-1"><header class="ez-dialog-head"><h2>住在哪里</h2><button type="button" class="ez-icon" data-action="close" aria-label="关闭住宿选择">×</button></header>${body}</section></div>`;if(!this.focused){this.root.querySelector('[role=dialog]')?.focus({preventScroll:true});this.focused=true;}}
  else this.root.innerHTML=`<section class="ez-stay-planner" aria-label="分段住宿安排">${body}</section>`;
  if(selector){const next=this.root.querySelector(selector);next?.focus({preventScroll:true});if(next&&caret)try{next.setSelectionRange(...caret)}catch{}}
 }
 content(){
  if(this.busy&&!this.proposal&&!this.options.input)return '<p role="status" class="ez-note">正在整理各城住宿安排…</p>';
  if(this.error&&!this.proposal&&!this.options.input)return `<p class="ez-error" role="alert">${esc(this.error)}</p><button type="button" class="ez-secondary" data-action="reload">重新载入建议</button>`;
  if(!this.total&&this.options.input)return '';
  if(!this.total&&this.proposal)return '<p class="ez-note">当天往返，无需安排住宿。</p>';
  const title=this.options.input?'一次选好连续住宿':'每座城市住一处，少搬行李';
  let html=`<div class="ez-stay-title"><div><h3>${title}</h3><p class="ez-note">${this.options.input?'选择具体酒店后会覆盖整段入住时间，也可添加下一段。':`共 ${this.total} 晚 · 先选片区，再选具体酒店；入住范围可拖动调整。`}</p></div>${this.complete?'<span class="ez-complete">已覆盖全部住宿</span>':''}</div>`;
  if(this.proposal?.review_in_progress)html+='<p class="ez-note" role="status">正在按当前安排复核衔接，住宿选择可以继续。</p>';
  const review=this.proposal?.review;const gate=review?.quality_gate;
  if(gate&&gate.state!=='passed'||this.total>=7&&(review?.issues||[]).some(i=>i.severity==='high')){
   const issues=(review?.issues||[]).filter(i=>i.severity==='high');
   html+=`<details class="ez-review-note"><summary>${esc(gate?.summary||'行程仍有衔接待调整，先安排住宿再复核')}</summary><ul>${issues.slice(0,8).map(i=>`<li>${esc(i.message)}</li>`).join('')}</ul></details>`;
  }
  if(this.error)html+=`<p class="ez-error" role="alert">${esc(this.error)} ${!this.options.input?'<button type="button" class="ez-text" data-action="reload">重新载入建议</button>':''}</p>`;
  if(!this.accepted){
   const groups=this.proposal?.blocks||[];
   html+=`<ol class="ez-proposal">${groups.map(b=>`<li><b>${esc(b.city)}</b><span>${esc(this.rangeText(b))}</span></li>`).join('')}</ol><p class="ez-note">先按顺序选片区，再选这一片区的具体酒店。选择用于行程规划，不代表已预订或确认有房。</p><div class="ez-button-row"><button type="button" class="ez-primary" data-action="accept" ${!this.writable||this.busy?'disabled':''}>接受分城连住建议，开始选择</button><button type="button" class="ez-secondary" data-action="custom" ${!this.writable?'disabled':''}>自己安排住宿</button></div>`;
   if(!this.writable)html+='<p class="ez-note">共享行程可查看建议；取得编辑权限后才能保存住宿。</p>';
   return html;
  }
  html+=`<p class="ez-note">${this.party.travelers}人同行 · 按${this.party.rooms}间房查询酒店。人数与房间数可在费用明细中调整。</p>`;
  html+=this.timeline();
  const current=this.blocks[this.active];if(!current)return html;
  html+=`<div class="ez-step-label" role="heading" aria-level="4" tabindex="-1"><span>第 ${this.active+1} / ${this.blocks.length} 段 · ${esc(current.city||'住宿')}</span><b>${esc(this.rangeText(current))}</b></div>`;
  if(this.complete)html+='<p class="ez-note">所有晚数都已安排。点时间条上的城市可返回修改，确认后统一更新行程。</p>';
  const choices=current.areas||[];
  if(choices.length)html+=`<div class="ez-area-choices" role="group" aria-label="${esc(current.city)}推荐住宿区域">${choices.map((a,i)=>`<button type="button" class="ez-area ${current.area?.name===a.name?'selected':''}" data-action="choose" data-index="${i}" aria-pressed="${current.area?.name===a.name}" ${!this.writable||this.busy?'disabled':''}><span class="ez-area-top"><b>${esc(a.name)}</b><span>${a.source==='itinerary_center'?'行程中心参考':'推荐片区'}</span></span><span>${esc(a.why)}</span>${a.transit?`<small>${esc(a.transit)}</small>`:''}</button>`).join('')}</div>`;
  if(current.area)html+=`<p class="ez-note">已选片区：${esc(current.area.name)}${current.selection?'':' · 接下来选择具体酒店'}</p>`;
  if(current.selection)html+=`<p class="ez-picked">已选：${esc(current.selection.name)} · ${current.selection.kind==='hotel'?'酒店 / 住处':'住宿区域'}</p>`;
  html+=`<div class="ez-button-row">${!this.options.input&&current.id?.startsWith('stay-')?`<button type="button" class="ez-secondary" data-action="recommend" ${!this.writable||this.busy||this.recommendBusy?'disabled':''}>${this.recommendBusy?'正在查询片区…':'查看更多片区建议'}</button>`:''}<button type="button" class="ez-secondary" data-action="search-toggle" ${!this.writable?'disabled':''}>自行搜索酒店</button></div>`;
  if(this.hotelLoading)html+='<p class="ez-note" role="status">正在查询片区内的酒店…</p>';
  if(this.hotels?.length)html+=`<div class="ez-hotel-choices" role="group" aria-label="具体酒店">${this.hotels.map((p,i)=>`<article class="ez-hotel-card"><button type="button" class="ez-area" data-action="hotel-pick" data-index="${i}" ${!this.writable||this.busy?'disabled':''}><b>${esc(p.name)}</b><span>${esc(p.address||'')}</span><small>${p.rating?'★ '+esc(p.rating)+' · ':''}${p.avg_km!=null?'距片区中心 '+esc(p.avg_km)+' km':''}</small><span>选择这家酒店</span></button><button type="button" class="ez-secondary" data-action="hotel-quote" data-index="${i}" ${p.quoteLoading||!this.dates(current).check_in?'disabled':''}>${p.quoteLoading?'正在查询多人房价…':`查询${this.party.travelers}人${this.party.rooms}间房价格`}</button>${p.quote?`<div class="ez-hotel-quote">${p.quote.ok?`<p>渠道均价 €${esc(p.quote.per_night_mean)} / 间 / 晚</p><p>本段整团 €${esc(p.quote.total_mean)} · 人均 €${esc((p.quote.total_mean/this.party.travelers).toFixed(2))}</p><p>${esc(p.quote.note)}</p>`:`<p>${esc(p.quote.note||'暂未取得对应日期与人数的报价，费用将标为估算。')}</p>`}</div>`:''}<a href="${esc(this.bookingUrl(p,current))}" target="_blank" rel="noopener noreferrer">按同行人数与入住日期查价</a></article>`).join('')}</div><p class="ez-note">地点来自 Google Places，房价来自渠道查询；房型、税费与最终库存以预订页面为准。</p>`;
  if(this.hotelEmpty)html+='<p class="ez-note">未找到合适酒店，可自行搜索具体酒店名称，或改选片区。</p>';
  if(this.showSearch)html+=`<div class="ez-search"><label>搜索这一段的具体酒店<input type="search" data-search maxlength="80" aria-label="搜索住宿地点" value="${esc(this.query||'')}" placeholder="${esc(current.city||'城市')} · 酒店名或地址" autocomplete="off"></label><div class="ez-search-results" role="listbox" aria-label="住宿搜索结果">${this.searchMarkup()}</div></div>`;
  html+=`<div class="ez-button-row ez-tools"><button type="button" class="ez-text" data-action="split" ${!this.writable||current.night_end===current.night_start?'disabled':''}>拆成两段入住</button>${this.blocks.length>1?`<button type="button" class="ez-text" data-action="merge" title="${this.active?'沿用上一段住宿，合并入住时间':'沿用本段住宿，合并下一段入住时间'}" ${!this.writable?'disabled':''}>${this.active?'与上一段连住':'与下一段连住'}</button>`:''}</div>`;
  html+=`<footer class="ez-stay-actions"><button type="button" class="ez-secondary" data-action="prev" ${this.active===0?'disabled':''}>上一段</button>${this.active<this.blocks.length-1?'<button type="button" class="ez-secondary" data-action="next">下一段</button>':''}${!this.options.input?`<button type="button" class="ez-primary" data-action="save" ${!this.writable||!this.complete||this.busy?'disabled':''}>${this.busy?'正在保存…':`确认 ${this.total} 晚住宿，更新行程`}</button>`:''}</footer>`;
  return html;
 }
 timeline(){
  const palette=['#6254dc','#0f8d78','#317cc8','#c0732e','#a349a4'];
  const selected=this.blocks.filter(b=>b.selection?.kind==='hotel').reduce((s,b)=>s+b.night_end-b.night_start+1,0);
  return `<div class="ez-night-timeline" aria-label="住宿入住时间条"><p class="ez-note">${selected} / ${this.total} 晚已选择 · 拖动分界调整日期，点击城市返回选择</p><div class="ez-track">${this.blocks.map((b,i)=>`<button type="button" class="ez-segment ${i===this.active?'active':''}" data-action="active" data-index="${i}" style="flex:${b.night_end-b.night_start+1};--segment-color:${palette[i%palette.length]}" aria-label="选择${esc(b.city)}住宿分段，第${b.night_start}至${b.night_end}晚"><b>${esc(b.city||'住宿')}</b><span>${b.night_end-b.night_start+1}晚${b.selection?.kind==='hotel'?' ✓':''}</span></button>`).join('')}${this.blocks.slice(0,-1).map((b,i)=>`<input class="ez-boundary" type="range" min="1" max="${Math.max(1,this.total-1)}" step="1" value="${b.night_end}" data-boundary="${i}" style="left:calc(${100/this.total}% - 12px);width:calc(${100*(this.total-2)/this.total}% + 24px)" aria-label="调整${esc(b.city)}与${esc(this.blocks[i+1].city)}的入住分界" aria-valuetext="第${b.night_end}晚后换住宿" ${!this.writable||this.busy?'disabled':''}>`).join('')}</div><div class="ez-track-ends"><span>第1晚</span><span>第${this.total}晚后退房</span></div></div>`;
 }
 searchMarkup(){if(this.searching)return '<p role="status">正在搜索住宿地点…</p>';return this.searchResults.map((p,i)=>`<button type="button" role="option" aria-selected="false" data-action="search-pick" data-index="${i}"><b>${esc(p.name)}</b><small>${esc(p.address||'')}</small></button>`).join('')|| (this.query?.length>=2?'<p>未找到地点，可换一个酒店名或加上城市。</p>':'');}
 async click(event){
  const button=event.target.closest('[data-action]');if(!button||!this.root.contains(button)||button.disabled)return;const action=button.dataset.action;
  if(action==='backdrop'){if(event.target===button)this.close();return}
  if(action==='close'){this.close();return}
  if(action==='reload'){await this.load();return}
  if(this.busy)return;
  if(action==='active'){this.active=Number(button.dataset.index);this.resetHotels();this.render();this.resumeHotels();return}
  if(action==='prev'||action==='next'){this.active=Math.max(0,Math.min(this.blocks.length-1,this.active+(action==='next'?1:-1)));this.resetHotels();this.render();this.resumeHotels();return}
  if(!this.writable)return;
  if(action==='accept'||action==='custom'){this.accepted=true;this.blocks=clone(this.proposal.blocks);this.active=0;this.showSearch=action==='custom';this.changed();this.focusStep();this.focusSearch();this.ensureSuggestions();return}
  if(action==='choose'){this.selectArea(this.blocks[this.active].areas[Number(button.dataset.index)]);return}
  if(action==='hotel-quote'){await this.quoteHotel(Number(button.dataset.index));return}
  if(action==='hotel-pick'){const p=this.hotels?.[Number(button.dataset.index)];if(p)this.pickHotel(p);return}
  if(action==='search-toggle'){this.showSearch=!this.showSearch;this.query='';this.searchResults=[];this.render();this.focusSearch();return}
  if(action==='search-pick'){const p=this.searchResults[Number(button.dataset.index)];if(p)this.pickHotel(p);return}
  if(action==='recommend'){await this.recommend();return}
  if(action==='save'){await this.save();return}
  const b=this.blocks[this.active];
  if(action==='split'&&b.night_end>b.night_start){const boundary=Math.floor((b.night_start+b.night_end)/2);const second={...clone(b),id:`custom-${Date.now()}`,night_start:boundary+1,selection:null,area:null};b.night_end=boundary;this.blocks.splice(this.active+1,0,second);this.active++;this.resetHotels();this.showSearch=true;this.query='';this.searchResults=[];this.changed();this.focusSearch();return}
  if(action==='merge'&&this.blocks.length>1){const i=this.active||1;const previous=this.blocks[i-1],current=this.blocks[i];previous.night_end=current.night_end;this.blocks.splice(i,1);this.active=i-1;this.resetHotels();this.changed();this.resumeHotels();}
 }
 resetHotels(){this.hotelToken=(this.hotelToken||0)+1;this.hotels=[];this.hotelLoading=false;this.hotelEmpty=false;this.showSearch=false;this.query='';this.searchResults=[];this.searching=false;clearTimeout(this.searchTimer);}
 resumeHotels(){const b=this.blocks[this.active];if(b?.area&&!b.selection)void this.loadHotels(b.area);else this.ensureSuggestions();}
 selectArea(area){if(!area||!pointValid(area))return;this.resetHotels();const b=this.blocks[this.active];b.area=clone(area);b.selection=null;this.error='';this.changed();void this.loadHotels(area);}
 bookingUrl(hotel,b){const dates=this.dates(b);const params=new URLSearchParams({ss:hotel.name+' '+(b.city||this.props.city||''),group_adults:this.party.travelers,no_rooms:this.party.rooms,group_children:0});if(dates.check_in){params.set('checkin',dates.check_in);params.set('checkout',dates.check_out)}return 'https://www.booking.com/searchresults.html?'+params;}
 async quoteHotel(index){const hotel=this.hotels?.[index],b=this.blocks[this.active],token=this.hotelToken;if(!hotel||hotel.quoteLoading||!this.dates(b).check_in)return;hotel.quoteLoading=true;this.render();
  try{const q=await this.call('/api/travel-plan/hotels/quote?'+new URLSearchParams({hotel_name:hotel.name,city:b.city||this.props.city||'',...this.dates(b),...this.party}));if(this.alive&&token===this.hotelToken)hotel.quote=q;}
  catch(e){if(this.alive&&token===this.hotelToken)hotel.quote={ok:false,note:message(e)}}finally{hotel.quoteLoading=false;if(this.alive&&token===this.hotelToken)this.render();}
 }
 pickHotel(p){this.choose({name:p.name,lat:Number(p.latitude??p.lat),lng:Number(p.longitude??p.lng),kind:'hotel',place_id:p.place_id||'',address:p.address||''});}
 async loadHotels(area){const b=this.blocks[this.active],token=++this.hotelToken;this.hotelLoading=true;this.hotelEmpty=false;this.render();
  try{const data=await this.call('/api/travel-plan/hotels/search?'+new URLSearchParams({travelers:this.party.travelers,rooms:this.party.rooms,city:b.city||this.props.city||'',q:(area.query||area.name).slice(0,80),lat:area.lat,lng:area.lng}));if(this.alive&&token===this.hotelToken){this.hotels=(data.items||[]).filter(p=>pointValid({lat:p.latitude,lng:p.longitude}));this.hotelEmpty=!this.hotels.length;}}
  catch(e){if(this.alive&&token===this.hotelToken){this.error=message(e);this.showSearch=true;}}
  finally{if(this.alive&&token===this.hotelToken){this.hotelLoading=false;this.render();}}
 }
 choose(choice){if(!choice?.name||choice.kind!=='hotel'||!pointValid(choice))return;this.blocks[this.active].selection={...choice,name:choice.name.slice(0,120)};this.resetHotels();this.error='';const next=this.blocks.findIndex(b=>b.selection?.kind!=='hotel');if(next>=0)this.active=next;this.changed();this.focusStep();this.resumeHotels();}
 focusStep(){const step=this.root.querySelector('.ez-step-label');step?.focus({preventScroll:true});step?.scrollIntoView({block:'nearest',behavior:'auto'})}
 ensureSuggestions(){const b=this.blocks[this.active];if(!this.id||!this.accepted||!this.writable||this.recommendBusy||b?.selection||!b?.id?.startsWith('stay-')||b._requested||b.areas?.some(a=>a.source!=='itinerary_center'))return;b._requested=true;void this.recommend();}
 focusSearch(){if(this.showSearch)requestAnimationFrame(()=>this.root.querySelector('[data-search]')?.focus({preventScroll:true}));}
 input(event){
  const el=event.target;
  if(el.matches('[data-boundary]')){this.dragging=true;const index=Number(el.dataset.boundary);shiftBoundary(this.blocks,index,el.value);el.value=this.blocks[index].night_end;el.setAttribute('aria-valuetext',`第${el.value}晚后换住宿`);this.root.querySelectorAll('.ez-segment').forEach((segment,i)=>{const b=this.blocks[i];segment.style.flex=b.night_end-b.night_start+1;segment.querySelector('span').textContent=`${b.night_end-b.night_start+1}晚${b.selection?.kind==='hotel'?' ✓':''}`});this.saveDraft();return}
  if(el.matches('[data-search]')){this.query=el.value;clearTimeout(this.searchTimer);this.searchTimer=setTimeout(()=>void this.search(),350);}
 }
 change(event){if(event.target.matches('[data-boundary]')){this.dragging=false;const index=event.target.dataset.boundary;this.emitInput();this.render();this.root.querySelector(`[data-boundary="${index}"]`)?.focus({preventScroll:true});}}
 async search(){const q=(this.query||'').trim();if(q.length<2){this.searchResults=[];this.refreshSearch();return}const active=this.active;const b=this.blocks[active];const token=this.hotelToken;this.searching=true;this.refreshSearch();
  try{const data=await this.call('/api/travel-plan/hotels/search?'+new URLSearchParams({q,travelers:this.party.travelers,rooms:this.party.rooms,city:b.city||this.props.city||'',...(b.area?{lat:b.area.lat,lng:b.area.lng}:{})}));if(this.alive&&q===this.query?.trim()&&active===this.active&&token===this.hotelToken){this.searchResults=(data.items||[]).filter(p=>pointValid({lat:Number(p.latitude??p.lat),lng:Number(p.longitude??p.lng)}));}}
  catch(e){if(this.alive&&token===this.hotelToken){this.error=message(e);this.render();}}finally{if(this.alive&&token===this.hotelToken){this.searching=false;this.refreshSearch();}}
 }
 refreshSearch(){const box=this.root.querySelector('.ez-search-results');if(box)box.innerHTML=this.searchMarkup();}
 scheduleReviewPoll(){clearTimeout(this.reviewTimer);if(!this.alive||!this.id||this.options.input||this.options.modal&&!this.props.open||this.reviewPolls>=48)return;if(this.proposal?.review_in_progress||this.proposal?.review_stale&&this.props.canEdit)this.reviewTimer=setTimeout(()=>void this.refreshReview(),8000);}
 async refreshReview(){this.reviewPolls++;try{const data=await this.call(`/api/travel-plan/${encodeURIComponent(this.id)}/stay-plan`);if(!this.alive)return;if(data.rev!==this.proposal.rev){this.error='行程已在别处修改，请重新载入后再保存。';this.render();return}this.proposal.review=data.review;this.proposal.planning_status=data.planning_status;this.proposal.review_in_progress=data.review_in_progress;this.proposal.review_stale=data.review_stale;this.render();}catch{}finally{if(this.alive)this.scheduleReviewPoll();}}
 async recommend(){if(this.recommendBusy)return;const b=this.blocks[this.active];this.recommendBusy=true;this.error='';this.render();try{const data=await this.call(`/api/travel-plan/${encodeURIComponent(this.id)}/stay-plan/${encodeURIComponent(b.id)}/recommend`,{});if(!this.alive)return;b.areas=data.areas?.length?data.areas:b.areas;if(!data.areas?.length)this.error='暂未找到更多片区，可使用当前建议或自行搜索。';this.saveDraft();}catch(e){if(this.alive)this.error=message(e)}finally{if(this.alive){this.recommendBusy=false;this.render();this.ensureSuggestions();}}}
 async save(){if(!this.complete)return;this.busy=true;this.error='';this.render();try{const body={rev:this.proposal.rev,reorder:false,stays:expandBlocks(this.blocks,this.total),blocks:this.blocks.map(b=>({night_start:b.night_start,night_end:b.night_end,city:b.city,...b.selection}))};const data=await this.call(`/api/travel-plan/${encodeURIComponent(this.id)}/stay-set`,body);if(!this.alive)return;try{localStorage.removeItem(this.draftKey)}catch{}this.accepted=true;this.proposal.rev=data.rev;this.options.onSaved?.(data);window.dispatchEvent(new CustomEvent('eztrip:stay-saved',{detail:{id:this.id,source:this.uid,data}}));if(this.options.modal)this.close();else await this.load();}catch(e){if(this.alive)this.error=message(e)}finally{if(this.alive){this.busy=false;this.render();}}}
}
