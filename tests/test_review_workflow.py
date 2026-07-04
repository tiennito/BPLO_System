import unittest
import sys
import types

sys.modules.setdefault("cv2", types.SimpleNamespace())
sys.modules.setdefault("fitz", types.SimpleNamespace())
sys.modules.setdefault("numpy", types.SimpleNamespace())
sys.modules.setdefault("pytesseract", types.SimpleNamespace(pytesseract=types.SimpleNamespace(tesseract_cmd="")))
fake_image = types.SimpleNamespace()
fake_image_ops = types.SimpleNamespace()
sys.modules.setdefault("PIL", types.SimpleNamespace(Image=fake_image, ImageOps=fake_image_ops))
sys.modules.setdefault("PIL.Image", fake_image)
sys.modules.setdefault("PIL.ImageOps", fake_image_ops)

from main import AppHandler, department_key_from_name


class WorkflowComputationTests(unittest.TestCase):
    def setUp(self):
        self.handler = object.__new__(AppHandler)

    def test_department_key_normalizes_office_names(self):
        self.assertEqual(department_key_from_name("Health or Sanitary Office"), "health_or_sanitary")

    def test_money_rounds_amounts(self):
        self.assertEqual(self.handler.money("12.345"), 12.35)

    def test_assessment_payload_computes_final_amount(self):
        config = {"actor": {"id": "staff-id"}}
        payload = {
            "assessmentId": "assessment-id",
            "applicationId": "application-id",
            "feeName": "Mayor's Permit Fee",
            "quantity": "2",
            "rate": "150",
            "penalty": "25",
            "discount": "10",
        }

        item = self.handler.build_assessment_item_payload(config, payload)

        self.assertEqual(item["amount"], 300)
        self.assertEqual(item["final_amount"], 315)
        self.assertEqual(item["updated_by"], "staff-id")

    def test_assessment_payload_uses_manual_final_amount_when_present(self):
        config = {"actor": {"id": "staff-id"}}
        payload = {
            "assessmentId": "assessment-id",
            "applicationId": "application-id",
            "feeName": "Fire Safety Inspection Fee",
            "quantity": "1",
            "rate": "500",
            "finalAmount": "450",
        }

        item = self.handler.build_assessment_item_payload(config, payload)

        self.assertEqual(item["amount"], 500)
        self.assertEqual(item["final_amount"], 450)


if __name__ == "__main__":
    unittest.main()
