const SUPABASE_URL = window.APP_CONFIG?.supabaseUrl || "";
const SUPABASE_ANON_KEY =
  window.APP_CONFIG?.supabaseAnonKey || window.APP_CONFIG?.supabasePublishableKey || "";

const fields = {
  fullName: document.querySelector('[data-field="fullName"]'),
  email: document.querySelector('[data-field="email"]'),
  contact: document.querySelector('[data-field="contact"]'),
  address: document.querySelector('[data-field="address"]'),
};
const profileName = document.querySelector("[data-profile-name]");
const profileToggle = document.querySelector("[data-profile-toggle]");
const profileDropdown = document.querySelector("[data-profile-dropdown]");
const logoutButton = document.querySelector("[data-logout]");
const permitSummaryCard = document.querySelector(".permit-summary-card");
const permitTypeBadge = document.querySelector(".permit-summary-card header span");
const permitStartButton = document.querySelector(".start-application-button");
const businessFormShell = document.querySelector("[data-business-form-shell]");
const businessStepPanels = {
  form: document.querySelector('[data-business-step-panel="form"]'),
};
const businessContinueButton = document.querySelector("[data-business-continue]");
const finishApplicationButton = document.querySelector("[data-finish-application]");
const reviewStrip = document.querySelector("[data-review-strip]");
const recentPermitsTableBody = document.querySelector(".permits-table-wrap tbody");

const PERMIT_STORAGE_KEY = "bplo_recent_business_permits";

let supabaseClient = null;
let currentUser = null;

function initSupabase() {
  if (!window.supabase?.createClient) {
    return null;
  }

  if (!supabaseClient) {
    supabaseClient = window.supabase.createClient(SUPABASE_URL, SUPABASE_ANON_KEY);
  }

  return supabaseClient;
}

function setField(name, value) {
  if (fields[name]) {
    fields[name].value = value || "";
  }
}

function formatFullName(profile, user) {
  const metadata = user?.user_metadata || {};
  const firstName = profile?.first_name_raw || metadata.first_name || "";
  const middleName = profile?.middle_name || metadata.middle_name || "";
  const lastName = profile?.last_name || metadata.last_name || "";
  const suffix = profile?.suffix || metadata.suffix || "";

  return [firstName, middleName, lastName, suffix].filter(Boolean).join(" ");
}

function formatAddress(profile, user) {
  const metadata = user?.user_metadata || {};
  const parts = [
    profile?.address_street || metadata.address_street,
    profile?.address_barangay || metadata.address_barangay,
    profile?.address_city || metadata.address_city,
    profile?.address_province || metadata.address_province,
    profile?.postal_code || metadata.postal_code,
  ];

  return parts.filter(Boolean).join(", ");
}

function syncBusinessPermitType() {
  if (!permitSummaryCard) {
    return;
  }

  const params = new URLSearchParams(window.location.search);
  const applicationType = params.get("type");

  if (!applicationType) {
    return;
  }

  const isRenewal = applicationType === "renewal";

  if (permitTypeBadge) {
    permitTypeBadge.textContent = isRenewal ? "Renewal" : "New";
  }

  if (permitStartButton) {
    permitStartButton.querySelector("span").textContent = isRenewal ? "Start Renewal" : "Start Application";
  }
}

function readStoredPermits() {
  try {
    const raw = window.localStorage.getItem(PERMIT_STORAGE_KEY);
    const permits = raw ? JSON.parse(raw) : [];
    return Array.isArray(permits) ? permits : [];
  } catch {
    return [];
  }
}

function writeStoredPermits(permits) {
  try {
    window.localStorage.setItem(PERMIT_STORAGE_KEY, JSON.stringify(permits));
  } catch {
    // Ignore storage failures in restricted browser modes.
  }
}

function getBusinessFieldValue(name) {
  if (!businessFormShell) {
    return "";
  }

  const control = businessFormShell.querySelector(`[data-business-field="${name}"]`);
  if (!control) {
    return "";
  }

  if (control instanceof HTMLInputElement) {
    if (control.type === "checkbox") {
      return control.checked ? control.value : "";
    }

    if (control.type === "radio") {
      const selected = businessFormShell.querySelector(
        `[data-business-field="${name}"]:checked`
      );
      return selected instanceof HTMLInputElement ? selected.value : "";
    }

    return control.value.trim();
  }

  if (control instanceof HTMLTextAreaElement || control instanceof HTMLSelectElement) {
    return control.value.trim();
  }

  return "";
}

function setReviewValue(name, value) {
  const target = document.querySelector(`[data-review-value="${name}"]`);
  if (target) {
    target.textContent = value || "Not filled in yet";
  }
}

function collectBusinessApplication() {
  const checkedBusinessTypes = businessFormShell
    ? [...businessFormShell.querySelectorAll('[data-business-field="type_of_business"]:checked')].map(
        (input) => input.value
      )
    : [];

  return {
    applicationDate: getBusinessFieldValue("application_date"),
    registrationNumber: getBusinessFieldValue("registration_number"),
    modeOfPayment: getBusinessFieldValue("mode_of_payment"),
    lastName: getBusinessFieldValue("last_name"),
    firstName: getBusinessFieldValue("first_name"),
    middleName: getBusinessFieldValue("middle_name"),
    email: getBusinessFieldValue("email"),
    contactNumber: getBusinessFieldValue("contact_number"),
    homeAddress: getBusinessFieldValue("home_address"),
    businessName: getBusinessFieldValue("business_name"),
    tradeName: getBusinessFieldValue("trade_name"),
    businessTypes: checkedBusinessTypes,
    businessClassification: getBusinessFieldValue("business_classification"),
    tin: getBusinessFieldValue("tin"),
    businessAddress: getBusinessFieldValue("business_address"),
    locationDetail: getBusinessFieldValue("location_detail"),
    businessBarangay: getBusinessFieldValue("business_barangay"),
    businessPremise: getBusinessFieldValue("business_premise"),
    businessTelephone: getBusinessFieldValue("business_telephone"),
    businessMobile: getBusinessFieldValue("business_mobile"),
    businessEmail: getBusinessFieldValue("business_email"),
    ownerContactNumber: getBusinessFieldValue("owner_contact_number"),
    emergencyContactPerson: getBusinessFieldValue("emergency_contact_person"),
    emergencyContact: getBusinessFieldValue("emergency_contact"),
    businessArea: getBusinessFieldValue("business_area"),
    employeesTotal: getBusinessFieldValue("employees_total"),
    employeesLgu: getBusinessFieldValue("employees_lgu"),
    businessActivity: getBusinessFieldValue("business_activity"),
    capitalization: getBusinessFieldValue("capitalization"),
    goodsValue: getBusinessFieldValue("goods_value"),
    taxIncentive: getBusinessFieldValue("tax_incentive"),
    taxIncentiveEntity: getBusinessFieldValue("tax_incentive_entity"),
  };
}

function updateReviewCopy(application) {
  setReviewValue("business_name", application.businessName);
  setReviewValue("business_address", application.businessAddress || application.homeAddress);
  setReviewValue("business_mobile", application.businessMobile || application.contactNumber);
  setReviewValue("business_email", application.businessEmail || application.email);
  setReviewValue("mode_of_payment", application.modeOfPayment);
}

function setBusinessStep(step) {
  if (!businessStepPanels.form) {
    return;
  }

  const isReview = step === "review";
  businessStepPanels.form.classList.remove("is-hidden");
  reviewStrip?.classList.toggle("is-hidden", !isReview);

  const stepperSteps = document.querySelectorAll(".progress-stepper--business .progress-step");
  const firstStep = stepperSteps[0];
  const secondStep = stepperSteps[1];
  const thirdStep = stepperSteps[2];

  firstStep?.classList.add("progress-step--done");
  firstStep?.classList.remove("progress-step--current");
  secondStep?.classList.toggle("progress-step--current", !isReview);
  secondStep?.classList.toggle("progress-step--done", isReview);
  thirdStep?.classList.toggle("progress-step--current", isReview);
  thirdStep?.classList.toggle("progress-step--done", false);

  if (isReview) {
    reviewStrip?.scrollIntoView({ behavior: "smooth", block: "start" });
  }
}

function createPermitRecord(application, userId = "") {
  const createdAt = new Date();
  const permitSuffix = `${createdAt.getTime()}`.slice(-6);
  const submittedSuffix = `${createdAt.getTime()}`.slice(-8);

  return {
    user_id: userId,
    permit_id: `BPLO-${permitSuffix}`,
    business_name: application.businessName || "Untitled Business",
    status: "Submitted",
    progress: "Review complete",
    submitted_id: submittedSuffix,
    application_type: "New Application",
    application_payload: application,
    created_at: createdAt.toISOString(),
  };
}

async function renderRecentPermits() {
  if (!recentPermitsTableBody) {
    return;
  }

  const client = initSupabase();
  let permits = [];

  if (client && currentUser) {
    try {
      const { data, error } = await client
        .from("business_permit_applications")
        .select("*")
        .eq("user_id", currentUser.id)
        .order("created_at", { ascending: false })
        .limit(10);

      if (!error && Array.isArray(data) && data.length) {
        permits = data;
      }
    } catch {
      permits = [];
    }
  }

  if (!permits.length) {
    permits = readStoredPermits();
  }

  recentPermitsTableBody.innerHTML = "";

  if (!permits.length) {
    recentPermitsTableBody.innerHTML =
      '<tr><td colspan="6" class="empty-state">No recent business permits yet.</td></tr>';
    return;
  }

  permits.forEach((permit) => {
    const row = document.createElement("tr");
    row.innerHTML = `
      <td>${permit.permit_id || permit.permitId || "-"}</td>
      <td>${permit.business_name || permit.businessName || "-"}</td>
      <td>${permit.status || "Submitted"}</td>
      <td>${permit.progress || "Review complete"}</td>
      <td>${permit.submitted_id || permit.submittedId || "-"}</td>
      <td><a href="/applicant/business-information" style="color: var(--green); text-decoration: underline;">View</a></td>
    `;
    recentPermitsTableBody.appendChild(row);
  });
}

function handleBusinessContinue() {
  if (!businessFormShell) {
    return;
  }

  const application = collectBusinessApplication();
  updateReviewCopy(application);
  setBusinessStep("review");
}

async function handleFinishApplication() {
  const application = collectBusinessApplication();
  const record = createPermitRecord(application, currentUser?.id || "");
  const permits = readStoredPermits();

  permits.unshift(record);
  writeStoredPermits(permits.slice(0, 10));

  const client = initSupabase();
  if (client && currentUser) {
    try {
      await client.from("business_permit_applications").insert(record);
    } catch {
      // Keep the local record even if the database table is not ready yet.
    }
  }

  window.location.href = "/applicant/dashboard";
}

async function loadApplicantDashboard() {
  const client = initSupabase();
  if (!client) {
    window.location.href = "/login";
    return;
  }

  const {
    data: { user },
    error: userError,
  } = await client.auth.getUser();

  if (userError || !user) {
    window.location.href = "/login";
    return;
  }

  currentUser = user;

  const { data: profile } = await client
    .from("applicants")
    .select("*")
    .eq("user_id", user.id)
    .maybeSingle();

  const fullName = formatFullName(profile, user) || "Applicant";
  setField("fullName", fullName);
  setField("email", profile?.email || user.email || "");
  setField("contact", profile?.contact_number || user.user_metadata?.contact_number || "");
  setField("address", formatAddress(profile, user));

  if (profileName) {
    profileName.textContent = fullName;
  }

  await renderRecentPermits();
}

profileToggle?.addEventListener("click", () => {
  profileDropdown?.classList.toggle("is-open");
});

document.addEventListener("click", (event) => {
  if (!profileDropdown?.classList.contains("is-open")) {
    return;
  }

  const target = event.target;
  if (target instanceof Node && !profileDropdown.contains(target) && !profileToggle?.contains(target)) {
    profileDropdown.classList.remove("is-open");
  }
});

logoutButton?.addEventListener("click", async () => {
  const client = initSupabase();
  await client?.auth.signOut();
  window.location.href = "/login";
});

businessContinueButton?.addEventListener("click", handleBusinessContinue);
finishApplicationButton?.addEventListener("click", () => {
  void handleFinishApplication();
});

window.addEventListener("DOMContentLoaded", () => {
  window.lucide?.createIcons();
  syncBusinessPermitType();
  loadApplicantDashboard();
});
