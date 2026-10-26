import json,datetime,hashlib,pathlib,sys
from decimal import Decimal
ROOT=pathlib.Path(__file__).resolve().parent.parent
raw=(pathlib.Path(sys.argv[1]) if len(sys.argv)>1 else ROOT/'dist/source-tencent.json').read_bytes()
j=json.loads(raw)
assert j['code']==0
x=j['data']['sh512890']; values=x['qfqday']; assert len(values)>=45
holiday_ranges={
 '2024':[('01-01','01-01'),('02-09','02-17'),('04-04','04-06'),('05-01','05-05'),('06-10','06-10'),('09-15','09-17'),('10-01','10-07')],
 '2025':[('01-01','01-01'),('01-28','02-04'),('04-04','04-06'),('05-01','05-05'),('05-31','06-02'),('10-01','10-08')],
 '2026':[('01-01','01-03'),('02-15','02-23'),('04-04','04-06'),('05-01','05-05'),('06-19','06-21'),('09-25','09-27'),('10-01','10-07')]}
holidays=set()
for year,ranges in holiday_ranges.items():
 for a,b in ranges:
  d=datetime.date.fromisoformat(year+'-'+a);last=datetime.date.fromisoformat(year+'-'+b)
  while d<=last:holidays.add(d.isoformat());d+=datetime.timedelta(days=1)
qt=x['qt']['sh512890'];quarantined=[]
if values[-1][0].replace('-','')==qt[30][:8]:
 r=values[-1]
 if [Decimal(r[i]) for i in [1,2,3,4]]!=[Decimal(qt[i]) for i in [5,3,33,34]]:
  quarantined.append({'date':r[0],'reason':'前复权日K与同响应报价精度及OHLC不一致，隔离且不参与计算','qfqOHLC':{'open':r[1],'close':r[2],'high':r[3],'low':r[4]},'quoteOHLC':{'open':qt[5],'close':qt[3],'high':qt[33],'low':qt[34]}})
  values=values[:-1]
rows=[];seen=set();prev=''
for r in values:
 date,op,cl,hi,lo,volume=r[:6]
 assert date>prev and date not in seen,'日期重复或乱序'
 prev=date;seen.add(date)
 o,c,h,l=map(Decimal,[op,cl,hi,lo]);assert 0<l<=min(o,c)<=max(o,c)<=h
 rows.append(dict(date=date,open=op,close=cl,high=hi,low=lo,volume=volume))
expected=[];d=datetime.date.fromisoformat(rows[0]['date']);end=datetime.date.fromisoformat(rows[-1]['date'])
while d<=end:
 if d.weekday()<5 and d.isoformat() not in holidays:expected.append(d.isoformat())
 d+=datetime.timedelta(days=1)
assert set(expected)==seen,'交易日缺失或多余'
source='https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=sh512890,day,,,1800,qfq'
meta={'symbol':'512890','name':'华泰柏瑞中证红利低波动ETF','provider':'腾讯证券','source':source,'adjustment':'前复权 · qfqday（提供方原始口径）','snapshotDate':'2026-10-26','latestReceivedDate':x['qfqday'][-1][0],'latestUsableDate':rows[-1]['date'],'firstDate':rows[0]['date'],'rowCount':len(rows),'rawSha256':hashlib.sha256(raw).hexdigest(),'quarantined':quarantined,'calendarVerified':True,'calendarYears':[2024,2025,2026],'calendarSources':[
 {'label':'上交所2024休市安排','url':'https://www.sse.com.cn/disclosure/dealinstruc/closed/c/c_20231226_5733941.shtml'},
 {'label':'上交所2025休市安排','url':'https://www.sse.com.cn/disclosure/announcement/general/c/c_20241223_10767108.shtml'},
 {'label':'上交所2026休市安排','url':'https://www.sse.com.cn/disclosure/dealinstruc/closed/c/c_20251222_10802510.shtml'}
 ],'crossCheck':{'url':'https://cn.investing.com/etfs/huatai-pinebridge-csi-div-low-vol-historical-data','range':'2026-09-21 — 2026-10-23','note':'最近19根有效K线OHLC逐项一致；此网页未明确复权口径，仅作交叉核验，不替代前复权序列。'}}
(ROOT/'dist/data.json').write_text(json.dumps({'meta':meta,'rows':rows},ensure_ascii=False,separators=(',',':')))
(ROOT/'dist/source-tencent.json').write_bytes(raw)
(ROOT/'dist/calendar.json').write_text(json.dumps({'holidays':sorted(holidays),'supportedYears':[2024,2025,2026]}))
print(json.dumps({'rows':len(rows),'first':rows[0]['date'],'last':rows[-1]['date'],'quarantined':quarantined},ensure_ascii=False))
