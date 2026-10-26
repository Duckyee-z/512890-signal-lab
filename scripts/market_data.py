"""Closed daily adjusted prices. Fewer decimal places are advisory, not invalid."""
import argparse
import datetime as dt
import hashlib
import json
import pathlib
import re
import sys
import urllib.request
from decimal import Decimal
from zoneinfo import ZoneInfo

ROOT = pathlib.Path(__file__).resolve().parent.parent
TZ = ZoneInfo('Asia/Shanghai')
TENCENT = 'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=sh512890,day,,,1800,qfq'
EASTMONEY = 'https://push2his.eastmoney.com/api/qt/stock/kline/get?secid=1.512890&klt=101&fqt=1&beg=20180101&end=20500101&fields1=f1,f2,f3,f4,f5,f6&fields2=f51,f52,f53,f54,f55,f56,f57'
SCHEDULE = '每个工作日 16:37、18:37、21:37（北京时间，GitHub Actions 可能延迟）'


def trading_day(date, calendar):
    return date.weekday() < 5 and date.isoformat() not in calendar['holidays']


def closed_cutoff(now, calendar):
    day = now.astimezone(TZ).date()
    if now.astimezone(TZ).time() < dt.time(15, 15):
        day -= dt.timedelta(days=1)
    while not trading_day(day, calendar):
        day -= dt.timedelta(days=1)
    return day


def decode_response(raw, source):
    obj = json.loads(raw)
    if 'sh512890' in (obj.get('data') or {}):
        if obj.get('code') != 0:
            raise ValueError('腾讯响应 code 非0')
        data = obj['data']['sh512890']
        if not isinstance(data.get('qfqday'), list):
            raise ValueError('缺少明确前复权 qfqday，不用 day 替代')
        return data['qfqday'], '腾讯证券', data.get('qt', {}).get('sh512890'), obj
    data = obj.get('data') or {}
    if source == EASTMONEY and obj.get('rc') == 0 and data.get('code') == '512890' and isinstance(data.get('klines'), list):
        return [r.split(',') for r in data['klines']], '东方财富', None, obj
    raise ValueError('不支持的来源或复权响应')


def prepare(raw, source, now, calendar, previous=None, fetched=False):
    values, provider, quote, obj = decode_response(raw, source)
    cutoff = closed_cutoff(now, calendar)
    by_date = {}
    latest_received = None
    precision = []
    for value in values:
        if len(value) < 6:
            raise ValueError('OHLC字段不完整')
        date, op, cl, hi, lo, volume = map(str, value[:6])
        day = dt.date.fromisoformat(date)
        latest_received = max(latest_received or date, date)
        if day > cutoff:
            continue
        prices = [op, cl, hi, lo]
        if any(not re.fullmatch(r'\d+(?:\.\d{1,6})?', p) for p in prices):
            raise ValueError('价格格式或精度不受支持')
        o, c, h, l = map(Decimal, prices)
        if not 0 < l <= min(o, c) <= max(o, c) <= h:
            raise ValueError('OHLC范围不一致')
        if not Decimal(volume).is_finite() or Decimal(volume) < 0:
            raise ValueError('成交量无效')
        if not trading_day(day, calendar):
            raise ValueError('非交易日出现日线')
        row = dict(date=date, open=op, close=cl, high=hi, low=lo, volume=volume)
        if date in by_date and by_date[date] != row:
            raise ValueError('同一日期存在冲突数据')
        by_date[date] = row
    rows = [by_date[d] for d in sorted(by_date)]
    if len(rows) < 45:
        raise ValueError('不足45根完整日线')
    expected = set()
    day = dt.date.fromisoformat(rows[0]['date'])
    end = dt.date.fromisoformat(rows[-1]['date'])
    while day <= end:
        if day.year in calendar['supportedYears'] and trading_day(day, calendar):
            expected.add(day.isoformat())
        day += dt.timedelta(days=1)
    if expected - set(by_date):
        raise ValueError('数据窗口有缺失交易日')
    if previous and rows[-1]['date'] < previous['meta']['latestUsableDate']:
        raise ValueError('行情日期倒退，保留上次有效数据')
    for row in rows:
        fields = [k for k in ('open', 'close', 'high', 'low') if len(row[k].partition('.')[2]) < 3]
        if fields:
            precision.append(dict(date=row['date'], fields=fields, values={k: row[k] for k in fields}))
    stamp = now.astimezone(TZ).isoformat(timespec='seconds')
    old = previous['meta'] if previous else {}
    meta = {
        'symbol': '512890', 'name': '华泰柏瑞中证红利低波动ETF',
        'provider': provider, 'source': source,
        'adjustment': '前复权 · qfqday（提供方原始口径）' if provider == '腾讯证券' else '前复权 · fqt=1（提供方原始口径）',
        'snapshotDate': now.astimezone(TZ).date().isoformat(),
        'latestReceivedDate': latest_received, 'latestUsableDate': rows[-1]['date'],
        'firstDate': rows[0]['date'], 'rowCount': len(rows),
        'rawSha256': hashlib.sha256(raw).hexdigest(), 'rawFile': 'source-market.json',
        'quarantined': [], 'precisionNotes': precision,
        'precisionPolicy': '保留来源原值参与计算；小数位较少仅作提示，不拒绝日K，也不使用行情报价替换。',
        'calendarVerified': all(dt.date.fromisoformat(r['date']).year in calendar['supportedYears'] for r in rows),
        'calendarYears': calendar['supportedYears'], 'calendarSources': old.get('calendarSources', []),
        'rebuiltAt': stamp, 'lastAttemptAt': stamp if fetched else old.get('lastAttemptAt'),
        'lastSuccessfulFetchAt': stamp if fetched else old.get('lastSuccessfulFetchAt'),
        'updateStatus': 'success' if fetched else 'cached', 'lastUpdateError': None,
        'expectedLatestDate': cutoff.isoformat(), 'autoUpdateSchedule': SCHEDULE,
    }
    if quote and len(quote) > 34 and quote[30][:8] == rows[-1]['date'].replace('-', ''):
        meta['quoteComparison'] = {'date': rows[-1]['date'], 'quoteTime': quote[30],
            'qfqOHLC': {k: rows[-1][k] for k in ('open', 'close', 'high', 'low')},
            'quoteOHLC': dict(zip(('open', 'close', 'high', 'low'), (quote[i] for i in (5, 3, 33, 34))))}
    return {'meta': meta, 'rows': rows}


def write_json(path, value):
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, separators=(',', ':')))
    temp.replace(path)


def retain_after_failure(previous, now, errors):
    result = json.loads(json.dumps(previous))
    result['meta'].update(lastAttemptAt=now.astimezone(TZ).isoformat(timespec='seconds'),
        updateStatus='failed', lastUpdateError='；'.join(errors), autoUpdateSchedule=SCHEDULE)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--fetch', action='store_true')
    parser.add_argument('--input', type=pathlib.Path)
    args = parser.parse_args(argv)
    now = dt.datetime.now(TZ)
    path = ROOT / 'dist/data.json'
    previous = json.loads(path.read_text()) if path.exists() else None
    calendar = json.loads((ROOT / 'dist/calendar.json').read_text())
    errors = []
    result = None
    if args.fetch:
        for source in (TENCENT, EASTMONEY):
            try:
                request = urllib.request.Request(source, headers={'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'})
                with urllib.request.urlopen(request, timeout=25) as response:
                    raw = response.read(5_000_000)
                result = prepare(raw, source, now, calendar, previous, fetched=True)
                break
            except Exception as exc:
                errors.append(('腾讯证券' if source == TENCENT else '东方财富') + ': ' + str(exc)[:180])
    else:
        cached = args.input or (ROOT / 'dist/source-market.json')
        if not cached.exists():
            cached = ROOT / 'dist/source-tencent.json'
        raw = cached.read_bytes()
        source = EASTMONEY if 'klines' in (json.loads(raw).get('data') or {}) else TENCENT
        result = prepare(raw, source, now, calendar, previous, fetched=False)
    if result is None:
        if not previous:
            raise RuntimeError('没有可保留的有效行情：' + '；'.join(errors))
        result = retain_after_failure(previous, now, errors)
        print('::warning::行情获取失败，保留上次有效数据。' + '；'.join(errors))
    else:
        temp = ROOT / 'dist/source-market.json.tmp'
        temp.write_bytes(raw)
        temp.replace(ROOT / 'dist/source-market.json')
    write_json(path, result)
    status = {k: result['meta'].get(k) for k in ('updateStatus', 'lastAttemptAt', 'lastSuccessfulFetchAt', 'latestUsableDate', 'expectedLatestDate', 'lastUpdateError', 'provider', 'source', 'autoUpdateSchedule')}
    write_json(ROOT / 'dist/update-status.json', status)
    print(json.dumps(status, ensure_ascii=False))
    if summary := __import__('os').environ.get('GITHUB_STEP_SUMMARY'):
        with open(summary, 'a') as output:
            output.write('### 512890 行情更新\n\n```json\n' + json.dumps(status, ensure_ascii=False, indent=2) + '\n```\n')
    return 0


if __name__ == '__main__':
    sys.exit(main())
