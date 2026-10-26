import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {analyze,fixed,forwardReturn,simulate} from '../dist/engine.js';
const make=(prices)=>prices.map((v,i)=>{const p=String(v);return {date:new Date(Date.UTC(2024,0,i+1)).toISOString().slice(0,10),open:p,high:p,low:p,close:p,volume:'100'};});
const base=()=>[...Array(19).fill('1'),'0.9','1.1'];
test('requires both MAs; no fabricated initial cross',()=>{
 const r=analyze(make(Array(25).fill('1.1')));assert.equal(r.events.length,0);assert.equal(r.signals.length,0);assert.equal(r.rows[18].ma,null);assert.ok(r.rows[19].ma);
});
test('A includes equality to MA20; no repeated signals per event',()=>{
 const r=analyze(make([...base(),'1','1','1']));assert.deepEqual(r.signals.map(s=>[s.strategy,s.index]),[['A',21]]);assert.equal(r.rows[21].statusA,'触发');assert.equal(r.rows[22].statusA,'已触发');assert.equal(r.rows[21].ma,1);
});
test('strict cross excludes previous equality and breakout day cannot be a pullback',()=>{
 const r=analyze(make([...Array(20).fill('1'),'1.001']));assert.equal(r.events.length,0);
 const q=analyze(make([...Array(19).fill('1'),'0.99','1.001']));assert.equal(q.events.length,1);assert.equal(q.signals.length,0);
});
test('B requires surge strictly after breakout then a later declining pullback',()=>{
 const r=analyze(make([...base(),'1.04','1.004','1.003']));assert.deepEqual(r.signals.map(s=>s.strategy),['A','B']);assert.equal(r.signals[1].peak,r.rows[21].date);assert.equal(r.signals[1].index,22);
 const q=analyze(make([...base(),'1','1']));assert.equal(q.signals.filter(s=>s.strategy==='B').length,0);assert.equal(q.rows[21].statusB,'等待冲高');
});
test('waiting close below MA invalidates both; new true cross resets',()=>{
 const r=analyze(make([...base(),'0.99','1.1','1.007']));assert.equal(r.rows[21].statusA,'失效');assert.equal(r.rows[21].statusB,'失效');assert.equal(r.events.length,2);assert.equal(r.signals[0].breakout,r.rows[22].date);
});
test('10th day included, 11th excluded, window moves by rows not calendar days',()=>{
 const pp=[...base(),...Array(9).fill('1.02'),'1.011'];const r=analyze(make(pp));assert.equal(r.signals.at(-1)?.index,30);assert.equal(r.signals.at(-1)?.remaining,0);
 const q=analyze(make([...base(),...Array(10).fill('1.02'),'1.011']));assert.equal(q.signals.length,0);assert.equal(q.rows[30].statusA,'失效');assert.equal(q.rows[31].statusA,'等待突破');
});
test('exact fixed precision has no premature rounding',()=>{
 assert.equal(fixed('1.005001'),1005001n);assert.equal(fixed('1.005000'),1005000n);assert.throws(()=>fixed('1.0050001'));
 // 19 prior closes sum to 18.995, so MA is exactly 1 when C=1.005.
 const seed=[...Array(18).fill('1'),'0.995','0.9','1.1','1.005'];
 const r=analyze(make(seed));assert.equal(r.rows[21].ma,1);assert.deepEqual(r.signals.map(s=>s.strategy),['A']);
 const q=analyze(make([...seed.slice(0,-1),'1.005001']));assert.equal(q.signals.length,0);
});
test('B at 1.5% exact surge threshold and later pullback, A and B independent',()=>{
 // At day21, previous19 sum=18.985; adding1.015 gives MA=1.
 const seed=[...Array(18).fill('1'),'0.985','0.9','1.1','1.015','1.004'];
 const r=analyze(make(seed));assert.equal(r.rows[21].ma,1);assert.equal(r.rows[22].peak,r.rows[21].date);assert.ok(r.signals.some(s=>s.strategy==='B'));
});
test('future prices cannot alter earlier signals or states',()=>{
 const p=[...base(),'1.04','1.004','1.003'];const a=analyze(make(p)),b=analyze(make([...p,'5','0.1','2']));assert.deepEqual(b.signals.filter(s=>s.index<p.length),a.signals);for(let i=0;i<p.length;i++)assert.equal(a.rows[i].statusB,b.rows[i].statusB);
});
test('invalid/duplicate data is rejected instead of used',()=>{
 const r=make(['1','1']);r[1].date=r[0].date;assert.throws(()=>analyze(r));const q=make(['1']);q[0].low='2';assert.throws(()=>analyze(q));
});
test('next-open execution, fee, two positions maximum, last-day signal not filled',()=>{
 const a=analyze(make(['1','1','1.1','1.2','1.3']));
 const ss=[{date:a.rows[0].date,index:0,strategy:'A'},{date:a.rows[0].date,index:0,strategy:'B'},{date:a.rows[1].date,index:1,strategy:'A'},{date:a.rows[4].date,index:4,strategy:'B'}];
 const s=simulate(a.rows,ss,{start:a.rows[0].date,end:a.rows[4].date,strategy:'AB',capital:100000,feeBps:0});assert.equal(s.trades.length,2);assert.equal(s.trades[0].entryDate,a.rows[1].date);assert.equal(s.trades[0].exitDate,a.rows[3].date);assert.equal(s.trades[0].exit,1.2);assert.equal(s.positions.length,0);assert.equal(s.pending,1);assert.ok(s.cash>100000);
 const f=simulate(a.rows,[ss[0]],{start:a.rows[0].date,end:a.rows[1].date,strategy:'A',capital:100000,feeBps:3});assert.ok(f.totalReturn<0);assert.ok(f.positions.length<=2);
});
test('actual data: validated rows, independent forward return, warmup, full reconstruction invariant',()=>{
 const d=JSON.parse(fs.readFileSync(new URL('../dist/data.json',import.meta.url)));assert.ok(d.rows.length>=45);assert.equal(d.meta.latestUsableDate,d.rows.at(-1).date);assert.equal(d.meta.rowCount,d.rows.length);assert.deepEqual(d.meta.quarantined,[]);
 const a=analyze(d.rows);assert.ok(a.signals.length>0);assert.ok(a.signals.every(s=>s.index>=21));
 const seen=new Set();for(const s of a.signals){const key=s.strategy+s.breakout;assert.ok(!seen.has(key));seen.add(key);assert.ok(s.age>=1&&s.age<=10);if(s.strategy==='B')assert.ok(s.peak<s.date&&s.peak>s.breakout);}
 const ret=forwardReturn(a.rows,a.rows.length-10,20);assert.equal(ret,null);assert.equal(forwardReturn(a.rows,30,20),a.rows[50].closeN/a.rows[31].openN-1);
 // A shortened display always filters the same full reconstruction.
 const filtered=a.signals.filter(s=>s.date>='2026-07-23');assert.deepEqual(filtered,analyze(d.rows).signals.filter(s=>s.date>='2026-07-23'));
});
