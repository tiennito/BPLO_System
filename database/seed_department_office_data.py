from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import json
import os


BASE_DIR = Path(__file__).resolve().parents[1]
ENV_FILE = BASE_DIR / ".env"

DEPARTMENTS = [
    {
        "key": "engineering",
        "name": "Engineering Office",
        "email": "engineering@test.com",
        "first_name": "Engineering",
        "last_name": "Office",
    },
    {
        "key": "health",
        "name": "Health/Sanitary Office",
        "email": "health@test.com",
        "first_name": "Health",
        "last_name": "Office",
    },
    {
        "key": "zoning",
        "name": "Zoning/MPDC Office",
        "email": "zoning@test.com",
        "first_name": "Zoning",
        "last_name": "Office",
    },
    {
        "key": "fire",
        "name": "Fire Office",
        "email": "fire@test.com",
        "first_name": "Fire",
        "last_name": "Office",
    },
]

SAMPLE_APPLICATIONS = [
    ("BPLO-ENG-001", "Victoria Hardware Supply", "engineering", "Pending"),
    ("BPLO-ENG-002", "Laguna Builders Depot", "engineering", "Approved"),
    ("BPLO-ENG-003", "Mabuhay Welding Shop", "engineering", "Rejected"),
    ("BPLO-HEA-001", "Healthy Bites Canteen", "health", "Pending"),
    ("BPLO-HEA-002", "San Isidro Water Refilling", "health", "Approved"),
    ("BPLO-ZON-001", "Greenfield Trading", "zoning", "Pending"),
    ("BPLO-ZON-002", "Town Center Pharmacy", "zoning", "Rejected"),
    ("BPLO-FIR-001", "Spark Safe Electronics", "fire", "Pending"),
    ("BPLO-FIR-002", "Victoria Events Hall", "fire", "Approved"),
]


def load_env():
    if not ENV_FILE.exists():
        return

    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def request_json(path, method="GET", payload=None, query=None, prefer=None):
    supabase_url = os.environ["SUPABASE_URL"].rstrip("/")
    service_key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    url = f"{supabase_url}{path}"
    if query:
        url = f"{url}?{query}"

    data = None
    headers = {
        "apikey": service_key,
        "Authorization": f"Bearer {service_key}",
    }
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if prefer:
        headers["Prefer"] = prefer

    request = Request(url, data=data, method=method, headers=headers)
    with urlopen(request, timeout=20) as response:
        body = response.read().decode("utf-8")
        return json.loads(body) if body else None


def find_auth_user(email):
    query = urlencode({"page": 1, "per_page": 1000})
    payload = request_json(f"/auth/v1/admin/users?{query}")
    for user in payload.get("users", []):
        if (user.get("email") or "").lower() == email.lower():
            return user
    return None


def create_or_update_department_user(department):
    existing = find_auth_user(department["email"])
    payload = {
        "email": department["email"],
        "password": "Test123456",
        "email_confirm": True,
        "user_metadata": {
            "first_name": department["first_name"],
            "last_name": department["last_name"],
        },
        "app_metadata": {
            "role": "department",
            "department_key": department["key"],
            "department_name": department["name"],
        },
    }

    if existing:
        request_json(
            f"/auth/v1/admin/users/{existing['id']}",
            method="PUT",
            payload=payload,
        )
        return existing["id"]

    created = request_json("/auth/v1/admin/users", method="POST", payload=payload)
    return created["id"]


def upsert_departments():
    rows = [
        {
            "name": department["name"],
            "description": f"Department office account group for {department['name']}.",
            "status": "Active",
        }
        for department in DEPARTMENTS
    ]
    request_json(
        "/rest/v1/departments",
        method="POST",
        payload=rows,
        query=urlencode({"on_conflict": "name"}),
        prefer="resolution=merge-duplicates,return=minimal",
    )


def upsert_application(reference_number, business_name, status):
    payload = {
        "user_id": "00000000-0000-0000-0000-000000000000",
        "permit_id": reference_number,
        "business_name": business_name,
        "status": "Submitted",
        "progress": "Department review",
        "submitted_id": reference_number.replace("BPLO-", "SUB-"),
        "application_type": "New Application",
        "application_payload": {
            "firstName": "Sample",
            "lastName": "Applicant",
            "email": "sample.applicant@test.com",
            "contactNumber": "+63 900 000 0000",
            "homeAddress": "Victoria, Laguna",
            "businessName": business_name,
            "businessAddress": "Victoria, Laguna",
            "businessEmail": "business@test.com",
            "businessMobile": "+63 911 111 1111",
        },
    }
    rows = request_json(
        "/rest/v1/business_permit_applications",
        method="POST",
        payload=payload,
        query=urlencode({"on_conflict": "permit_id"}),
        prefer="resolution=merge-duplicates,return=representation",
    )
    application = rows[0]
    return application["id"], status


def seed_department_records(user_ids):
    for reference_number, business_name, department_key, status in SAMPLE_APPLICATIONS:
        application_id, evaluation_status = upsert_application(reference_number, business_name, status)
        request_json(
            "/rest/v1/department_application_assignments",
            method="POST",
            payload={
                "application_id": application_id,
                "department_key": department_key,
                "evaluation_status": evaluation_status,
                "verification_status": "Verified" if evaluation_status == "Approved" else "Pending",
                "remarks": "Sample rejected record for testing." if evaluation_status == "Rejected" else "",
                "assigned_by": user_ids.get(department_key),
            },
            query=urlencode({"on_conflict": "application_id,department_key"}),
            prefer="resolution=merge-duplicates,return=minimal",
        )

    for department in DEPARTMENTS:
        request_json(
            "/rest/v1/department_requirement_checklists",
            method="POST",
            payload={
                "department_key": department["key"],
                "title": f"{department['name']} clearance checklist",
                "description": "Seeded sample checklist item.",
                "is_required": True,
                "status": "Active",
                "created_by": user_ids.get(department["key"]),
            },
            prefer="return=minimal",
        )


def main():
    load_env()
    required = ["SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY"]
    missing = [key for key in required if not os.getenv(key)]
    if missing:
        raise SystemExit(f"Missing required .env values: {', '.join(missing)}")

    upsert_departments()
    user_ids = {}
    for department in DEPARTMENTS:
        user_ids[department["key"]] = create_or_update_department_user(department)

    seed_department_records(user_ids)
    print("Department office users and sample records seeded successfully.")


if __name__ == "__main__":
    try:
        main()
    except HTTPError as error:
        print(error.read().decode("utf-8"))
        raise
