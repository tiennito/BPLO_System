import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from backend.renewal_service import (
    DEFAULT_RENEWAL_SETTINGS,
    calculate_renewal_fees,
    calendar_permit_validity,
    delayed_months,
    filed_after_deadline,
    renewal_window,
)


try:
    MANILA = ZoneInfo("Asia/Manila")
except Exception:
    MANILA = timezone(timedelta(hours=8), name="Asia/Manila")
MIGRATION = Path(__file__).resolve().parents[1] / "database" / "17. annual_business_permit_renewals.sql"


class AnnualRenewalRuleTests(unittest.TestCase):
    def test_calendar_year_validity_always_ends_december_31(self):
        self.assertEqual(calendar_permit_validity("2026-02-14")["valid_until"], "2026-12-31")
        self.assertEqual(calendar_permit_validity("2026-11-30")["valid_until"], "2026-12-31")
        self.assertEqual(calendar_permit_validity("2026-12-31")["valid_until"], "2026-12-31")
        self.assertEqual(calendar_permit_validity("2026-12-31")["renewal_year"], 2027)

    def test_january_20_deadline_uses_manila_end_of_day(self):
        window = renewal_window(2027, DEFAULT_RENEWAL_SETTINGS)
        self.assertFalse(filed_after_deadline(datetime(2027, 1, 1, 9, 0, tzinfo=MANILA), window["effective_due_date"]))
        self.assertFalse(filed_after_deadline(datetime(2027, 1, 20, 23, 59, 59, tzinfo=MANILA), window["effective_due_date"]))
        self.assertTrue(filed_after_deadline(datetime(2027, 1, 21, 0, 0, tzinfo=MANILA), window["effective_due_date"]))
        self.assertFalse(filed_after_deadline("2027-01-20T15:59:59+00:00", window["effective_due_date"]))
        self.assertTrue(filed_after_deadline("2027-01-20T16:00:00+00:00", window["effective_due_date"]))

    def test_delayed_months_are_capped(self):
        self.assertEqual(delayed_months("2027-01-20", "2032-01-20", "anniversary_cycle", maximum=36), 36)

    def test_extension_can_suspend_penalties(self):
        values = calculate_renewal_fees(
            base_renewal_fee="1000",
            other_fees="100",
            penalty_base="1000",
            is_late=True,
            due_date="2027-01-20",
            calculation_date="2027-04-21",
            settings=DEFAULT_RENEWAL_SETTINGS,
            extension={"surcharge_suspended": True, "interest_suspended": True},
        )
        self.assertEqual(values["surcharge_amount"], "0.00")
        self.assertEqual(values["interest_amount"], "0.00")
        self.assertEqual(values["total_amount"], "1100.00")


class AnnualRenewalMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sql = MIGRATION.read_text(encoding="utf-8").lower()

    def test_duplicate_renewal_index_exists(self):
        self.assertIn("applications_unique_source_renewal_year_idx", self.sql)
        self.assertIn("where application_type = 'renewal'", self.sql)

    def test_notification_dedupe_and_assessment_lock_exist(self):
        self.assertIn("renewal_notification_logs_unique_idx", self.sql)
        self.assertIn("lock_finalized_renewal_assessment", self.sql)

    def test_view_is_security_invoker_and_not_publicly_exposed(self):
        self.assertIn("with (security_invoker = true)", self.sql)
        self.assertIn("revoke all on public.renewal_monitoring from anon, authenticated", self.sql)
        self.assertIn("grant select on public.renewal_monitoring to service_role", self.sql)


if __name__ == "__main__":
    unittest.main()
