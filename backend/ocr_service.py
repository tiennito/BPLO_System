from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from urllib.parse import parse_qs, quote, urlencode, urlsplit
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
import json
import os
import re
import tempfile
import uuid

from .config import BASE_DIR, STATIC_DIR, ENV_FILE, HOST, PORT, PAGE_ROUTES
from .utils import (
    dashboard_path_for_role,
    department_key_from_name,
    normalize_business_classification_key,
    normalize_business_classification_value,
    normalize_role,
    profile_status,
    slugify_key,
    utc_now_iso,
)


class OCRServiceMixin:
    FIELD_LABELS = {
        "business_name": [
            r"business\s*name",
            r"name\s*of\s*business",
        ],
        "trade_name": [
            r"trade\s*name",
            r"tradename",
        ],
        "tin": [
            r"tin",
            r"tax\s*identification\s*number",
            r"taxpayer\s*identification\s*number",
        ],
        "business_address": [
            r"business\s*address",
            r"business\s*location",
            r"business\s*office\s*address",
        ],
    }

    BAD_BUSINESS_NAME_WORDS = [
        "registration",
        "issued",
        "issue",
        "republic",
        "philippines",
        "secretary",
        "certificate",
        "department",
        "trade and industry",
        "department of trade",
        "pursuant",
        "valid",
        "business name registration",
        "this is to certify",
        "le ma",
        "cristina",
        "roque",
    ]

    def prepare_ocr_image_variants(self, image):
        import cv2
        import numpy as np
        from PIL import Image, ImageOps

        image = ImageOps.exif_transpose(image).convert("RGB")
        rgb = np.array(image)
        gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)

        height, width = gray.shape[:2]
        scale = max(1.0, min(4.0, 1800 / max(width, height)))
        if scale > 1:
            gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)

        denoised = cv2.fastNlMeansDenoising(gray, None, 18, 7, 21)
        clahe = cv2.createCLAHE(clipLimit=2.8, tileGridSize=(8, 8)).apply(denoised)
        blur = cv2.GaussianBlur(clahe, (3, 3), 0)
        _, otsu = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        adaptive = cv2.adaptiveThreshold(
            blur,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            31,
            11,
        )

        variants = [
            Image.fromarray(gray),
            Image.fromarray(clahe),
            Image.fromarray(otsu),
            Image.fromarray(adaptive),
            Image.fromarray(cv2.bitwise_not(otsu)),
        ]

        enlarged_variants = []
        for variant in variants:
            enlarged_variants.append(variant)
            enlarged_variants.append(variant.resize((variant.width * 2, variant.height * 2), Image.Resampling.LANCZOS))

        return enlarged_variants

    def ocr_image_to_text(self, image):
        import pytesseract

        configs = [
            "--oem 3 --psm 6",
            "--oem 3 --psm 11",
            "--oem 3 --psm 7",
        ]
        texts = []
        seen = set()

        for variant in self.prepare_ocr_image_variants(image):
            for config in configs:
                try:
                    text = pytesseract.image_to_string(variant, config=config)
                except Exception:
                    continue
                text = self.clean_ocr_text(text)
                key = self.flatten_ocr_text(text).lower()
                if text and key not in seen:
                    seen.add(key)
                    texts.append(text)

        return "\n".join(texts)

    def extract_text_from_file(self, file_name, file_bytes):
        import fitz
        from PIL import Image

        file_name_lower = (file_name or "").lower()

        if file_name_lower.endswith(".pdf"):
            document = fitz.open(stream=file_bytes, filetype="pdf")
            extracted_pages = []

            for page in document:
                pix = page.get_pixmap(dpi=260)
                image_bytes = pix.tobytes("png")
                image = Image.open(BytesIO(image_bytes))
                text = self.ocr_image_to_text(image)
                extracted_pages.append(text)

            return "\n".join(extracted_pages)

        image = Image.open(BytesIO(file_bytes))
        return self.ocr_image_to_text(image)

    def clean_ocr_text(self, text):
        text = (text or "").replace("\r", "\n")
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n+", "\n", text)
        return text.strip()

    def flatten_ocr_text(self, text):
        return re.sub(r"\s+", " ", text or "").strip()

    def get_all_label_patterns(self):
        labels = []
        for patterns in self.FIELD_LABELS.values():
            labels.extend(patterns)
        return labels

    def build_all_labels_regex(self):
        return "|".join(f"(?:{pattern})" for pattern in self.get_all_label_patterns())

    def normalize_ocr_text(self, raw_text):
        text = self.clean_ocr_text(raw_text)
        for label_pattern in self.get_all_label_patterns():
            text = re.sub(
                rf"(?i)\b({label_pattern})\b\s*[:\-]?",
                r"\n\1: ",
                text,
            )
        text = re.sub(r"\n+", "\n", text)
        return text.strip()

    def find_first_match(self, patterns, text):
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(1).strip(" :,-")
        return ""

    def clean_extracted_value(self, value):
        if not value:
            return None

        value = str(value).strip()
        value = re.sub(r"\s+", " ", value)
        value = value.replace("|", "")
        value = value.replace("\u201c", "")
        value = value.replace("\u201d", "")
        value = value.strip(" :;-")
        return value.strip() or None

    def clean_extracted_ocr_value(self, value):
        return self.clean_extracted_value(re.sub(r"[:|_]+", " ", str(value or ""))) or ""

    def extract_value_by_label(self, text, label_patterns):
        all_labels_regex = self.build_all_labels_regex()
        current_label_regex = "|".join(f"(?:{pattern})" for pattern in label_patterns)
        pattern = rf"""
            (?:^|\n)\s*
            (?:{current_label_regex})
            \s*[:\-]?\s*
            (.*?)
            (?=
                \n\s*(?:{all_labels_regex})\s*[:\-]?
                |
                $
            )
        """
        match = re.search(pattern, text, re.IGNORECASE | re.DOTALL | re.VERBOSE)
        if not match:
            return None
        return self.clean_extracted_value(match.group(1))

    def contains_known_label(self, value):
        if not value:
            return False
        all_labels_regex = self.build_all_labels_regex()
        return re.search(rf"\b(?:{all_labels_regex})\b", str(value), re.IGNORECASE) is not None

    def is_valid_business_name(self, value):
        if not value:
            return False
        value = str(value).strip()
        if len(value) > 100:
            return False
        if self.contains_known_label(value):
            return False

        bad_words = [
            "certificate",
            "registration",
            "republic",
            "philippines",
            "department",
            "secretary",
            "issued",
            "valid",
        ]
        lower = value.lower()
        return not any(word in lower for word in bad_words)

    def clean_tin(self, value):
        if not value:
            return None

        match = re.search(r"\b\d{3}[-\s]?\d{3}[-\s]?\d{3}(?:[-\s]?\d{3})?\b", str(value))
        if not match:
            return None

        digits = re.sub(r"\D", "", match.group(0))
        if len(digits) == 9:
            return f"{digits[:3]}-{digits[3:6]}-{digits[6:9]}"
        if len(digits) == 12:
            return f"{digits[:3]}-{digits[3:6]}-{digits[6:9]}-{digits[9:12]}"
        return None

    def is_valid_address(self, value):
        if not value:
            return False

        value = str(value).strip()
        if len(value) < 5 or len(value) > 250:
            return False
        if self.contains_known_label(value):
            return False
        return True

    def validate_business_info_fields(self, fields):
        validated = {}

        business_name = self.clean_extracted_value(fields.get("business_name"))
        trade_name = self.clean_extracted_value(fields.get("trade_name"))
        tin = self.clean_tin(fields.get("tin"))
        business_address = self.clean_extracted_value(fields.get("business_address"))

        if self.is_valid_business_name(business_name):
            validated["business_name"] = business_name.upper()

        if trade_name and len(trade_name) <= 100 and not self.contains_known_label(trade_name):
            validated["trade_name"] = trade_name.upper()

        if tin:
            validated["tin"] = tin

        if self.is_valid_address(business_address):
            validated["business_address"] = business_address.upper()

        return validated

    def score_field(self, field_name, value):
        if not value:
            return 0.0
        if self.contains_known_label(value):
            return 0.2
        if field_name == "tin":
            return 0.95 if self.clean_tin(value) else 0.3
        if field_name == "business_name":
            return 0.9 if self.is_valid_business_name(value) else 0.3
        if field_name == "business_address":
            return 0.85 if self.is_valid_address(value) else 0.3
        return 0.8

    def build_confidence(self, fields):
        return {
            field_name: self.score_field(field_name, value)
            for field_name, value in fields.items()
        }

    def parse_business_info_document(self, raw_text):
        text = self.normalize_ocr_text(raw_text)
        fields = {
            "business_name": self.extract_value_by_label(text, self.FIELD_LABELS["business_name"]),
            "trade_name": self.extract_value_by_label(text, self.FIELD_LABELS["trade_name"]),
            "tin": self.extract_value_by_label(text, self.FIELD_LABELS["tin"]),
            "business_address": self.extract_value_by_label(text, self.FIELD_LABELS["business_address"]),
        }
        fields = self.validate_business_info_fields(fields)
        if not fields:
            return {}

        confidence = self.build_confidence(fields)
        fields["field_confidence"] = confidence
        fields["confidence"] = confidence
        fields["confidence_score"] = round(sum(confidence.values()) / len(confidence), 2)
        fields["parser_version"] = "business_info_v1"
        return fields

    def field_confidence_value(self, value, confidence):
        return {
            "value": value,
            "confidence": confidence,
        }

    def extract_labeled_ocr_value(self, labels, lines, flattened_text, stop_labels=None):
        stop_labels = stop_labels or [
            "Name of Owner",
            "Name of Business",
            "Business Name",
            "Business Address",
            "TIN",
            "Date Issued",
            "TOTAL SALES",
            "Total Sales",
        ]
        stop_pattern = "|".join(re.escape(label) for label in stop_labels)

        for label_pattern, confidence in labels:
            same_line_pattern = re.compile(rf"{label_pattern}\s*[:\-|]?\s*(.+)", re.IGNORECASE)
            for index, line in enumerate(lines):
                match = same_line_pattern.search(line)
                if match:
                    value = self.clean_extracted_ocr_value(match.group(1))
                    if value:
                        return value, confidence
                    if index + 1 < len(lines):
                        next_value = self.clean_extracted_ocr_value(lines[index + 1])
                        if next_value:
                            return next_value, max(confidence - 8, 70)

            block_match = re.search(
                rf"{label_pattern}\s*[:\-|]?\s*(.+?)(?:\s+(?:{stop_pattern})\b|$)",
                flattened_text,
                re.IGNORECASE,
            )
            if block_match:
                value = self.clean_extracted_ocr_value(block_match.group(1))
                if value:
                    return value, max(confidence - 5, 70)

        return "", 0

    def is_bad_business_name_candidate(self, value):
        if not value:
            return True

        value = re.sub(r"\s+", " ", str(value)).strip()
        value_lower = value.lower()
        if len(value_lower) < 3 or len(value_lower) > 80:
            return True

        if not re.search(r"[a-z]", value_lower):
            return True

        if re.search(r"\b(?:no|number)\.?\s*\d", value_lower):
            return True

        if re.fullmatch(r"(?:no\.?\s*)?[a-z0-9\-]{4,}", value_lower) and sum(character.isalpha() for character in value_lower) <= 2:
            return True

        return any(bad_word in value_lower for bad_word in self.BAD_BUSINESS_NAME_WORDS)

    def normalize_business_name(self, value):
        if not value:
            return ""

        value = re.sub(r"\s+", " ", value).strip(" :,-")
        stop_words = [
            "Owner",
            "Proprietor",
            "Registrant",
            "Business Address",
            "Certificate",
            "Registration",
            "Date",
            "Issued",
            "This is to certify",
        ]
        for stop in stop_words:
            value = re.sub(rf"\b{re.escape(stop)}\b.*", "", value, flags=re.IGNORECASE).strip()

        value = value.upper()
        value = re.sub(r"(?<=[A-Z])0(?=[A-Z])", "O", value)
        value = re.sub(r"(?<=[A-Z])1(?=[A-Z])", "I", value)
        value = re.sub(r"(?<=[A-Z])5(?=[A-Z])", "S", value)
        value = re.sub(r"(?<=[A-Z])8(?=[A-Z])", "B", value)
        return value

    def is_valid_gross_sales_business_name(self, value):
        if self.is_bad_business_name_candidate(value):
            return False

        value_lower = str(value or "").lower()
        address_words = ["street", "st.", "brgy", "barangay", "laguna", "province", "city", "municipality"]
        label_words = ["name of business", "business name", "business address", "name of owner", "tin"]
        if any(word in value_lower for word in address_words + label_words):
            return False

        return True

    def is_valid_business_address_candidate(self, value):
        value = str(value or "").strip()
        if len(value) < 8 or len(value) > 180:
            return False
        if self.contains_known_label(value):
            return False
        lowered = value.lower()
        location_words = ["street", "st.", "brgy", "barangay", "victoria", "laguna", "city", "municipality", "province", "road", "ave"]
        return any(word in lowered for word in location_words)

    def is_valid_tin_candidate(self, value):
        return bool(re.fullmatch(r"\d{3}-?\d{3}-?\d{3}(?:-?\d{3})?", str(value or "").strip()))

    def is_valid_sales_candidate(self, value):
        normalized = str(value or "").replace(",", "").strip()
        return bool(re.fullmatch(r"\d+(?:\.\d{1,2})?", normalized))

    def parse_gross_sales_certificate_fields(self, raw_text):
        text = self.clean_ocr_text(raw_text)
        flattened_text = self.flatten_ocr_text(text)
        lines = [line.strip() for line in text.split("\n") if line.strip()]
        fields = {}
        confidence = {}

        owner_name, owner_confidence = self.extract_labeled_ocr_value(
            [
                (r"Name\s+of\s+Owner", 95),
                (r"Owner\s+Name", 88),
                (r"\bOwner\b", 78),
            ],
            lines,
            flattened_text,
        )
        if owner_name and len(owner_name) <= 90:
            owner_name = self.normalize_business_name(owner_name)
            fields["owner_name"] = owner_name
            fields.update(self.split_owner_name(owner_name))
            confidence["owner_name"] = owner_confidence

        business_name, business_confidence = self.extract_labeled_ocr_value(
            [
                (r"Name\s+of\s+Business", 96),
                (r"Business\s+Name", 94),
                (r"Name\s+Business", 88),
                (r"Name\s+of\s+Buslness", 86),
                (r"Name\s+of\s+Busmess", 86),
            ],
            lines,
            flattened_text,
        )
        business_name = self.normalize_business_name(business_name)
        if business_name and self.is_valid_gross_sales_business_name(business_name):
            fields["business_name"] = business_name
            fields["businessName"] = business_name
            fields["business_name_confidence"] = "high" if business_confidence >= 90 else "medium"
            confidence["business_name"] = business_confidence
            confidence["businessName"] = business_confidence
        else:
            fields["business_name_confidence"] = "low"

        business_address, address_confidence = self.extract_labeled_ocr_value(
            [
                (r"Business\s+Address", 95),
                (r"Address\s+of\s+Business", 88),
                (r"\bAddress\b", 76),
            ],
            lines,
            flattened_text,
        )
        if business_address and self.is_valid_business_address_candidate(business_address):
            fields["business_address"] = business_address
            fields["businessAddress"] = business_address
            confidence["business_address"] = address_confidence
            confidence["businessAddress"] = address_confidence

        tin, tin_confidence = self.extract_labeled_ocr_value(
            [
                (r"\bTIN\b", 96),
                (r"Tax\s+Identification\s+Number", 90),
            ],
            lines,
            flattened_text,
        )
        tin_match = re.search(r"\d{3}-?\d{3}-?\d{3}(?:-?\d{3})?", tin or flattened_text)
        if tin_match:
            tin_value = tin_match.group(0)
            if self.is_valid_tin_candidate(tin_value):
                fields["tin"] = tin_value
                confidence["tin"] = tin_confidence or 80

        date_issued, date_confidence = self.extract_labeled_ocr_value(
            [
                (r"Date\s+Issued", 95),
                (r"Issued\s+Date", 88),
                (r"Date\s+of\s+Issue", 86),
            ],
            lines,
            flattened_text,
        )
        if date_issued:
            fields["date_issued"] = date_issued
            fields["dateIssued"] = date_issued
            confidence["date_issued"] = date_confidence
            confidence["dateIssued"] = date_confidence

        gross_sales, sales_confidence = self.extract_labeled_ocr_value(
            [
                (r"TOTAL\s+SALES", 96),
                (r"Total\s+Sales", 96),
                (r"Gross\s+Sales", 92),
                (r"Sales", 74),
            ],
            lines,
            flattened_text,
        )
        sales_match = re.search(r"\d[\d,]*(?:\.\d{1,2})?", gross_sales or "")
        if not sales_match:
            sales_match = re.search(r"(?:TOTAL\s+SALES|Total\s+Sales|Gross\s+Sales)\D+(\d[\d,]*(?:\.\d{1,2})?)", flattened_text, re.IGNORECASE)
            sales_value = sales_match.group(1) if sales_match else ""
        else:
            sales_value = sales_match.group(0)
        sales_value = sales_value.replace(",", "")
        if sales_value and self.is_valid_sales_candidate(sales_value):
            fields["gross_sales"] = sales_value
            fields["grossSales"] = sales_value
            fields["goods_value"] = sales_value
            confidence["gross_sales"] = sales_confidence or 86
            confidence["grossSales"] = sales_confidence or 86
            confidence["goods_value"] = sales_confidence or 86

        fields["field_confidence"] = confidence
        if confidence:
            fields["confidence_score"] = round(sum(confidence.values()) / len(confidence), 2)

        return fields

    def parse_dti_fields(self, raw_text):
        text = self.clean_ocr_text(raw_text)
        flattened_text = self.flatten_ocr_text(text)
        fields = {}
        lines = [line.strip() for line in text.split("\n") if line.strip()]
        business_name_candidates = []
        owner_name = ""

        for index, line in enumerate(lines):
            if re.search(r"certificate\s+issued\s+to|issued\s+to", line, re.IGNORECASE):
                for next_line in lines[index + 1 : index + 4]:
                    candidate_owner = self.normalize_business_name(next_line)
                    if candidate_owner and len(candidate_owner) <= 80 and not self.is_bad_business_name_candidate(candidate_owner):
                        owner_name = candidate_owner
                        break
                break

        owner_match = re.search(
            r"(?:owner|proprietor|registrant)\s*[:\-]?\s*(.+)",
            text,
            re.IGNORECASE,
        )
        if owner_match:
            matched_owner = self.normalize_business_name(owner_match.group(1))
            if matched_owner and len(matched_owner) <= 80:
                owner_name = matched_owner

        if owner_name:
            fields["owner_name"] = owner_name
            fields.update(self.split_owner_name(owner_name))

        for line in lines:
            match = re.search(r"business\s*name\s*[:\-]?\s*(.+)", line, re.IGNORECASE)
            if match:
                candidate = self.normalize_business_name(match.group(1))
                if candidate != owner_name and not self.is_bad_business_name_candidate(candidate):
                    business_name_candidates.append((candidate, "high"))

        for index, line in enumerate(lines):
            if not re.search(r"certif(?:y|ies)\s+that", line, re.IGNORECASE):
                continue

            for next_line in lines[index + 1 : index + 6]:
                candidate = self.normalize_business_name(next_line)
                if not candidate or candidate == owner_name or self.is_bad_business_name_candidate(candidate):
                    continue
                if re.search(r"^\([^)]+\)$", candidate):
                    continue
                if re.search(r"\b(REGION|CALABARZON|LAGUNA|PROVINCE|CITY|MUNICIPALITY|BARANGAY|BRGY)\b", candidate, re.IGNORECASE):
                    continue
                business_name_candidates.append((candidate, "high"))
                break

        sentence_match = re.search(
            r"certif(?:y|ies)\s+that\s+(.+?)(?:\s+\([^)]+\))?\s+(?:is\s+a\s+business\s+name\s+registered|is|has been)\s+(?:registered|granted)?",
            flattened_text,
            re.IGNORECASE,
        )
        if sentence_match:
            candidate = self.normalize_business_name(sentence_match.group(1))
            candidate = re.sub(r"\s+\([^)]+\).*$", "", candidate).strip()
            candidate = re.sub(r"\b(REGION|CALABARZON|LAGUNA|PROVINCE|CITY|MUNICIPALITY|BARANGAY|BRGY)\b.*", "", candidate, flags=re.IGNORECASE).strip()
            if candidate != owner_name and not self.is_bad_business_name_candidate(candidate):
                business_name_candidates.append((candidate, "high"))

        before_owner_section = True
        for line in lines:
            if re.search(r"certificate\s+issued\s+to|issued\s+to|valid\s+from|in\s+testimony", line, re.IGNORECASE):
                before_owner_section = False
            if not before_owner_section:
                continue

            candidate = self.normalize_business_name(line)
            if candidate == owner_name or self.is_bad_business_name_candidate(candidate):
                continue

            uppercase_ratio = sum(1 for character in candidate if character.isupper()) / max(len(candidate), 1)
            if uppercase_ratio > 0.5 and len(candidate.split()) >= 2:
                business_name_candidates.append((candidate, "medium"))

        if business_name_candidates:
            business_name, confidence = sorted(business_name_candidates, key=lambda item: (item[1] != "high", len(item[0])))[0]
            fields["business_name"] = business_name
            fields["business_name_confidence"] = confidence
        else:
            fields["business_name_confidence"] = "low"

        registration_number = self.find_first_match(
            [
                r"(?:certificate\s+no\.?|registration\s+no\.?|business\s+name\s+no\.?|dti\s+registration\s+no\.?)\s*[:\-]?\s*([A-Z0-9\-]+)",
            ],
            flattened_text,
        )
        if registration_number:
            fields["registration_number"] = registration_number
            fields["dti_registration_no"] = registration_number

        business_address = self.find_first_match(
            [
                r"(?:Business Address|Business Location|Address)\s*[:\-]?\s*(.+?)(?: Owner| Proprietor| Registrant| Registration| Certificate|$)",
            ],
            flattened_text,
        )
        if business_address:
            fields["business_address"] = re.sub(r"\s+", " ", business_address).strip(" :,-")

        registration_date = self.find_first_match(
            [
                r"(?:Registration Date|Date Registered|Date of Registration|Issued on)\s*[:\-]?\s*([A-Za-z0-9 ,/\-]+?)(?: Business| Owner| Address|$)",
            ],
            flattened_text,
        )
        if registration_date:
            fields["registration_date"] = registration_date

        business_type = self.find_first_match(
            [
                r"\b(SINGLE|SOLE PROPRIETORSHIP|PARTNERSHIP|CORPORATION|COOPERATIVE)\b",
            ],
            flattened_text,
        )
        if business_type:
            fields["type_of_business"] = "SINGLE" if business_type.upper() == "SOLE PROPRIETORSHIP" else business_type.upper()
            fields["business_type"] = fields["type_of_business"]

        return fields

    def normalize_handwritten_ocr_line(self, line):
        line = str(line or "")
        replacements = {
            "8USINESS": "BUSINESS",
            "BVSINESS": "BUSINESS",
            "BUSlNESS": "BUSINESS",
            "BUS1NESS": "BUSINESS",
            "BUSl NESS": "BUSINESS",
            "B U S I N E S S": "BUSINESS",
            "NANE": "NAME",
            "MAME": "NAME",
            "NAHE": "NAME",
        }
        normalized = line.upper()
        for wrong, right in replacements.items():
            normalized = normalized.replace(wrong, right)
        normalized = re.sub(r"\s+", " ", normalized)
        normalized = re.sub(r"\bBUSI\s+NESS\b", "BUSINESS", normalized)
        normalized = re.sub(r"\bBUS\s*INESS\b", "BUSINESS", normalized)
        return normalized.strip()

    def parse_freeform_business_fields(self, raw_text):
        text = self.clean_ocr_text(raw_text)
        flattened_text = self.flatten_ocr_text(text)
        lines = [line.strip() for line in text.split("\n") if line.strip()]
        candidates = []

        label_patterns = [
            r"(?:business|bus1ness|busi\s*ness|bvsiness|8usiness)\s*(?:name|nane|mame|nahe)",
            r"(?:name\s+of\s+business|name\s+business)",
            r"(?:trade\s+name)",
        ]

        for line in lines:
            normalized_line = self.normalize_handwritten_ocr_line(line)
            for label_pattern in label_patterns:
                match = re.search(rf"{label_pattern}\s*[:\-|]?\s*(.+)", normalized_line, re.IGNORECASE)
                if match:
                    candidate = self.normalize_business_name(match.group(1))
                    if candidate and not self.is_bad_business_name_candidate(candidate):
                        candidates.append(candidate)

        normalized_flattened = self.normalize_handwritten_ocr_line(flattened_text)
        for label_pattern in label_patterns:
            match = re.search(
                rf"{label_pattern}\s*[:\-|]?\s*(.+?)(?:\s+(?:OWNER|PROPRIETOR|ADDRESS|TIN|REGISTRATION|PERMIT|DATE)\b|$)",
                normalized_flattened,
                re.IGNORECASE,
            )
            if match:
                candidate = self.normalize_business_name(match.group(1))
                if candidate and not self.is_bad_business_name_candidate(candidate):
                    candidates.append(candidate)

        if not candidates:
            return {}

        business_name = sorted(set(candidates), key=lambda value: (-len(value.split()), len(value)))[0]
        return {
            "business_name": business_name,
            "businessName": business_name,
            "business_name_confidence": "medium",
            "field_confidence": {
                "business_name": 78,
                "businessName": 78,
            },
        }

    def split_owner_name(self, owner_name):
        parts = (owner_name or "").strip().split()
        if len(parts) >= 2:
            return {
                "first_name": parts[0],
                "middle_name": " ".join(parts[1:-1]),
                "last_name": parts[-1],
            }
        if parts:
            return {"first_name": parts[0]}
        return {}

    def normalize_extracted_business_fields(self, fields):
        alias_map = {
            "date_of_application": "application_date",
            "dti_registration_no": "registration_number",
            "dti_registration_number": "registration_number",
            "registration_no": "registration_number",
            "certificate_no": "registration_number",
            "owner_first_name": "first_name",
            "owner_middle_name": "middle_name",
            "owner_last_name": "last_name",
            "registered_email": "email",
            "registered_contact_number": "contact_number",
            "business_type": "type_of_business",
            "business_types": "type_of_business",
            "capital_investment": "capitalization",
            "ownerName": "owner_name",
            "businessName": "business_name",
            "businessAddress": "business_address",
            "dateIssued": "date_issued",
            "grossSales": "gross_sales",
            "gross_sales": "goods_value",
        }
        metadata_keys = {"field_confidence", "fieldConfidence", "confidence", "confidence_score", "parser_version"}
        normalized = {}

        for key, value in (fields or {}).items():
            if value in (None, ""):
                continue

            if key in metadata_keys:
                normalized[key] = value
                continue

            normalized_key = alias_map.get(key, key)
            normalized[normalized_key] = value

            if key != normalized_key:
                normalized[key] = value

        owner_name = normalized.get("owner_name")
        if owner_name:
            for key, value in self.split_owner_name(owner_name).items():
                normalized.setdefault(key, value)

        return normalized

    def get_ocr_field_confidence_number(self, fields, key):
        confidence_aliases = {
            "business_name": ["business_name", "businessName"],
            "trade_name": ["trade_name", "tradeName"],
            "tin": ["tin"],
            "business_address": ["business_address", "businessAddress"],
            "goods_value": ["goods_value", "gross_sales", "grossSales"],
            "date_issued": ["date_issued", "dateIssued"],
            "owner_name": ["owner_name", "ownerName"],
        }
        confidence_map = fields.get("field_confidence") or fields.get("fieldConfidence") or fields.get("confidence") or {}
        for confidence_key in confidence_aliases.get(key, [key]):
            if confidence_key in confidence_map:
                value = confidence_map.get(confidence_key)
                if isinstance(value, (int, float)):
                    return float(value) * 100 if 0 < float(value) <= 1 else float(value)
                level = str(value or "").lower()
                if level == "high":
                    return 95
                if level == "medium":
                    return 80
                if level == "low":
                    return 0

        direct_value = fields.get(f"{key}_confidence")
        if isinstance(direct_value, (int, float)):
            return float(direct_value) * 100 if 0 < float(direct_value) <= 1 else float(direct_value)
        level = str(direct_value or "").lower()
        if level == "high":
            return 95
        if level == "medium":
            return 80
        if level == "low":
            return 0

        return 0

    def merge_extracted_ocr_fields(self, merged_fields, incoming_fields):
        incoming = self.normalize_extracted_business_fields(incoming_fields or {})
        confidence_map = merged_fields.setdefault("field_confidence", {})
        incoming_confidence = incoming.get("field_confidence") or {}
        metadata_keys = {"field_confidence", "fieldConfidence", "confidence", "confidence_score", "parser_version"}

        for key, value in incoming.items():
            if key in metadata_keys or key.endswith("_confidence") or value in (None, ""):
                continue

            if key == "business_name":
                owner_name = incoming.get("owner_name") or merged_fields.get("owner_name")
                if owner_name and self.normalize_business_name(value) == self.normalize_business_name(owner_name):
                    continue
                if not self.is_valid_gross_sales_business_name(value):
                    continue
                value = self.normalize_business_name(value)

            if key == "trade_name":
                value = self.clean_extracted_value(value)
                if not value or len(value) > 100 or self.contains_known_label(value):
                    continue

            if key == "tin":
                value = self.clean_tin(value)
                if not value:
                    continue

            if key == "business_address":
                value = self.clean_extracted_value(value)
                if not self.is_valid_address(value):
                    continue

            incoming_score = self.get_ocr_field_confidence_number(incoming, key)
            existing_value = merged_fields.get(key)
            existing_score = self.get_ocr_field_confidence_number(merged_fields, key)

            if not existing_value or incoming_score >= existing_score:
                merged_fields[key] = value
                if incoming_score:
                    confidence_map[key] = incoming_score

        for key, value in incoming_confidence.items():
            normalized_key = self.normalize_extracted_business_fields({key: "x"})
            confidence_key = next((candidate for candidate, candidate_value in normalized_key.items() if candidate_value == "x"), key)
            if isinstance(value, (int, float)) and value > confidence_map.get(confidence_key, 0):
                confidence_map[confidence_key] = value

        for key, value in incoming.items():
            if key.endswith("_confidence") and key not in merged_fields:
                merged_fields[key] = value

        return merged_fields

    def extract_business_fields_from_text(self, raw_text, document_type=""):
        text = self.clean_ocr_text(raw_text)
        flattened_text = self.flatten_ocr_text(text)
        document_type_lower = (document_type or "").lower()
        business_info_fields = self.parse_business_info_document(raw_text)
        freeform_fields = self.parse_freeform_business_fields(raw_text)

        def with_freeform_fallback(fields):
            fields = dict(fields or {})
            if freeform_fields:
                if not fields.get("business_name") and freeform_fields.get("business_name"):
                    fields["business_name"] = freeform_fields["business_name"]
                    fields["businessName"] = freeform_fields["business_name"]
                    fields["business_name_confidence"] = freeform_fields.get("business_name_confidence", "medium")
                confidence = fields.setdefault("field_confidence", {})
                for key, value in (freeform_fields.get("field_confidence") or {}).items():
                    confidence.setdefault(key, value)

            if business_info_fields:
                for key in ("business_name", "trade_name", "tin", "business_address"):
                    if business_info_fields.get(key):
                        fields[key] = business_info_fields[key]
                        if key == "business_name":
                            fields["businessName"] = business_info_fields[key]
                        if key == "business_address":
                            fields["businessAddress"] = business_info_fields[key]

                confidence = fields.setdefault("field_confidence", {})
                for key, value in (business_info_fields.get("field_confidence") or {}).items():
                    confidence[key] = value

                fields["confidence"] = business_info_fields.get("confidence", {})
                fields["confidence_score"] = business_info_fields.get("confidence_score")
                fields["parser_version"] = business_info_fields.get("parser_version", "business_info_v1")
            return self.normalize_extracted_business_fields(fields)

        is_gross_sales_certificate = (
            "gross" in document_type_lower
            or "sales" in document_type_lower
            or "certification" in document_type_lower
            or "name of business" in flattened_text.lower()
            or "total sales" in flattened_text.lower()
        )
        if is_gross_sales_certificate:
            return with_freeform_fallback(self.parse_gross_sales_certificate_fields(raw_text))

        if "dti" in document_type_lower or "business name" in flattened_text.lower():
            return with_freeform_fallback(self.parse_dti_fields(raw_text))

        extracted = {
            "registration_number": self.find_first_match(
                [
                    r"(?:Registration No\.?|Reg\.? No\.?|Certificate No\.?)\s*[:\-]?\s*([A-Z0-9\-]+)",
                    r"(?:DTI No\.?|SEC No\.?|CDA No\.?)\s*[:\-]?\s*([A-Z0-9\-]+)",
                    r"(?:DTI Registration No\.?)\s*[:\-]?\s*([A-Z0-9\-]+)",
                ],
                flattened_text,
            ),
            "trade_name": self.find_first_match(
                [
                    r"(?:Trade Name)\s*[:\-]?\s*([A-Za-z0-9 &.,'\-]+?)(?: Owner| Proprietor| Address| Registration|$)",
                ],
                flattened_text,
            ),
            "tin": self.find_first_match(
                [
                    r"(?:TIN|Tax Identification Number)\s*[:\-]?\s*([0-9\-]+)",
                ],
                flattened_text,
            ),
            "business_address": self.find_first_match(
                [
                    r"(?:Business Address|Business Location|Address)\s*[:\-]?\s*([A-Za-z0-9 #.,'\-]+?)(?: Barangay| Owner| Registration|$)",
                ],
                flattened_text,
            ),
            "registration_date": self.find_first_match(
                [
                    r"(?:Registration Date|Date Registered|Date of Registration)\s*[:\-]?\s*([A-Za-z0-9 ,/\-]+?)(?: Business| Owner| Address|$)",
                ],
                flattened_text,
            ),
            "type_of_business": self.find_first_match(
                [
                    r"\b(SINGLE|SOLE PROPRIETORSHIP|PARTNERSHIP|CORPORATION|COOPERATIVE)\b",
                ],
                flattened_text,
            ),
            "first_name": "",
            "middle_name": "",
            "last_name": "",
            "business_name_confidence": "low",
        }

        business_name = self.find_first_match(
            [
                r"(?:Business Name|Trade Name)\s*[:\-]?\s*([A-Za-z0-9 &.,'\-]+?)(?: Owner| Proprietor| Address| Registration|$)",
            ],
            flattened_text,
        )
        business_name = self.normalize_business_name(business_name)
        if business_name and not self.is_bad_business_name_candidate(business_name):
            extracted["business_name"] = business_name
            extracted["business_name_confidence"] = "medium"

        owner_name = self.find_first_match(
            [
                r"(?:Owner|Proprietor|Registrant|Applicant Name)\s*[:\-]?\s*([A-Za-z .,'\-]+?)(?: Address| Business| Registration|$)",
            ],
            flattened_text,
        )

        if owner_name:
            extracted["owner_name"] = owner_name
            extracted.update(self.split_owner_name(owner_name))

        if extracted.get("type_of_business") == "SOLE PROPRIETORSHIP":
            extracted["type_of_business"] = "SINGLE"

        extracted = {key: value for key, value in extracted.items() if value}
        if extracted.get("registration_number"):
            extracted["dti_registration_no"] = extracted["registration_number"]
        if extracted.get("type_of_business"):
            extracted["business_type"] = extracted["type_of_business"]

        return with_freeform_fallback(extracted)

