"""Closed daily adjusted prices. Fewer decimal places are advisory, not invalid."""
import argparse
import datetime as dt
import hashlib
import json
import pathlib
import re
import sys
import urllib.request
from decimal import Decimal, ROUND_HALF_UP
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


def reconcile_latest_candle(rows, quote):
    """Recover a rounded latest qfq candle only with a verified same-source close.

    Latest-day qfq is anchored to current prices. Require the previous qfq close
    to equal the quote's previous-close reference, matching volume and date,
    an after-close timestamp, and rounding-compatible OHLC for every field.
    Never apply the latest quote to an older candle or adjust history by guess.
    """
    if not quote or len(quote) <= 34 or len(rows) < 2:
        return None
    latest = rows[-1]
    if quote[30][:8] != latest['date'].replace('-', ''):
        return None
    if str(quote[2]) != '512890':
        raise ValueError('同源收盘报价标的不匹配')
    quoted = dict(zip(('open', 'close', 'high', 'low'), (str(quote[i]) for i in (5, 3, 33, 34))))
    if any(not re.fullmatch(r'\d+(?:\.\d{1,6})?', value) for value in quoted.values()):
        raise ValueError('同源收盘报价价格格式无效')
    if all(Decimal(latest[k]) == Decimal(quoted[k]) for k in quoted):
        return None
    stamp = dt.datetime.strptime(quote[30], '%Y%m%d%H%M%S')
    if stamp.time() < dt.time(15, 0):
        raise ValueError('最新日线与报价不一致，报价尚未收盘，尝试其他完整前复权来源')
    if Decimal(rows[-2]['close']) != Decimal(str(quote[4])):
        raise ValueError('昨收与前一日复权收盘不一致，无法确认同一复权基准')
    if Decimal(latest['volume']) != Decimal(str(quote[6])):
        raise ValueError('最新日线与收盘报价成交量不一致，无法校准')
    o, c, h, l = (Decimal(quoted[k]) for k in ('open', 'close', 'high', 'low'))
    if not 0 < l <= min(o, c) <= max(o, c) <= h:
        raise ValueError('完整精度收盘报价OHLC无效')
    for key, value in quoted.items():
        decimals = len(latest[key].partition('.')[2])
        quantum = Decimal(1).scaleb(-decimals)
        if Decimal(value).quantize(quantum, rounding=ROUND_HALF_UP) != Decimal(latest[key]):
            raise ValueError('日线与同源报价差异不能由小数位舍入解释，尝试其他前复权来源')
    correction = {
        'date': latest['date'], 'source': '腾讯证券同响应 qt 已收盘OHLC',
        'quoteTime': quote[30],
        'originalOHLC': {k: latest[k] for k in quoted}, 'usedOHLC': quoted,
        'previousAdjustedClose': rows[-2]['close'], 'quotedPreviousClose': str(quote[4]),
        'matchedVolume': latest['volume'],
        'checks': ['同标的、同交易日', '报价时间在收盘后', '昨收与前一日前复权收盘一致',
                   '成交量一致', '全部OHLC差异可由舍入解释'],
    }
    latest.update(quoted)
    return correction


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
    original_latest_ohlc = {k: rows[-1][k] for k in ('open', 'close', 'high', 'low')}
    correction = reconcile_latest_candle(rows, quote) if provider == '腾讯证券' else None
    if previous:
        prior = {row['date']: row for row in previous['rows']}
        for row in rows:
            if row['date'] not in prior:
                continue
            for key in ('open', 'close', 'high', 'low'):
                old_value, new_value = prior[row['date']][key], row[key]
                old_digits, new_digits = len(old_value.partition('.')[2]), len(new_value.partition('.')[2])
                if new_digits < old_digits and Decimal(old_value) != Decimal(new_value):
                    quantum = Decimal(1).scaleb(-new_digits)
                    if Decimal(old_value).quantize(quantum, rounding=ROUND_HALF_UP) == Decimal(new_value):
                        raise ValueError('来源退回已知舍入价格，尝试其他完整前复权来源，不覆盖完整精度历史')
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
        'precisionPolicy': '小数位数本身不作为拒绝条件。最新日线若与完整精度同源收盘报价不同，仅在标的、日期、收盘时间、昨收基准、成交量及舍入关系全部通过后校准整组OHLC；记录原值与采用值。不能校准则换完整前复权来源。',
        'latestCandleCorrection': correction,
        'calendarVerified': all(dt.date.fromisoformat(r['date']).year in calendar['supportedYears'] for r in rows),
        'calendarYears': calendar['supportedYears'], 'calendarSources': old.get('calendarSources', []),
        'rebuiltAt': stamp, 'lastAttemptAt': stamp if fetched else old.get('lastAttemptAt'),
        'lastSuccessfulFetchAt': stamp if fetched else old.get('lastSuccessfulFetchAt'),
        'updateStatus': 'success' if fetched else 'cached', 'lastUpdateError': None,
        'expectedLatestDate': cutoff.isoformat(), 'autoUpdateSchedule': SCHEDULE,
    }
    if quote and len(quote) > 34 and quote[30][:8] == rows[-1]['date'].replace('-', ''):
        meta['quoteComparison'] = {'date': rows[-1]['date'], 'quoteTime': quote[30],
            'qfqOHLC': original_latest_ohlc,
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
