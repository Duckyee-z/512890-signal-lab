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

    def test_two_decimals_and_quote_mismatch_are_included_unchanged(self):
        data = self.build()
        self.assertEqual(len(data['rows']), 641)
        self.assertEqual(data['rows'][-1]['date'], '2026-10-26')
        self.assertEqual(data['rows'][-1]['close'], '1.21')
        self.assertEqual(data['meta']['quarantined'], [])
        self.assertEqual(data['meta']['precisionNotes'][-1]['date'], '2026-10-26')
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
        values = self.obj['data']['sh512890']['qfqday']
        obj = {'rc': 0, 'data': {'code': '512890', 'klines': [','.join(r[:6]) for r in values]}}
        data = prepare(json.dumps(obj).encode(), EASTMONEY, self.now, self.calendar)
        self.assertEqual(data['meta']['provider'], '东方财富')
        self.assertIn('fqt=1', data['meta']['adjustment'])
        self.assertEqual(data['rows'][-1]['close'], '1.21')


if __name__ == '__main__':
    unittest.main()
