import tempfile
import unittest
import zipfile
from pathlib import Path

from scripts.import_business_classifications import (
    extract_business_classifications,
    normalize_classification_key,
    normalize_classification_name,
)


WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def make_docx(rows):
    table_rows = []
    for row in rows:
        cells = "".join(
            f"<w:tc><w:p><w:r><w:t>{value}</w:t></w:r></w:p></w:tc>"
            for value in row
        )
        table_rows.append(f"<w:tr>{cells}</w:tr>")

    xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="{WORD_NS}">
  <w:body><w:tbl>{''.join(table_rows)}</w:tbl></w:body>
</w:document>"""

    temp_dir = tempfile.TemporaryDirectory()
    path = Path(temp_dir.name) / "source.docx"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", xml)
    return temp_dir, path


class BusinessClassificationImportTests(unittest.TestCase):
    def test_normalizes_spacing_and_punctuation(self):
        self.assertEqual(
            normalize_classification_name("  bakery/ bake shop  "),
            "BAKERY / BAKE SHOP",
        )

    def test_merges_obvious_duplicates(self):
        self.assertEqual(
            normalize_classification_key("BAKERY / BAKESHOP"),
            normalize_classification_key("BAKERY/BAKE SHOP"),
        )

    def test_extracts_only_business_type_column(self):
        temp_dir, path = make_docx(
            [
                ["#", "Business Type", "Parent Category", "Gross Sales"],
                ["1", "COMPUTER REPAIR", "Service Provider", "100,000"],
                ["2", "COMPUTER REPAIR", "Service Provider", "200,000"],
                ["3", "See Retailer section", "Retailer", "See Retailer section"],
            ]
        )
        self.addCleanup(temp_dir.cleanup)

        classifications, rejected = extract_business_classifications(path)

        self.assertEqual(len(classifications), 1)
        self.assertEqual(classifications[0].name, "COMPUTER REPAIR")
        self.assertEqual(classifications[0].parent_category, "Service Provider")
        self.assertEqual(len(rejected), 1)


if __name__ == "__main__":
    unittest.main()
