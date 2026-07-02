#!/usr/bin/env python3
"""
Import official BPLO business classifications from the source DOCX.

The script extracts only "Business Type" table columns, normalizes values for
duplicate detection/search, and upserts active records into Supabase through the
project's existing REST API configuration.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from xml.etree import ElementTree


DOCX_NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
DEFAULT_DOCX = Path(r"C:\Users\tienito\Downloads\TYPE-OF-BUSINESS-with-source (1).docx")
ALLOWED_PARENT_CATEGORIES = {
    "Broker / Agent",
    "Contractor",
    "Cooperative",
    "Dropshipper",
    "Government",
    "Jobber",
    "Lessor",
    "Manufacturer",
    "Retailer",
    "Service Provider",
    "Wholesaler",
    "Wholesaler (Distributor)",
}


@dataclass
class ClassificationRow:
    code: str
    name: str
    normalized_name: str
    parent_category: str = ""
    description: str = ""
    sort_order: int = 0
    source_names: list[str] = field(default_factory=list)
    source_rows: list[dict[str, Any]] = field(default_factory=list)


def load_env(env_path: Path) -> None:
    if not env_path.exists():
        return

    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def clean_text(value: str) -> str:
    value = unicodedata.normalize("NFKC", value or "")
    replacements = {
        "\u2013": "-",
        "\u2014": "-",
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u00a0": " ",
    }
    for old, new in replacements.items():
        value = value.replace(old, new)
    return re.sub(r"\s+", " ", value).strip()


def normalize_parent_category(value: str) -> str:
    value = re.sub(r"\s*\([^)]*\)", "", clean_text(value)).strip()
    if value.lower() == "retailer service":
        return "Retailer"
    for category in ALLOWED_PARENT_CATEGORIES:
        if value.lower() == category.lower():
            return category
    return value


def normalize_classification_name(value: str) -> str:
    value = clean_text(value).upper()
    value = re.sub(r"\s*/\s*", " / ", value)
    value = re.sub(r"\s*-\s*", " - ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def normalize_classification_key(value: str) -> str:
    value = normalize_classification_name(value)
    value = value.replace("&", " AND ")
    value = re.sub(r"\bBAKE\s+SHOP\b", "BAKESHOP", value)
    value = re.sub(r"\bPHONE\s+CARDS\b", "PHONECARDS", value)
    value = re.sub(r"\bSMALL\s+LOT\b", "SMALLLOT", value)
    value = re.sub(r"[^A-Z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def is_valid_business_type(value: str) -> bool:
    if not value:
        return False
    lowered = value.lower()
    invalid_fragments = [
        "business type",
        "classified under",
        "no dedicated entries",
        "see retailer section",
    ]
    if any(fragment in lowered for fragment in invalid_fragments):
        return False
    if value.startswith("(") and value.endswith(")"):
        return False
    if re.fullmatch(r"[\d#.\-\s]+", value):
        return False
    return True


def docx_cell_text(cell: ElementTree.Element) -> str:
    return clean_text("".join(text.text or "" for text in cell.findall(".//w:t", DOCX_NS)))


def extract_business_classifications(docx_path: Path) -> tuple[list[ClassificationRow], list[dict[str, Any]]]:
    if not docx_path.exists():
        raise FileNotFoundError(f"Source DOCX not found: {docx_path}")

    with zipfile.ZipFile(docx_path) as archive:
        document_xml = archive.read("word/document.xml")

    root = ElementTree.fromstring(document_xml)
    classifications_by_key: dict[str, ClassificationRow] = {}
    rejected: list[dict[str, Any]] = []
    extracted_count = 0

    for table_index, table in enumerate(root.findall(".//w:tbl", DOCX_NS)):
        rows = table.findall("./w:tr", DOCX_NS)
        if not rows:
            continue

        header = [docx_cell_text(cell) for cell in rows[0].findall("./w:tc", DOCX_NS)]
        lowered_header = [item.lower() for item in header]
        if "business type" not in lowered_header:
            continue

        business_index = lowered_header.index("business type")
        parent_index = next(
            (index for index, label in enumerate(lowered_header) if "parent category" in label),
            None,
        )

        for row_index, row in enumerate(rows[1:], start=1):
            cells = [docx_cell_text(cell) for cell in row.findall("./w:tc", DOCX_NS)]
            raw_name = cells[business_index] if business_index < len(cells) else ""
            official_name = normalize_classification_name(raw_name)
            item_number = cells[0] if cells else ""

            if not is_valid_business_type(official_name):
                if raw_name:
                    rejected.append(
                        {
                            "table": table_index,
                            "row": row_index,
                            "value": raw_name,
                            "reason": "not a business classification",
                        }
                    )
                continue

            extracted_count += 1
            normalized_name = normalize_classification_key(official_name)
            if not normalized_name:
                rejected.append(
                    {
                        "table": table_index,
                        "row": row_index,
                        "value": raw_name,
                        "reason": "empty normalized name",
                    }
                )
                continue

            parent_category = ""
            if parent_index is not None and parent_index < len(cells):
                parent_category = normalize_parent_category(cells[parent_index])

            source_row = {
                "table": table_index,
                "row": row_index,
                "itemNumber": item_number,
                "businessType": raw_name,
                "parentCategory": parent_category,
            }

            existing = classifications_by_key.get(normalized_name)
            if existing:
                if official_name not in existing.source_names:
                    existing.source_names.append(official_name)
                existing.source_rows.append(source_row)
                if not existing.parent_category and parent_category:
                    existing.parent_category = parent_category
                continue

            sort_order = int(item_number) if item_number.isdigit() else extracted_count
            classifications_by_key[normalized_name] = ClassificationRow(
                code=f"BIZ-{sort_order:04d}",
                name=official_name,
                normalized_name=normalized_name,
                parent_category=parent_category,
                sort_order=sort_order,
                source_names=[official_name],
                source_rows=[source_row],
            )

    classifications = sorted(classifications_by_key.values(), key=lambda item: (item.sort_order, item.name))
    for index, item in enumerate(classifications, start=1):
        item.sort_order = index
        item.code = f"BIZ-{index:04d}"
        if len(item.source_names) > 1:
            item.description = "Source variants: " + "; ".join(item.source_names)

    return classifications, rejected


def rest_request(
    supabase_url: str,
    service_key: str,
    table: str,
    query: dict[str, Any] | None = None,
    method: str = "GET",
    payload: Any | None = None,
    prefer: str | None = None,
) -> Any:
    query_string = urllib.parse.urlencode(query or {})
    url = f"{supabase_url.rstrip('/')}/rest/v1/{table}"
    if query_string:
        url = f"{url}?{query_string}"

    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {
        "apikey": service_key,
        "Authorization": f"Bearer {service_key}",
        "Content-Type": "application/json",
    }
    if prefer:
        headers["Prefer"] = prefer

    request = urllib.request.Request(url, data=data, method=method, headers=headers)
    with urllib.request.urlopen(request, timeout=30) as response:
        body = response.read().decode("utf-8")
        return json.loads(body or "[]")


def import_classifications(classifications: list[ClassificationRow], dry_run: bool = False) -> dict[str, int]:
    supabase_url = os.getenv("SUPABASE_URL", "").strip()
    service_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    if not supabase_url or not service_key:
        raise RuntimeError("Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY before importing.")

    existing_rows = rest_request(
        supabase_url,
        service_key,
        "business_classifications",
        {
            "select": "id,code,name,normalized_name,parent_category,description,is_active,sort_order,source_metadata",
            "limit": "10000",
        },
    )
    existing_by_normalized = {row.get("normalized_name"): row for row in existing_rows or []}
    existing_codes = {row.get("code") for row in existing_rows or [] if row.get("code")}

    summary = {
        "inserted": 0,
        "updated": 0,
        "duplicatesSkipped": 0,
    }

    for item in classifications:
        payload = {
            "code": item.code,
            "name": item.name,
            "normalized_name": item.normalized_name,
            "parent_category": item.parent_category or None,
            "description": item.description or None,
            "is_active": True,
            "sort_order": item.sort_order,
            "source_metadata": {
                "sourceNames": item.source_names,
                "sourceRows": item.source_rows,
            },
        }
        existing = existing_by_normalized.get(item.normalized_name)
        if existing:
            patch_payload = {
                key: value
                for key, value in payload.items()
                if key in {"code", "name", "parent_category", "description", "sort_order", "source_metadata"}
                and existing.get(key) != value
            }
            if patch_payload:
                if not dry_run:
                    rest_request(
                        supabase_url,
                        service_key,
                        "business_classifications",
                        {"id": f"eq.{existing.get('id')}"},
                        method="PATCH",
                        payload=patch_payload,
                        prefer="return=minimal",
                    )
                summary["updated"] += 1
            else:
                summary["duplicatesSkipped"] += 1
            continue

        insert_payload = dict(payload)
        if insert_payload.get("code") in existing_codes:
            insert_payload["code"] = None

        if not dry_run:
            try:
                rest_request(
                    supabase_url,
                    service_key,
                    "business_classifications",
                    method="POST",
                    payload=insert_payload,
                    prefer="return=minimal",
                )
            except urllib.error.HTTPError as error:
                if error.code != 409:
                    raise

                refreshed_rows = rest_request(
                    supabase_url,
                    service_key,
                    "business_classifications",
                    {
                        "select": "id,normalized_name",
                        "normalized_name": f"eq.{item.normalized_name}",
                        "limit": 1,
                    },
                )
                if refreshed_rows:
                    summary["duplicatesSkipped"] += 1
                    continue

                insert_payload["code"] = None
                rest_request(
                    supabase_url,
                    service_key,
                    "business_classifications",
                    method="POST",
                    payload=insert_payload,
                    prefer="return=minimal",
                )
        summary["inserted"] += 1
        if insert_payload.get("code"):
            existing_codes.add(insert_payload["code"])

    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Import BPLO business classifications from DOCX.")
    parser.add_argument("--source", type=Path, default=DEFAULT_DOCX, help="Path to TYPE-OF-BUSINESS DOCX")
    parser.add_argument("--env", type=Path, default=Path(".env"), help="Path to .env")
    parser.add_argument("--dry-run", action="store_true", help="Extract and summarize without writing to Supabase")
    parser.add_argument("--json", action="store_true", help="Print summary as JSON")
    args = parser.parse_args()

    load_env(args.env)
    classifications, rejected = extract_business_classifications(args.source)
    summary = {
        "totalRecordsExtracted": sum(len(item.source_rows) for item in classifications) + len(rejected),
        "uniqueClassifications": len(classifications),
        "invalidRecords": len(rejected),
        "rejectedRows": rejected,
    }

    if args.dry_run:
        summary.update({"inserted": 0, "updated": 0, "duplicatesSkipped": 0})
    else:
        summary.update(import_classifications(classifications, dry_run=False))

    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        print(f"Total records extracted: {summary['totalRecordsExtracted']}")
        print(f"Unique classifications: {summary['uniqueClassifications']}")
        print(f"Inserted: {summary['inserted']}")
        print(f"Updated: {summary['updated']}")
        print(f"Duplicates skipped: {summary['duplicatesSkipped']}")
        print(f"Invalid records: {summary['invalidRecords']}")
        for row in rejected[:20]:
            print(f"Rejected table {row['table']} row {row['row']}: {row['value']} ({row['reason']})")

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, FileNotFoundError, zipfile.BadZipFile, urllib.error.HTTPError) as error:
        print(f"Import failed: {error}", file=sys.stderr)
        raise SystemExit(1)
