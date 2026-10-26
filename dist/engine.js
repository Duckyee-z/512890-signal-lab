// Exact fixed-point comparisons. Prices retain the provider's decimal strings.
const SCALE=1000000n;
export function fixed(v){
  if(!/^\d+(\.\d{1,6})?$/.test(String(v)))throw new Error('价格精度或格式无效');
  const [a,b='']=String(v).split('.');return BigInt(a)*SCALE+BigInt(b.padEnd(6,'0'));
}
export function analyze(input){
  let prev='';
  const rows=input.map((r,i)=>{
    if(!/^\d{4}-\d{2}-\d{2}$/.test(r.date)||r.date<=prev)throw new Error('日期必须升序且唯一');prev=r.date;
    const q={...r,index:i};for(const k of ['open','high','low','close']){q[k+'Q']=fixed(r[k]);if(q[k+'Q']<=0n)throw new Error('价格须大于0');q[k+'N']=Number(r[k]);}
    if(q.lowQ>q.openQ||q.lowQ>q.closeQ||q.highQ<q.openQ||q.highQ<q.closeQ||q.lowQ>q.highQ)throw new Error('OHLC不完整或不一致');
    return q;
  });
  let sum=0n,event=null;const signals=[],events=[];
  for(let i=0;i<rows.length;i++){
    const r=rows[i];sum+=r.closeQ;if(i>=20)sum-=rows[i-20].closeQ;
    r.sum20=i>=19?sum:null;r.ma=i>=19?Number(sum)/Number(SCALE)/20:null;
    r.signals=[];r.statusA='预热';r.statusB='预热';r.remaining=null;
    if(i<20)continue; // Both current AND previous MA must exist before a cross.
    const cross=rows[i-1].closeQ*20n<rows[i-1].sum20&&r.closeQ*20n>sum;
    r.cross=cross;
    if(cross){
      event={start:i,date:r.date,peak:null,A:null,B:null,ended:false,endReason:null};events.push(event);
    }
    if(event&&!event.ended){
      const age=i-event.start;r.breakout=event.date;r.remaining=Math.max(0,10-age);
      if(age>0){
        if(r.closeQ*20n<sum){event.ended=true;event.endReason='收盘跌破MA20';r.invalid=event.endReason;}
        else if(age<=10){
          const near=r.closeQ*20n>=sum&&r.closeQ*20n*1000n<=sum*1005n;
          const trigger=(strategy)=>{
            event[strategy]=i;r.signals.push(strategy);
            signals.push({strategy,index:i,date:r.date,breakout:event.date,peak:event.peak==null?null:rows[event.peak].date,age,remaining:10-age,close:r.closeN,ma:r.ma});
          };
          if(event.A==null&&near)trigger('A');
          if(event.B==null&&event.peak!=null&&i>event.peak&&near&&r.closeQ<rows[i-1].closeQ)trigger('B');
          // B's surge must be in the post-breakout window, not the breakout day.
          if(event.peak==null&&r.closeQ*20n*1000n>=sum*1015n)event.peak=i;
          if(age===10){event.ended=true;event.endReason='第10个交易日到期';r.expired=true;}
        }else{event.ended=true;event.endReason='窗口到期';}
      }
      r.peak=event.peak==null?null:rows[event.peak].date;
      for(const s of ['A','B']){
        r['status'+s]=r.signals.includes(s)?'触发':event[s]!=null?'已触发':event.ended?'失效':s==='B'&&event.peak==null?'等待冲高':'等待回踩';
      }
    }else{r.statusA='等待突破';r.statusB='等待突破';r.remaining=null;}
  }
  return {rows,signals,events};
}
export function forwardReturn(rows,index,horizon){
  const entry=rows[index+1],exit=rows[index+horizon];
  return entry&&exit?exit.closeN/entry.openN-1:null;
}
// Independent A / B / combined simulation, no positions carried into the selected range.
// Close-confirmed entry and +5% take profit are both executed at the next available open.
export function simulate(rows,signals,{start,end,strategy='A',capital=100000,feeBps=3,slippageBps=0}={}){
  const window=rows.filter(r=>r.date>=start&&r.date<=end);const fee=feeBps/10000,slip=slippageBps/10000;
  let cash=capital,positions=[],pending=[],peak=capital,maxDrawdown=0;const trades=[],curve=[];
  const signalMap=new Map();for(const s of signals){if(strategy!=='AB'&&s.strategy!==strategy)continue;const v=signalMap.get(s.index)||[];v.push(s);signalMap.set(s.index,v);}
  for(const r of window){
    for(const p of positions.filter(p=>p.sellNext)){
      const exit=r.openN*(1-slip),proceeds=p.quantity*exit;cash+=proceeds*(1-fee);
      trades.push({...p,exitDate:r.date,exit,netReturn:(proceeds*(1-fee)-p.cost)/p.cost});
    }
    positions=positions.filter(p=>!p.sellNext);
    for(const s of pending){
      const budget=capital*.5;
      if(positions.length>=2||cash+1e-8<budget)continue;
      const entry=r.openN*(1+slip),quantity=budget/(entry*(1+fee));cash-=budget;
      positions.push({signalDate:s.date,strategy:s.strategy,entryDate:r.date,entry,quantity,cost:budget,sellNext:false});
    }
    pending=[];
    for(const p of positions){if(r.closeN>=p.entry*1.05)p.sellNext=true;}
    pending=signalMap.get(r.index)||[];
    const equity=cash+positions.reduce((v,p)=>v+p.quantity*r.closeN,0);peak=Math.max(peak,equity);maxDrawdown=Math.max(maxDrawdown,1-equity/peak);
    curve.push({date:r.date,equity,close:r.closeN});
  }
  return {trades,positions,curve,cash,totalReturn:curve.length?curve.at(-1).equity/capital-1:0,maxDrawdown,pending:pending.length};
}
