import {analyze,forwardReturn,simulate} from './engine.js';
const $=s=>document.querySelector(s),$$=s=>[...document.querySelectorAll(s)];
const fmt=(n,d=3)=>n==null?'—':Number(n).toFixed(d),pct=(n,d=2)=>n==null?'—':`${n>=0?'+':''}${(n*100).toFixed(d)}%`;
const cls=n=>n==null?'':n>=0?'positive':'negative';
let data,analysis,rows,signals,shown=[],selected=-1,locked=false,filter='all',page=0,range={start:'',end:''},simulation;
const pageSize=8;let currentView='overview';
function notify(message){$('#toast').textContent=message;$('#toast').hidden=false;setTimeout(()=>$('#toast').hidden=true,2600);}
async function init(){
 try{
  const response=await fetch('./data.json');if(!response.ok)throw new Error('数据快照载入失败');data=await response.json();analysis=analyze(data.rows);({rows,signals}=analysis);
  $('#latest-date').textContent=data.meta.latestUsableDate;
  $('#notice').innerHTML=`数据提示：收到的 ${data.meta.latestReceivedDate} K 线精度异常，已隔离；可用行情截至 ${data.meta.latestUsableDate}。<a href="#data">查看原因</a> · 固定快照，不是实时行情。`;
  for(const el of [$('#start'),$('#end')]){el.min=rows[20].date;el.max=rows.at(-1).date;}
  renderAudit();bind();setPreset('3');changeView();
 }catch(e){$('#notice').textContent='无法可靠判定：'+e.message+'。本页不会展示模拟行情。';$('#notice').style.color='#b45d45';$$('button,input,select').forEach(e=>e.disabled=true);}
}
function bind(){
 window.addEventListener('hashchange',changeView);
 $$('#ranges button').forEach(b=>b.addEventListener('click',()=>setPreset(b.dataset.months)));
 $('#apply').addEventListener('click',()=>applyRange());
 [$('#start'),$('#end')].forEach(e=>e.addEventListener('keydown',event=>{if(event.key==='Enter')applyRange();}));
 [$('#show-ma'),$('#show-a'),$('#show-b')].forEach(e=>e.addEventListener('change',drawPrice));
 $$('#signal-filter button').forEach(b=>b.addEventListener('click',()=>{filter=b.dataset.strategy;page=0;$$('#signal-filter button').forEach(x=>x.classList.toggle('selected',x===b));renderSignals();}));
 $('#prev-page').addEventListener('click',()=>{page--;renderSignals();});$('#next-page').addEventListener('click',()=>{page++;renderSignals();});
 $('#export').addEventListener('click',exportCSV);$('#run-sim').addEventListener('click',runSimulation);
 $('#reset-chart').addEventListener('click',()=>{selected=-1;locked=false;$('#chart-tooltip').hidden=true;$('#chart-day').textContent='使用鼠标或左右方向键查看单日行情';drawPrice();});
 const canvas=$('#price-chart');
 canvas.addEventListener('mousemove',e=>{if(locked)return;selectAt(e);});
 canvas.addEventListener('mouseleave',()=>{if(locked)return;selected=-1;$('#chart-tooltip').hidden=true;drawPrice();});
 canvas.addEventListener('click',e=>{selectAt(e);locked=!locked;});
 canvas.addEventListener('keydown',e=>{if(!['ArrowLeft','ArrowRight','Escape'].includes(e.key))return;e.preventDefault();if(e.key==='Escape'){$('#reset-chart').click();return;}selected=selected<0?shown.length-1:Math.max(0,Math.min(shown.length-1,selected+(e.key==='ArrowLeft'?-1:1)));locked=true;showTooltip();drawPrice();});
 new ResizeObserver(()=>{drawPrice();if(currentView==='backtest')drawEquity();}).observe($('#chart-wrap'));
 window.addEventListener('resize',()=>{if(currentView==='backtest')drawEquity();});
}
function changeView(){
 let id=location.hash.slice(1)||'overview';if(!['overview','backtest','rules','data'].includes(id))id='overview';currentView=id;
 $$('.view').forEach(v=>v.hidden=v.id!==id);$$('.nav-item').forEach(a=>a.classList.toggle('active',a.dataset.view===id));
 $('#page-label').textContent={overview:'信号工作台',backtest:'资金回测',rules:'规则说明',data:'数据审计'}[id];
 $('.filterbar').hidden=!['overview','backtest'].includes(id);$('#export').hidden=id==='data'||id==='rules';
 requestAnimationFrame(()=>{if(id==='overview')drawPrice();if(id==='backtest')runSimulation();});
}
function setPreset(p){
 const end=rows.at(-1).date;let start;
 if(p==='all')start=rows[20].date;else if(p==='ytd')start=end.slice(0,4)+'-01-01';else{const d=new Date(end+'T12:00:00Z');d.setUTCMonth(d.getUTCMonth()-Number(p));start=d.toISOString().slice(0,10);}
 start=start<rows[20].date?rows[20].date:start;$('#start').value=start;$('#end').value=end;applyRange(p);
}
function applyRange(p){
 const start=$('#start').value,end=$('#end').value;
 if(!start||!end||start>end||start<rows[20].date||end>rows.at(-1).date){$('#range-error').textContent=`请选择 ${rows[20].date} 至 ${rows.at(-1).date} 内的有效区间，起始日不得晚于截止日。`;return;}
 if(!rows.some(r=>r.date>=start&&r.date<=end)){$('#range-error').textContent='该区间没有有效交易日，请调整日期。';return;}
 $('#range-error').textContent='';range={start,end};shown=rows.filter(r=>r.date>=start&&r.date<=end);page=0;selected=-1;locked=false;$('#chart-tooltip').hidden=true;
 $$('#ranges button').forEach(b=>b.classList.toggle('selected',b.dataset.months===p));
 renderMetrics();renderStates();renderSignals();drawPrice();if(currentView==='backtest')runSimulation();
}
function rangeSignals(){return signals.filter(s=>s.date>=range.start&&s.date<=range.end&&(filter==='all'||s.strategy===filter));}
function observedReturn(index){return index+20<=shown.at(-1).index?forwardReturn(rows,index,20):null;}
function renderMetrics(){
 const last=shown.at(-1),prev=rows[last.index-1],dayReturn=last.closeN/prev.closeN-1,gap=last.ma==null?null:last.closeN/last.ma-1;
 const stats=s=>{const ss=signals.filter(v=>v.date>=range.start&&v.date<=range.end&&v.strategy===s);const rr=ss.map(v=>observedReturn(v.index)).filter(v=>v!==null);return {count:ss.length,n:rr.length,rate:rr.length?rr.filter(v=>v>0).length/rr.length:null};};
 const a=stats('A'),b=stats('B');
 $('#metrics').innerHTML=`<div class="metric"><div class="metric-label">区间末日收盘 <span class="metric-corner">↗</span></div><div class="metric-value">${fmt(last.closeN)}<small>元</small></div><div class="metric-sub">${last.date} <em class="${cls(dayReturn)}">${pct(dayReturn)} / 前一交易日</em></div></div>
 <div class="metric"><div class="metric-label">MA20 <span class="metric-corner">⌁</span></div><div class="metric-value">${fmt(last.ma,5)}</div><div class="metric-sub">收盘较均线 <em class="${cls(gap)}">${pct(gap)}</em> · 同一前复权口径</div></div>
 <div class="metric accent-a"><div class="metric-label">策略 A · 区间触发 <span class="signal-key a">A</span></div><div class="metric-value">${a.count.toString().padStart(2,'0')}<small>次</small></div><div class="metric-sub">后20日正收益率 ${a.rate==null?'—':(a.rate*100).toFixed(0)+'%'} · 完结样本 ${a.n}</div></div>
 <div class="metric accent-b"><div class="metric-label">策略 B · 区间触发 <span class="signal-key b">B</span></div><div class="metric-value">${b.count.toString().padStart(2,'0')}<small>次</small></div><div class="metric-sub">后20日正收益率 ${b.rate==null?'—':(b.rate*100).toFixed(0)+'%'} · 完结样本 ${b.n}</div></div>`;
 $('#chart-range').textContent=`${shown[0].date} — ${last.date} · ${shown.length} 个交易日`;
}
function renderStates(){
 const r=shown.at(-1);$('#state-date').textContent=r.date;
 $('#strategy-state').innerHTML=['A','B'].map(s=>`<div class="strategy-block"><h3><span class="strategy-mark ${s.toLowerCase()}">${s}</span>${s==='A'?'首次回踩':'冲高后回踩'}<span class="status-tag">${r['status'+s]}</span></h3><dl><dt>突破日期</dt><dd>${r.breakout||'—'}</dd>${s==='B'?`<dt>冲高确认</dt><dd>${r.peak||'—'}</dd>`:''}<dt>剩余交易日</dt><dd>${r.remaining==null?'—':r.remaining+' / 10'}</dd>${r.invalid||r.expired?`<dt>失效原因</dt><dd>${r.invalid||'窗口到期'}</dd>`:''}</dl></div>`).join('');
}
function renderSignals(){
 const items=rangeSignals().slice().reverse(),pages=Math.max(1,Math.ceil(items.length/pageSize));page=Math.max(0,Math.min(page,pages-1));$('#signal-count').textContent=items.length;
 $('#signal-table').innerHTML=items.slice(page*pageSize,(page+1)*pageSize).map(s=>{const f=observedReturn(s.index);return `<tr><td><button class="date-link" data-index="${s.index}" aria-label="定位${s.date}策略${s.strategy}信号">${s.date}</button></td><td><span class="strategy-mark ${s.strategy.toLowerCase()}">${s.strategy}</span></td><td>${fmt(s.close)}</td><td>${fmt(s.ma,6)}</td><td>${s.breakout}</td><td>${s.strategy==='B'?s.peak:'—'}</td><td>${s.remaining} 天</td><td class="${cls(f)}">${f==null?'<span class="pending">样本未完结</span>':pct(f)}</td></tr>`;}).join('')||'<tr><td colspan="8" class="empty-cell">当前区间没有符合规则的首次买点。可切换时间区间查看历史记录。</td></tr>';
 $('#pagination').textContent=`${page+1} / ${pages}`;$('#prev-page').disabled=page===0;$('#next-page').disabled=page>=pages-1;
 $$('#signal-table .date-link').forEach(b=>b.addEventListener('click',()=>{selected=shown.findIndex(r=>r.index===+b.dataset.index);locked=true;drawPrice();showTooltip();$('.chart-card').scrollIntoView({behavior:'smooth',block:'center'});}));
}
function setupCanvas(canvas){
 const rect=canvas.getBoundingClientRect();if(rect.width<1||rect.height<1)return null;const dpr=window.devicePixelRatio||1;
 canvas.width=Math.round(rect.width*dpr);canvas.height=Math.round(rect.height*dpr);const ctx=canvas.getContext('2d');ctx.scale(dpr,dpr);return {ctx,w:rect.width,h:rect.height};
}
function chartGeometry(w,h){return {left:11,right:w-54,top:20,bottom:h-85,width:w-65};}
function drawPrice(){
 if(!shown.length||currentView!=='overview')return;const setup=setupCanvas($('#price-chart'));if(!setup)return;const {ctx,w,h}=setup,g=chartGeometry(w,h);
 const values=shown.flatMap(r=>[r.lowN,r.highN,...($('#show-ma').checked&&r.ma!=null?[r.ma]:[])]);let lo=Math.min(...values),hi=Math.max(...values);const pad=Math.max((hi-lo)*.16,.005);lo-=pad;hi+=pad;
 const y=v=>g.bottom-(v-lo)/(hi-lo)*(g.bottom-g.top),step=g.width/shown.length,x=i=>g.left+(i+.5)*step;ctx.clearRect(0,0,w,h);
 ctx.font='9px ui-monospace,SFMono-Regular,monospace';ctx.textAlign='left';
 for(let i=0;i<=4;i++){const yy=g.top+(g.bottom-g.top)*i/4;ctx.strokeStyle='#edf0f2';ctx.lineWidth=1;ctx.setLineDash([3,4]);ctx.beginPath();ctx.moveTo(g.left,yy);ctx.lineTo(g.right+3,yy);ctx.stroke();ctx.setLineDash([]);ctx.fillStyle='#a7b1b7';ctx.fillText((hi-(hi-lo)*i/4).toFixed(3),g.right+11,yy+3);}
 if(selected>=0&&selected<shown.length){ctx.fillStyle='#f6f1e8';ctx.fillRect(x(selected)-Math.max(step/2,6),g.top,Math.max(step,12),h-g.top-25);}
 const maxVol=Math.max(...shown.map(r=>Number(r.volume)));
 shown.forEach((r,i)=>{
  const xx=x(i),up=r.closeN>=r.openN,color=up?'#c1806d':'#7a9b8c',body=Math.max(1,Math.min(6,step*.6));
  ctx.strokeStyle=color;ctx.fillStyle=color;ctx.lineWidth=Math.max(.8,Math.min(1.1,step*.2));ctx.beginPath();ctx.moveTo(xx,y(r.highN));ctx.lineTo(xx,y(r.lowN));ctx.stroke();
  ctx.fillRect(xx-body/2,Math.min(y(r.openN),y(r.closeN)),body,Math.max(1,Math.abs(y(r.openN)-y(r.closeN))));
  ctx.globalAlpha=.23;ctx.fillRect(xx-body/2,h-36-Number(r.volume)/maxVol*28,body,Number(r.volume)/maxVol*28);ctx.globalAlpha=1;
 });
 if($('#show-ma').checked){ctx.strokeStyle='#c3a16f';ctx.lineWidth=1.5;ctx.beginPath();let begun=false;shown.forEach((r,i)=>{if(r.ma==null)return;if(!begun){ctx.moveTo(x(i),y(r.ma));begun=true;}else ctx.lineTo(x(i),y(r.ma));});ctx.stroke();}
 const radius=shown.length>350?6:8;
 shown.forEach((r,i)=>{let offset=0;for(const s of r.signals){if(!$('#show-'+s.toLowerCase()).checked)continue;const xx=x(i),yy=y(r.lowN)+16+offset;offset+=20;ctx.fillStyle=s==='A'?'#ce784b':'#648f9a';ctx.beginPath();ctx.moveTo(xx,yy-radius-4);ctx.lineTo(xx-3,yy-radius);ctx.lineTo(xx+3,yy-radius);ctx.closePath();ctx.fill();ctx.beginPath();ctx.roundRect(xx-radius,yy-radius,2*radius,2*radius,3);ctx.fill();ctx.fillStyle='#fff';ctx.font=`${radius===6?8:9}px ui-monospace,monospace`;ctx.textAlign='center';ctx.fillText(s,xx,yy+3);}});
 ctx.font='9px ui-monospace,monospace';ctx.fillStyle='#a7b1b7';ctx.textAlign='center';for(let i=0;i<=4;i++){const k=Math.round((shown.length-1)*i/4);ctx.fillText(shown[k].date.slice(2),x(k),h-11);}
 ctx.textAlign='left';ctx.font='8px sans-serif';ctx.fillStyle='#afb9be';ctx.fillText('VOL',g.left,h-65);
 if(selected>=0&&selected<shown.length){const r=shown[selected],xx=x(selected);ctx.strokeStyle='#9dacae';ctx.lineWidth=.8;ctx.setLineDash([3,3]);ctx.beginPath();ctx.moveTo(xx,g.top);ctx.lineTo(xx,h-29);ctx.moveTo(g.left,y(r.closeN));ctx.lineTo(g.right,y(r.closeN));ctx.stroke();ctx.setLineDash([]);ctx.fillStyle='#607c79';ctx.beginPath();ctx.arc(xx,y(r.closeN),3,0,Math.PI*2);ctx.fill();}
}
function selectAt(event){const rect=$('#price-chart').getBoundingClientRect(),g=chartGeometry(rect.width,rect.height);selected=Math.max(0,Math.min(shown.length-1,Math.floor((event.clientX-rect.left-g.left)/g.width*shown.length)));showTooltip();drawPrice();}
function showTooltip(){
 if(selected<0||!shown[selected])return;const r=shown[selected],tooltip=$('#chart-tooltip'),rect=$('#price-chart').getBoundingClientRect(),g=chartGeometry(rect.width,rect.height),xx=g.left+(selected+.5)*g.width/shown.length;
 tooltip.innerHTML=`<b>${r.date}${r.signals.length?'　'+r.signals.join(' / ')+' 信号':''}</b><div class="tooltip-grid"><span>开 ${fmt(r.openN)}</span><span>收 ${fmt(r.closeN)}</span><span>高 ${fmt(r.highN)}</span><span>低 ${fmt(r.lowN)}</span></div><div>MA20　${fmt(r.ma,6)}</div><div>偏离　${pct(r.closeN/r.ma-1,3)}</div>`;
 tooltip.style.left=Math.max(6,Math.min(rect.width-182,xx>rect.width*.56?xx-184:xx+15))+'px';tooltip.style.top='17px';tooltip.hidden=false;
 $('#chart-day').textContent=`${r.date} · O ${fmt(r.openN)} / H ${fmt(r.highN)} / L ${fmt(r.lowN)} / C ${fmt(r.closeN)}`;
}
function exportCSV(){
 const lines=[['触发日期','策略','突破日期','B冲高日期','前复权收盘','MA20','剩余交易日','后20日收益(下一日开盘至第20日收盘)','数据来源','最新可用K线','复权口径'],...rangeSignals().map(s=>[s.date,s.strategy,s.breakout,s.strategy==='B'?s.peak:'',s.close.toFixed(6),s.ma.toFixed(6),s.remaining,observedReturn(s.index)??'',data.meta.provider,data.meta.latestUsableDate,'前复权qfqday'])];
 const content='\ufeff'+lines.map(l=>l.map(v=>'"'+String(v??'').replaceAll('"','""')+'"').join(',')).join('\r\n');const url=URL.createObjectURL(new Blob([content],{type:'text/csv;charset=utf-8'})),a=document.createElement('a');a.href=url;a.download=`512890-signals-${range.start}-${range.end}-${filter}.csv`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);notify(`已导出 ${lines.length-1} 条信号记录`);
}
function runSimulation(){
 const capital=Number($('#capital').value),feeBps=Number($('#fee').value),slippageBps=Number($('#slippage').value),strategy=$('#sim-strategy').value;
 if(!Number.isFinite(capital)||capital<1000||capital>1e8||!Number.isFinite(feeBps)||feeBps<0||feeBps>100||!Number.isFinite(slippageBps)||slippageBps<0||slippageBps>100){$('#sim-error').textContent='请填写有效参数：资金 1,000–100,000,000 元，费率和滑点 0–100（万分之）。';return;}
 $('#sim-error').textContent='';simulation=simulate(rows,signals,{...range,strategy,capital,feeBps,slippageBps});simulation.capital=capital;simulation.fee=feeBps/10000;simulation.slip=slippageBps/10000;
 const {trades,positions,totalReturn,maxDrawdown}=simulation;
 $('#sim-metrics').innerHTML=`<div class="metric"><div class="metric-label">区间总收益（含浮盈亏）</div><div class="metric-value ${cls(totalReturn)}">${pct(totalReturn)}</div><div class="metric-sub">期末估值 ${Math.round(simulation.curve.at(-1)?.equity??capital).toLocaleString()} 元</div></div><div class="metric"><div class="metric-label">最大回撤</div><div class="metric-value">${(maxDrawdown*100).toFixed(2)}<small>%</small></div><div class="metric-sub">每日收盘账户估值</div></div><div class="metric"><div class="metric-label">已平仓交易</div><div class="metric-value">${trades.length}<small>笔</small></div><div class="metric-sub">每笔收盘涨幅达 5% 后次日卖出</div></div><div class="metric"><div class="metric-label">期末持仓</div><div class="metric-value">${positions.length}<small>/ 2 笔</small></div><div class="metric-sub">${simulation.pending?'末日信号待执行 '+simulation.pending+' 笔':'现金 '+Math.round(simulation.cash).toLocaleString()+' 元'}</div></div>`;
 const last=shown.at(-1).closeN;
 const details=[...trades.map(p=>({...p,closed:true})),...positions.map(p=>({...p,closed:false,netReturn:(p.quantity*last-p.cost)/p.cost}))].sort((a,b)=>b.entryDate.localeCompare(a.entryDate));
 $('#trades-table').innerHTML=details.map(p=>`<tr><td><span class="strategy-mark ${p.strategy.toLowerCase()}">${p.strategy}</span> ${p.signalDate}</td><td>${p.entryDate}</td><td>${fmt(p.entry,6)}</td><td>${p.closed?p.exitDate:'—'}</td><td>${p.closed?fmt(p.exit,6):'—'}</td><td class="${cls(p.netReturn)}">${pct(p.netReturn)}</td><td>${p.closed?'已平仓':p.sellNext?'待次日卖出':'持有中'}</td></tr>`).join('')||'<tr><td colspan="7" class="empty-cell">该区间没有可执行的入场信号，模拟账户保持现金。</td></tr>';
 requestAnimationFrame(drawEquity);
}
function drawEquity(){
 if(!simulation||currentView!=='backtest')return;const setup=setupCanvas($('#equity-chart'));if(!setup)return;const {ctx,w,h}=setup;const curve=simulation.curve;if(!curve.length)return;
 const first=shown[0],nav=curve.map(r=>r.equity/simulation.capital),benchmark=curve.map(r=>r.close/first.openN/(1+simulation.slip)/(1+simulation.fee));
 const lo=Math.min(1,...nav,...benchmark)-.015,hi=Math.max(1,...nav,...benchmark)+.015,left=20,right=w-57,top=20,bottom=h-36,x=i=>left+(right-left)*i/Math.max(1,curve.length-1),y=v=>bottom-(v-lo)/(hi-lo)*(bottom-top);
 ctx.clearRect(0,0,w,h);ctx.font='10px ui-monospace,monospace';ctx.fillStyle='#9fadb3';ctx.textAlign='left';
 for(let i=0;i<=4;i++){const v=lo+(hi-lo)*i/4,yy=y(v);ctx.strokeStyle='#eef1f2';ctx.beginPath();ctx.moveTo(left,yy);ctx.lineTo(right,yy);ctx.stroke();ctx.fillText(v.toFixed(3),right+10,yy+3);}
 for(const [values,color] of [[benchmark,'#b4bfc2'],[nav,'#cb895e']]){ctx.beginPath();values.forEach((v,i)=>{i?ctx.lineTo(x(i),y(v)):ctx.moveTo(x(i),y(v));});ctx.strokeStyle=color;ctx.lineWidth=1.7;ctx.stroke();}
 ctx.textAlign='center';ctx.font='9px ui-monospace,monospace';for(let i=0;i<=3;i++){const k=Math.round((curve.length-1)*i/3);ctx.fillText(curve[k].date.slice(2),x(k),h-13);}
}
function renderAudit(){
 const m=data.meta;$('#data-summary').innerHTML=`<h2>数据快照 <span class="pill">2026.10.26</span></h2><dl class="data-list"><dt>标的</dt><dd>${m.name}（${m.symbol} / 上海）</dd><dt>数据提供方</dt><dd>${m.provider} · 公开日 K 线接口</dd><dt>复权口径</dt><dd>${m.adjustment}</dd><dt>最新收到 K 线</dt><dd>${m.latestReceivedDate}（已隔离，不参与计算）</dd><dt>最新可用 K 线</dt><dd>${m.latestUsableDate}</dd><dt>有效数据区间</dt><dd>${m.firstDate} — ${m.latestUsableDate} · ${m.rowCount} 根真实交易日日线</dd><dt>可判定信号起点</dt><dd>${rows[20].date}（前 20 根用于均线预热）</dd><dt>交易日连续性</dt><dd>通过 · 无重复、无缺失，按上交所休市安排核验</dd><dt>当次请求链接</dt><dd><a href="${m.source}" target="_blank" rel="noopener">${m.source}</a></dd><dt>原始响应 SHA256</dt><dd class="code">${m.rawSha256}</dd></dl>`;
 $('#quarantine').innerHTML=m.quarantined.map(q=>`<p><b>${q.date}</b> · ${q.reason}。</p><div class="table-scroll"><table class="quarantine-table"><thead><tr><th>同一响应内的数据</th><th>开盘</th><th>收盘</th><th>最高</th><th>最低</th></tr></thead><tbody><tr><td>qfqday 日 K</td><td>${q.qfqOHLC.open}</td><td>${q.qfqOHLC.close}</td><td>${q.qfqOHLC.high}</td><td>${q.qfqOHLC.low}</td></tr><tr><td>qt 报价（仅核验）</td><td>${q.quoteOHLC.open}</td><td>${q.quoteOHLC.close}</td><td>${q.quoteOHLC.high}</td><td>${q.quoteOHLC.low}</td></tr></tbody></table></div><p>不使用 qt 报价或英为财情行情修补前复权序列。这一日没有进入 MA20、有效期、信号或回测。无法可靠判断 ${q.date} 的新买点。</p>`).join('');
 $('#calendar-links').innerHTML=m.calendarSources.map(s=>`<a href="${s.url}" target="_blank" rel="noopener">${s.label} ↗</a>`).join('　');
}
init();
