import unittest
from pathlib import Path

from backend.permit_document import permit_storage_path, render_permit_pdf, render_permit_svg


MIGRATION = Path(__file__).resolve().parents[1] / "database" / "20. official_business_permit_release.sql"


SAMPLE_PERMIT = {
    "permit_number": "BP-2026-000001",
    "owner_name": "Sebastien Badulis",
    "business_name": "Badulis General Merchandise",
    "business_address": "Barangay San Roque, Victoria, Laguna",
    "release_date": "2026-07-17",
    "expiration_date": "2026-12-31",
    "official_receipt_number": "OR-2026-000001",
    "payment_date_time": "2026-07-17T15:45:00+08:00",
    "payment_amount": "2450.00",
    "sp_number": "BP-2026-000001",
    "authorized_official_name": "Juan Dela Cruz",
    "authorized_official_position": "Municipal Mayor",
    "qr_verification_url": "https://example.gov.ph/verify/permit/sample",
}


class OfficialPermitDocumentTests(unittest.TestCase):
    def test_pdf_renderer_outputs_single_a4_pdf(self):
        pdf = render_permit_pdf(SAMPLE_PERMIT)
        self.assertTrue(pdf.startswith(b"%PDF"))
        self.assertIn(b"/MediaBox [ 0 0 595.2756 841.8898 ]", pdf)

    def test_svg_preview_contains_official_fields(self):
        svg = render_permit_svg(SAMPLE_PERMIT)
        self.assertIn("PAHINTULOT SA PANGANGALAKAL", svg)
        self.assertIn("BP-2026-000001", svg)
        self.assertIn("BADULIS GENERAL MERCHANDISE", svg)
        self.assertIn("SCAN TO VERIFY", svg)

    def test_storage_path_is_stable_and_versioned(self):
        self.assertEqual(
            permit_storage_path("BP-2026-000001", 2),
            "2026/BP-2026-000001/permit-v2.pdf",
        )


class OfficialPermitMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sql = MIGRATION.read_text(encoding="utf-8").lower()

    def test_atomic_numbering_and_private_bucket_exist(self):
        self.assertIn("create table if not exists public.permit_number_counters", self.sql)
        self.assertIn("on conflict (permit_year) do update", self.sql)
        self.assertIn("values ('business-permits', 'business-permits', false", self.sql)

    def test_release_functions_are_service_role_only(self):
        self.assertIn("reserve_official_business_permit", self.sql)
        self.assertIn("finalize_official_business_permit_release", self.sql)
        self.assertIn("revoke all on function public.reserve_official_business_permit", self.sql)
        self.assertIn("grant execute on function public.finalize_official_business_permit_release", self.sql)

    def test_released_permit_immutability_exists(self):
        self.assertIn("protect_released_business_permit", self.sql)
        self.assertIn("prevent_released_business_permit_delete", self.sql)
        self.assertIn("released permit snapshots and files are immutable", self.sql)


if __name__ == "__main__":
    unittest.main()
