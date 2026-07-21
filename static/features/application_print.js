const PRINT_SUPABASE_URL = window.APP_CONFIG?.supabaseUrl || "";
const PRINT_SUPABASE_KEY = window.APP_CONFIG?.supabaseAnonKey || window.APP_CONFIG?.supabasePublishableKey || "";
const printButton = document.querySelector("[data-print-application]");
const backButton = document.querySelector("[data-back-to-application]");
const retryButton = document.querySelector("[data-retry-print-preview]");
const loadingState = document.querySelector("[data-print-loading]");
const errorState = document.querySelector("[data-print-error]");
const errorMessage = document.querySelector("[data-print-error-message]");
const printDocument = document.querySelector("[data-print-document]");
const printSections = document.querySelector("[data-print-sections]");
const printStatus = document.querySelector("[data-print-status]");
let printClient = null;
let previewViewerRole = "applicant";

const PRINT_SECTIONS = [
  {
    title: "A. Application Details",
    fields: [
      ["Date of Application", "date_of_application"],
      ["Application Type", "_application_type"],
      ["Permit Type", "_permit_name"],
      ["DTI/SEC/CDA Registration No.", "dti_registration_no"],
      ["Mode of Payment", "mode_of_payment"],
      ["Application / Reference No.", "_reference_number"],
      ["Application Status", "_status"],
      ["Date Submitted", "_submitted_at"],
    ],
  },
  {
    title: "B. Name of Taxpayer / Applicant",
    fields: [
      ["Last Name", "last_name"],
      ["First Name", "first_name"],
      ["Middle Name", "middle_name"],
      ["Suffix", "suffix"],
      ["Civil Status", "_civil_status"],
      ["Citizenship", "_citizenship"],
      ["Gender / Sex", "gender"],
      ["Home Address", "home_address"],
      ["Registered Contact Number", "registered_contact_number"],
      ["Registered Email Address", "registered_email"],
      ["Government ID / ID Details", "government_id"],
      ["TIN (Tax Identification Number)", "tin"],
    ],
  },
  {
    title: "C. Business Information",
    fields: [
      ["Business Name", "business_name"],
      ["Trade Name / Franchise", "trade_name"],
      ["Type of Business", "business_type"],
      ["Business Classification", "business_classification"],
      ["Business Activity", "business_activity"],
      ["Business Address", "business_address"],
      ["Unit / Street / Lot / Location", "location_detail"],
      ["Business Barangay", "business_barangay"],
      ["Municipality / City", "_municipality_city"],
      ["Province", "_province"],
      ["Postal Code", "_postal_code"],
      ["Business Premise", "business_premise"],
      ["Business Telephone", "business_telephone"],
      ["Business Mobile Number", "business_mobile"],
      ["Business Email", "business_email"],
      ["Owner/Proprietor Contact Number", "owner_contact_number"],
    ],
  },
  {
    title: "D. Business Operation Information",
    fields: [
      ["Capital Investment", "capital_investment"],
      ["Gross Sales / Goods Value", "goods_value"],
      ["Business Area (in sq. m.)", "business_area"],
      ["Total No. of Employees", "employees_total"],
      ["No. of Employees Residing within LGU", "employees_lgu"],
      ["Date Issued", "date_issued"],
      ["Tax Incentive", "tax_incentive"],
      ["Tax Incentive Issuing Entity", "tax_incentive_entity"],
    ],
  },
  {
    title: "E. Emergency Contact / Representative Information",
    fields: [
      ["Emergency Contact Person", "emergency_contact_person"],
      ["Emergency Contact Number / Email", "emergency_contact"],
    ],
  },
];

function esc(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function displayValue(value) {
  if (Array.isArray(value)) return value.length ? value.join(", ") : "N/A";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  const text = String(value ?? "").trim();
  return text || "N/A";
}

function formatDate(value, includeTime = false) {
  if (!value) return "N/A";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return displayValue(value);
  return new Intl.DateTimeFormat("en-PH", includeTime
    ? { year: "numeric", month: "long", day: "numeric", hour: "numeric", minute: "2-digit" }
    : { year: "numeric", month: "long", day: "numeric" }).format(date);
}

function client() {
  if (!printClient && window.supabase?.createClient && PRINT_SUPABASE_URL && PRINT_SUPABASE_KEY) {
    printClient = window.supabase.createClient(PRINT_SUPABASE_URL, PRINT_SUPABASE_KEY);
  }
  return printClient;
}

async function accessToken() {
  const supabase = client();
  if (!supabase) throw new Error("The print preview is not configured.");
  const { data, error } = await supabase.auth.getSession();
  if (error || !data.session?.access_token) throw new Error("Please sign in before printing this application.");
  return data.session.access_token;
}

function printContext(payload) {
  const application = payload.application || {};
  const profile = payload.applicantProfile || {};
  const info = application.businessInfo || {};
  return {
    ...info,
    date_of_application: info.date_of_application || info.application_date,
    dti_registration_no: info.dti_registration_no || info.registration_number,
    registered_contact_number: info.registered_contact_number || info.contact_number,
    registered_email: info.registered_email || info.email,
    business_type: info.business_type || info.business_types,
    capital_investment: info.capital_investment || info.capitalization,
    _application_type: String(application.applicationType || "New").replaceAll("_", " "),
    _permit_name: application.permitName || "Business Permit",
    _reference_number: application.referenceNumber || "Not yet assigned",
    _status: application.status || "Draft",
    _submitted_at: application.submittedAt ? formatDate(application.submittedAt) : "N/A",
    _civil_status: profile.civilStatus,
    _citizenship: profile.citizenship,
    _municipality_city: profile.municipalityCity,
    _province: profile.province,
    _postal_code: profile.postalCode,
  };
}

function renderSection(section, context) {
  return `
    <section class="print-section">
      <h3>${esc(section.title)}</h3>
      <dl class="print-field-grid">
        ${section.fields.map(([label, key]) => `
          <div class="print-field ${["home_address", "business_address"].includes(key) ? "print-field--wide" : ""}">
            <dt>${esc(label)}</dt>
            <dd>${esc(displayValue(context[key]))}</dd>
          </div>
        `).join("")}
      </dl>
    </section>
  `;
}

function renderPrintDocument(payload) {
  const application = payload.application || {};
  const lgu = payload.lgu || {};
  const context = printContext(payload);
  previewViewerRole = payload.viewerRole || "applicant";
  document.querySelector("[data-lgu-name]").textContent = lgu.name || window.APP_CONFIG?.lguName || "Local Government Unit";
  document.querySelector("[data-lgu-province]").textContent = lgu.province || window.APP_CONFIG?.lguProvince || "";
  document.querySelector("[data-lgu-office]").textContent = lgu.officeName || window.APP_CONFIG?.licensingOffice || "Business Permits and Licensing Office";
  document.querySelector("[data-permit-code]").textContent = application.permitCode || "BPLO 01";
  document.querySelector("[data-application-year]").textContent = `Application Year ${application.applicationYear || new Date().getFullYear()}`;
  document.querySelector("[data-reference-number]").textContent = application.referenceNumber || "Not yet assigned";
  document.querySelector("[data-application-status]").textContent = application.status || "Draft";
  document.querySelector("[data-applicant-printed-name]").textContent = displayValue(infoOwnerName(application.businessInfo || {}));
  document.querySelector("[data-print-generated-at]").textContent = `Prepared ${formatDate(new Date().toISOString(), true)}`;
  document.querySelector("[data-draft-watermark]").hidden = String(application.status || "Draft").toLowerCase() !== "draft";
  printSections.innerHTML = PRINT_SECTIONS.map((section) => renderSection(section, context)).join("");
  loadingState.hidden = true;
  errorState.hidden = true;
  printDocument.hidden = false;
  printButton.disabled = false;
  printStatus.textContent = "Your application form is ready for printing.";
}

function infoOwnerName(info) {
  return [info.first_name, info.middle_name, info.last_name, info.suffix].filter(Boolean).join(" ") || info.owner_name || "N/A";
}

async function loadPrintPreview() {
  const params = new URLSearchParams(window.location.search);
  const applicationId = params.get("applicationId") || "";
  const printSession = params.get("printSession") || "";
  loadingState.hidden = false;
  errorState.hidden = true;
  printDocument.hidden = true;
  printButton.disabled = true;
  printStatus.textContent = "Preparing application form...";
  if (!applicationId) {
    showError("The application form could not be found.");
    return;
  }
  try {
    const token = await accessToken();
    const auditSessionKey = printSession ? `bplo-print-audited:${applicationId}:${printSession}` : "";
    const hasLoggedThisPreview = auditSessionKey && window.sessionStorage.getItem(auditSessionKey) === "1";
    const response = await fetch(`/api/applications/${encodeURIComponent(applicationId)}/print`, {
      headers: {
        Authorization: `Bearer ${token}`,
        "X-Print-Session": printSession,
        "X-Print-Audit": hasLoggedThisPreview ? "0" : "1",
      },
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.error || "The latest application data could not be retrieved.");
    if (auditSessionKey) window.sessionStorage.setItem(auditSessionKey, "1");
    renderPrintDocument(payload);
  } catch (error) {
    showError(error.message || "The latest application data could not be retrieved.");
  }
}

function showError(message) {
  loadingState.hidden = true;
  printDocument.hidden = true;
  errorState.hidden = false;
  errorMessage.textContent = message;
  printStatus.textContent = "Print preview unavailable.";
  printButton.disabled = true;
  window.lucide?.createIcons();
}

printButton?.addEventListener("click", () => window.print());
backButton?.addEventListener("click", () => {
  if (["super_admin", "bplo_admin"].includes(previewViewerRole)) {
    window.history.back();
    return;
  }
  const applicationId = new URLSearchParams(window.location.search).get("applicationId") || "";
  window.location.href = `/applicant/business-information?applicationId=${encodeURIComponent(applicationId)}`;
});
retryButton?.addEventListener("click", loadPrintPreview);
window.addEventListener("DOMContentLoaded", () => {
  window.lucide?.createIcons();
  void loadPrintPreview();
});
