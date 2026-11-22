import os
import unittest

os.environ.setdefault("SUPABASE_URL", "https://x.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "sb_secret_test")

from ingest import db, geocode  # noqa: E402


class FakeResp:
    def __init__(self, status, payload):
        self.status_code, self._p = status, payload

    def json(self):
        return self._p

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError(str(self.status_code))


class FakeSession:
    def __init__(self, answers, status=200):
        self.answers, self.status, self.calls, self.headers = answers, status, [], {}

    def get(self, url, params=None, timeout=None):
        self.calls.append(params["q"])
        if self.status != 200:
            return FakeResp(self.status, [])
        hit = self.answers.get(params["q"])
        return FakeResp(200, [{"lat": str(hit[0]), "lon": str(hit[1])}] if hit else [])


class GeocodeTests(unittest.TestCase):
    def setUp(self):
        self.updates = []
        self.stores = []
        db.select_all = lambda *a, **k: list(self.stores)
        db.update = lambda table, flt, vals: self.updates.append((flt["id"], vals))
        geocode.DELAY = 0
        geocode.time.sleep = lambda s: None
        geocode.MAX_PER_RUN = 1500

    def run_with(self, answers, status=200):
        self.session = FakeSession(answers, status)
        geocode.requests.Session = lambda: self.session
        geocode.main()

    def test_exact_address_is_saved_as_precise(self):
        self.stores = [{"id": "s1", "city": "תל אביב", "address": "דיזנגוף 50"}]
        self.run_with({"דיזנגוף 50, תל אביב": (32.0786, 34.7740)})
        (sid, vals), = self.updates
        self.assertEqual((sid, vals["lat"], vals["lng"], vals["geocode_approx"], vals["geocode_failed"]), ("s1", 32.0786, 34.7740, False, False))
        self.assertEqual(self.session.calls, ["דיזנגוף 50, תל אביב"])

    def test_falls_back_to_city_and_marks_approximate(self):
        self.stores = [{"id": "s1", "city": "קריית שמונה", "address": "רחוב לא קיים 999"}]
        self.run_with({"קריית שמונה": (33.2074, 35.5712)})
        self.assertEqual(self.session.calls, ["רחוב לא קיים 999, קריית שמונה", "קריית שמונה"])
        self.assertTrue(self.updates[0][1]["geocode_approx"])

    def test_nothing_found_is_marked_failed_so_it_is_not_retried_forever(self):
        self.stores = [{"id": "s1", "city": "???", "address": "???"}]
        self.run_with({})
        self.assertTrue(self.updates[0][1]["geocode_failed"])

    def test_result_outside_israel_is_rejected(self):
        self.stores = [{"id": "s1", "city": "פריז", "address": "רחוב א 1"}]
        self.run_with({"רחוב א 1, פריז": (48.85, 2.35), "פריז": (48.85, 2.35)})
        self.assertTrue(self.updates[0][1]["geocode_failed"])

    def test_same_city_fallback_is_queried_once(self):
        self.stores = [{"id": f"s{i}", "city": "ערד", "address": ""} for i in range(5)]
        self.run_with({"ערד": (31.26, 35.21)})
        self.assertEqual(self.session.calls, ["ערד"], "5 stores in the same city -> one request (cache + politeness)")
        self.assertEqual(len(self.updates), 5)

    def test_junk_addresses_are_ignored(self):
        self.assertEqual(geocode.candidates({"address": "לא ידוע", "city": "חיפה"}), [("חיפה", True)])
        self.assertEqual(geocode.candidates({"address": "0", "city": ""}), [])

    def test_max_per_run_is_respected(self):
        geocode.MAX_PER_RUN = 2
        self.stores = [{"id": f"s{i}", "city": f"עיר{i}", "address": ""} for i in range(5)]
        self.run_with({f"עיר{i}": (32.0, 34.8) for i in range(5)})
        self.assertEqual(len(self.updates), 2)

    def test_rate_limit_stops_the_run_without_marking_stores_failed(self):
        self.stores = [{"id": "s1", "city": "חיפה", "address": ""}]
        self.run_with({}, status=429)
        self.assertEqual(self.updates, [], "a rate-limited store must stay unprocessed so the next run retries it")


if __name__ == "__main__":
    unittest.main()
