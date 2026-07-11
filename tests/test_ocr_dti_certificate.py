import sys
import types
import unittest

sys.modules.setdefault("cv2", types.SimpleNamespace())
sys.modules.setdefault("fitz", types.SimpleNamespace())
sys.modules.setdefault("numpy", types.SimpleNamespace())
sys.modules.setdefault("pytesseract", types.SimpleNamespace(pytesseract=types.SimpleNamespace(tesseract_cmd="")))
fake_image = types.SimpleNamespace()
fake_image_ops = types.SimpleNamespace()
sys.modules.setdefault("PIL", types.SimpleNamespace(Image=fake_image, ImageOps=fake_image_ops))
sys.modules.setdefault("PIL.Image", fake_image)
sys.modules.setdefault("PIL.ImageOps", fake_image_ops)

from backend.ocr_service import OCRServiceMixin


class DtiCertificateOcrTests(unittest.TestCase):
    def setUp(self):
        self.ocr = OCRServiceMixin()

    def test_extracts_dti_certificate_values_without_surrounding_prose(self):
        raw_text = """
        dti
        This certifies that
        WOODCRAVERS ONLINE SHOP
        (NATIONAL)
        is a business name registered in this office pursuant to the provisions of Act 3883, as amended
        by Act 4147 and Republic Act No. 863, and in compliance with the applicable rules and
        regulations prescribed by the Department of Trade and Industry.
        This certificate issued to
        LEONARD REMI PENA LIU
        is valid from 16 January 2025 to 16 January 2030 subject to continuing compliance
        In testimony whereof, I hereby sign this
        Certificate of Business Name Registration
        Business Name No.1426992
        This certificate is not a license to engage in any kind of business
        """

        result = self.ocr.build_structured_ocr_result(raw_text, "DTI Certificate")
        structured = result["structured_fields"]
        flat = result["flat_fields"]

        self.assertEqual(structured["business_name"]["value"], "WOODCRAVERS ONLINE SHOP")
        self.assertEqual(structured["owner_name"]["value"], "LEONARD REMI PENA LIU")
        self.assertEqual(structured["registration_number"]["value"], "1426992")
        self.assertEqual(flat["business_name"], "WOODCRAVERS ONLINE SHOP")
        self.assertEqual(flat["owner_name"], "LEONARD REMI PENA LIU")
        self.assertEqual(flat["registration_number"], "1426992")
        self.assertGreaterEqual(structured["business_name"]["confidence"], 90)
        self.assertGreaterEqual(structured["owner_name"]["confidence"], 90)
        self.assertGreaterEqual(structured["registration_number"]["confidence"], 90)

    def test_dti_prose_is_not_given_high_confidence_as_a_value(self):
        field = self.ocr.build_structured_field(
            "business_name",
            "registered in this office pursuant to the provisions of Act 3883, as amended",
            96,
            "DTI Certificate",
            "business name",
        )

        self.assertEqual(field["validation_status"], "needs_review")
        self.assertLess(field["confidence"], 80)


if __name__ == "__main__":
    unittest.main()
