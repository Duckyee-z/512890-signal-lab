import copy
import datetime as dt
import json
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
from market_data import TENCENT, EASTMONEY, TZ, prepare, closed_cutoff, retain_after_failure


class MarketDataTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = (ROOT / 'dist/source-tencent.json').read_bytes()
        cls.obj = json.loads(cls.raw)
        cls.calendar = json.loads((ROOT / 'dist/calendar.json').read_text())
        cls.now = dt.datetime(2026, 10, 26, 17, 0, tzinfo=TZ)

    def build(self, obj=None, **kwargs):
        raw = self.raw if obj is None else json.dumps(obj).encode()
        return prepare(raw, TENCENT, kwargs.pop('now', self.now), self.calendar, **kwargs)

    def test_rounded_latest_candle_uses_verified_complete_precision(self):
        data = self.build()
        self.assertEqual(len(data['rows']), 641)
        self.assertEqual(data['rows'][-1]['date'], '2026-10-26')
        self.assertEqual(data['rows'][-1]['close'], '1.213')
        self.assertEqual(data['rows'][-1]['open'], '1.195')
        self.assertEqual(data['rows'][-1]['high'], '1.215')
        self.assertEqual(data['rows'][-1]['low'], '1.192')
        self.assertEqual(data['meta']['quarantined'], [])
        self.assertEqual(data['meta']['latestCandleCorrection']['originalOHLC']['close'], '1.21')
        self.assertFalse(any(n['date']=='2026-10-26' for n in data['meta']['precisionNotes']))
        self.assertEqual(data['meta']['quoteComparison']['quoteOHLC']['close'], '1.213')

    def test_unclosed_and_future_candles_are_excluded(self):
        data = self.build(now=dt.datetime(2026, 10, 26, 14, 0, tzinfo=TZ))
        self.assertEqual(data['rows'][-1]['date'], '2026-10-23')
        obj = copy.deepcopy(self.obj)
        obj['data']['sh512890']['qfqday'].append(['2026-10-27', '1.1', '1.2', '1.3', '1.0', '100'])
        self.assertEqual(self.build(obj)['rows'][-1]['date'], '2026-10-26')

    def test_weekend_holiday_does_not_advance_market_day(self):
        self.assertEqual(closed_cutoff(dt.datetime(2026, 10, 25, 18, tzinfo=TZ), self.calendar).isoformat(), '2026-10-23')
        self.assertEqual(closed_cutoff(dt.datetime(2026, 10, 5, 18, tzinfo=TZ), self.calendar).isoformat(), '2026-09-30')

    def test_requires_explicit_adjustment(self):
        obj = copy.deepcopy(self.obj)
        d = obj['data']['sh512890']
        d['day'] = d.pop('qfqday')
        with self.assertRaisesRegex(ValueError, 'qfqday'):
            self.build(obj)

    def test_sort_and_identical_duplicates(self):
        obj = copy.deepcopy(self.obj)
        rows = obj['data']['sh512890']['qfqday']
        rows.append(copy.deepcopy(rows[0]))
        rows.reverse()
        self.assertEqual(len(self.build(obj)['rows']), 641)

    def test_missing_session_and_invalid_ohlc_rejected(self):
        obj = copy.deepcopy(self.obj)
        del obj['data']['sh512890']['qfqday'][30]
        with self.assertRaisesRegex(ValueError, '缺失'):
            self.build(obj)
        obj = copy.deepcopy(self.obj)
        obj['data']['sh512890']['qfqday'][-1][4] = '2'
        with self.assertRaisesRegex(ValueError, 'OHLC'):
            self.build(obj)

    def test_conflicting_duplicate_rejected(self):
        obj = copy.deepcopy(self.obj)
        rows = obj['data']['sh512890']['qfqday']
        duplicate = copy.deepcopy(rows[-1])
        duplicate[2] = '1.211'
        rows.append(duplicate)
        with self.assertRaisesRegex(ValueError, '冲突'):
            self.build(obj)

    def test_failure_and_regression_keep_previous_data(self):
        old = self.build(fetched=True)
        failed = retain_after_failure(old, self.now, ['source unavailable'])
        self.assertEqual(failed['rows'], old['rows'])
        self.assertEqual(failed['meta']['latestUsableDate'], old['meta']['latestUsableDate'])
        self.assertEqual(failed['meta']['lastSuccessfulFetchAt'], old['meta']['lastSuccessfulFetchAt'])
        self.assertEqual(failed['meta']['updateStatus'], 'failed')
        obj = copy.deepcopy(self.obj)
        obj['data']['sh512890']['qfqday'].pop()
        with self.assertRaisesRegex(ValueError, '倒退'):
            self.build(obj, previous=old)

    def test_eastmoney_fallback_uses_whole_explicit_qfq_series(self):
        values = copy.deepcopy(self.obj['data']['sh512890']['qfqday'])
        values[-1][1:5] = ['1.195', '1.213', '1.215', '1.192']
        obj = {'rc': 0, 'data': {'code': '512890', 'klines': [','.join(r[:6]) for r in values]}}
        data = prepare(json.dumps(obj).encode(), EASTMONEY, self.now, self.calendar)
        self.assertEqual(data['meta']['provider'], '东方财富')
        self.assertIn('fqt=1', data['meta']['adjustment'])
        self.assertEqual(data['rows'][-1]['close'], '1.213')


    def test_reference_close_must_match_adjustment_basis(self):
        obj = copy.deepcopy(self.obj)
        obj['data']['sh512890']['qt']['sh512890'][4] = '1.200'
        with self.assertRaisesRegex(ValueError, '复权基准'):
            self.build(obj)

    def test_mismatched_volume_is_not_patched(self):
        obj = copy.deepcopy(self.obj)
        obj['data']['sh512890']['qt']['sh512890'][6] = '4148660'
        with self.assertRaisesRegex(ValueError, '成交量'):
            self.build(obj)

    def test_quote_must_be_after_close(self):
        obj = copy.deepcopy(self.obj)
        obj['data']['sh512890']['qt']['sh512890'][30] = '20261026145959'
        with self.assertRaisesRegex(ValueError, '尚未收盘'):
            self.build(obj)

    def test_quote_must_be_same_symbol(self):
        obj = copy.deepcopy(self.obj)
        obj['data']['sh512890']['qt']['sh512890'][2] = '600000'
        with self.assertRaisesRegex(ValueError, '标的不匹配'):
            self.build(obj)

    def test_difference_must_be_explained_by_rounding(self):
        obj = copy.deepcopy(self.obj)
        obj['data']['sh512890']['qt']['sh512890'][33] = '1.230'
        with self.assertRaisesRegex(ValueError, '舍入解释'):
            self.build(obj)

    def test_no_patch_from_another_day(self):
        obj = copy.deepcopy(self.obj)
        obj['data']['sh512890']['qt']['sh512890'][30] = '20261027161439'
        data = self.build(obj)
        self.assertIsNone(data['meta']['latestCandleCorrection'])
        self.assertEqual(data['rows'][-1]['close'], '1.21')

    def test_fewer_digits_alone_are_not_an_error(self):
        obj = copy.deepcopy(self.obj)
        quote = obj['data']['sh512890']['qt']['sh512890']
        for index, value in [(5,'1.200'),(3,'1.210'),(33,'1.220'),(34,'1.190')]:
            quote[index] = value
        data = self.build(obj)
        self.assertEqual(data['rows'][-1]['close'], '1.21')
        self.assertIsNone(data['meta']['latestCandleCorrection'])

    def test_later_fetch_cannot_overwrite_verified_precision_with_rounded_history(self):
        previous = self.build(fetched=True)
        obj = copy.deepcopy(self.obj)
        obj['data']['sh512890']['qt']['sh512890'][30] = '20261027161439'
        with self.assertRaisesRegex(ValueError, '已知舍入价格'):
            self.build(obj, previous=previous)


if __name__ == '__main__':
    unittest.main()
