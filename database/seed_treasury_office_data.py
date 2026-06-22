from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import json
import os


BASE_DIR = Path(__file__).resolve().parents[1]
ENV_FILE = BASE_DIR / ".env"

TREASURY_USER = {
    "email": "treasury@test.com",
    "password": "Test123456",
    "first_name": "Treasury",
    "last_name": "Cashier",
}

SAMPLE_RECORDS = [
    ("OR-2024-00861", "APP-2024-00125", "Juan Dela Cruz", "JDC Trading", 25000, "Assessment", "Paid", "Assessment"),
    ("OR-2024-00860", "APP-2024-00124", "Maria Santos", "Santos Gen. Merch.", 12500, "SOA Generation", "Paid", "SOA Generation"),
    ("OR-2024-00859", "APP-2024-00123", "Pedro Reyes", "Reyes Construction", 48750, "Payment", "Paid", "Payment"),
    ("OR-2024-00858", "APP-2024-00122", "Ana Francisco", "AF Food Services", 8900, "Payment", "Pending", "Payment"),
    ("OR-2024-00857", "APP-2024-00120", "Liza Mendoza", "Mendoza Supplies", 15300, "Official Receipt", "Ready", "Official Receipt"),
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
    headers = {"apikey": service_key, "Authorization": f"Bearer {service_key}"}
    data = None
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
    payload = request_json(f"/auth/v1/admin/users?{urlencode({'page': 1, 'per_page': 1000})}")
    for user in payload.get("users", []):
        if (user.get("email") or "").lower() == email.lower():
            return user
    return None


def create_or_update_treasury_user():
    existing = find_auth_user(TREASURY_USER["email"])
    payload = {
        "email": TREASURY_USER["email"],
        "password": TREASURY_USER["password"],
        "email_confirm": True,
        "user_metadata": {
            "first_name": TREASURY_USER["first_name"],
            "last_name": TREASURY_USER["last_name"],
        },
        "app_metadata": {
            "role": "treasury",
            "office": "Treasury Office",
        },
    }
    if existing:
        request_json(f"/auth/v1/admin/users/{existing['id']}", method="PUT", payload=payload)
        return existing["id"]
    created = request_json("/auth/v1/admin/users", method="POST", payload=payload)
    return created["id"]


def seed_records(user_id):
    for or_no, application_no, applicant, business_name, amount, step, status, current_step in SAMPLE_RECORDS:
        request_json(
            "/rest/v1/treasury_records",
            method="POST",
            payload={
                "or_no": or_no,
                "application_no": application_no,
                "applicant": applicant,
                "business_name": business_name,
                "amount": amount,
                "step": step,
                "status": status,
                "current_step": current_step,
                "record_type": "payment",
                "created_by": user_id,
            },
            prefer="return=minimal",
        )


def main():
    load_env()
    missing = [key for key in ["SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY"] if not os.getenv(key)]
    if missing:
        raise SystemExit(f"Missing required .env values: {', '.join(missing)}")
    user_id = create_or_update_treasury_user()
    seed_records(user_id)
    print("Treasury office test account and sample records seeded successfully.")


if __name__ == "__main__":
    try:
        main()
    except HTTPError as error:
        print(error.read().decode("utf-8"))
        raise
