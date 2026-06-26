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
const activePermitsGrid = document.querySelector("[data-active-permits]");
const dynamicDocumentGrid = document.querySelector("[data-dynamic-document-grid]");
const checklistPermitName = document.querySelector("[data-checklist-permit-name]");
const checklistPermitCode = document.querySelector("[data-checklist-permit-code]");
const requirementsNextButton = document.querySelector("[data-requirements-next]");
const requirementsStatus = document.querySelector("[data-requirements-status]");

const PERMIT_STORAGE_KEY = "bplo_recent_business_permits";
const SELECTED_PERMIT_KEY = "bplo_selected_permit_id";
const CURRENT_APPLICATION_KEY = "bplo_current_application_id";

let supabaseClient = null;
let currentUser = null;
let activePermitCache = [];
let checklistDocuments = [];
let uploadedDocumentNames = new Map();

function initSupabase() {
  if (!window.supabase?.createClient) {
    return null;
  }

  if (!supabaseClient) {
    supabaseClient = window.supabase.createClient(SUPABASE_URL, SUPABASE_ANON_KEY);
  }

  return supabaseClient;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

async function getApplicantAccessToken() {
  const client = initSupabase();
  if (!client) {
    throw new Error("Supabase is not configured.");
  }

  const { data, error } = await client.auth.getSession();
  if (error || !data.session?.access_token) {
    throw new Error("Please sign in before continuing.");
  }

  return data.session.access_token;
}

async function applicantApi(path, options = {}) {
  const accessToken = await getApplicantAccessToken();
  const response = await fetch(path, {
    ...options,
    headers: {
      Authorization: `Bearer ${accessToken}`,
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
  });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.error || "Unable to complete request.");
  }
  return payload;
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

function renderActivePermits(permits) {
  if (!activePermitsGrid) {
    return;
  }

  if (!permits.length) {
    activePermitsGrid.innerHTML = `
      <article class="permit-summary-card permit-summary-card--empty">
        <h2>No active permits yet</h2>
        <p>Ask the admin to create and activate a permit first.</p>
      </article>
    `;
    return;
  }

  activePermitsGrid.innerHTML = permits
    .map(
      (permit, index) => `
        <section class="permit-summary-card" aria-labelledby="permit-${escapeHtml(permit.id)}">
          <header>
            <h2 id="permit-${escapeHtml(permit.id)}">${escapeHtml(permit.permitName)}</h2>
            <span>${escapeHtml(permit.category || "Permit")}</span>
          </header>
          <p>${escapeHtml(permit.description || "No description provided.")}</p>
          <dl>
            <dt>Code:</dt>
            <dd>${escapeHtml(permit.permitCode)}</dd>
          </dl>
          <button class="start-application-button" type="button" data-start-permit="${escapeHtml(permit.id)}">
            <span>Start Application</span>
            <i data-lucide="arrow-right" aria-hidden="true"></i>
          </button>
        </section>
      `
    )
    .join("");

  window.sessionStorage.setItem(SELECTED_PERMIT_KEY, permits[0].id);
  window.lucide?.createIcons();
}

async function loadActivePermits() {
  if (!activePermitsGrid) {
    return;
  }

  try {
    const payload = await applicantApi("/applicant/api/permits");
    activePermitCache = payload.permits || [];
    renderActivePermits(activePermitCache);
  } catch (error) {
    activePermitsGrid.innerHTML = `
      <article class="permit-summary-card permit-summary-card--empty">
        <h2>Unable to load permits</h2>
        <p>${escapeHtml(error.message)}</p>
      </article>
    `;
  }
}

async function startPermitApplication(permitId) {
  const button = document.querySelector(`[data-start-permit="${CSS.escape(permitId)}"]`);
  try {
    if (button) {
      button.disabled = true;
    }
    const payload = await applicantApi("/applicant/api/applications", {
      method: "POST",
      body: JSON.stringify({ permitId }),
    });
    window.sessionStorage.setItem(SELECTED_PERMIT_KEY, permitId);
    window.sessionStorage.setItem(CURRENT_APPLICATION_KEY, payload.application?.id || "");
    window.location.href = "/applicant/new-application";
  } catch (error) {
    if (button) {
      button.disabled = false;
    }
    alert(error.message || "Unable to start application.");
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

function updateRequirementsNextState() {
  if (!requirementsNextButton) {
    return;
  }

  const missingRequired = checklistDocuments.filter(
    (doc) => doc.requirementType === "Required" && !uploadedDocumentNames.get(doc.id)
  );
  requirementsNextButton.disabled = missingRequired.length > 0;

  if (requirementsStatus) {
    requirementsStatus.textContent = missingRequired.length
      ? `${missingRequired.length} required document(s) still missing.`
      : "All required documents uploaded. You may continue.";
    requirementsStatus.classList.toggle("is-ready", missingRequired.length === 0);
  }
}

function renderChecklistDocuments(documents) {
  if (!dynamicDocumentGrid) {
    return;
  }

  checklistDocuments = documents || [];
  uploadedDocumentNames = new Map();

  if (!checklistDocuments.length) {
    dynamicDocumentGrid.innerHTML = `
      <article class="document-card">
        <p>No document requirements configured for this permit.</p>
      </article>
    `;
    updateRequirementsNextState();
    return;
  }

  dynamicDocumentGrid.innerHTML = checklistDocuments
    .map((doc, index) => {
      const isRequired = doc.requirementType === "Required";
      return `
        <article class="document-card" data-document-card="${escapeHtml(doc.id)}">
          <header>
            <h3>${index + 1}. ${escapeHtml(doc.documentName)}</h3>
            <span class="doc-badge ${isRequired ? "doc-badge--required" : "doc-badge--optional"}">
              ${isRequired ? "Required" : "Optional"}
            </span>
          </header>
          <p class="document-card-description">${escapeHtml(doc.shortDescription || doc.notes || "")}</p>
          <input class="visually-hidden-file" type="file" data-file-input="${escapeHtml(doc.id)}" />
          <button class="upload-slot" type="button" data-upload-trigger="${escapeHtml(doc.id)}">
            <i data-lucide="file-up" aria-hidden="true"></i>
            <span>Upload Document</span>
            <small>${escapeHtml(doc.acceptedFileTypes || "PDF, JPG, PNG")} ${doc.maxFileSize ? ` / ${escapeHtml(doc.maxFileSize)}` : ""}</small>
          </button>
          <div class="upload-result" data-upload-result="${escapeHtml(doc.id)}">No file uploaded</div>
          <button class="remove-upload-button" type="button" data-remove-upload="${escapeHtml(doc.id)}" hidden>Remove file</button>
        </article>
      `;
    })
    .join("");
  window.lucide?.createIcons();
  updateRequirementsNextState();
}

function sanitizeStorageName(fileName) {
  return fileName.replace(/[^a-zA-Z0-9._-]/g, "_");
}

async function uploadApplicationFile(permitDocumentId, file) {
  const client = initSupabase();
  const applicationId = window.sessionStorage.getItem(CURRENT_APPLICATION_KEY);
  if (!client || !currentUser?.id || !applicationId) {
    throw new Error("Application session is not ready. Please start the application again.");
  }

  const storagePath = `${currentUser.id}/${applicationId}/${permitDocumentId}/${Date.now()}-${sanitizeStorageName(file.name)}`;
  const { error } = await client.storage.from("application-documents").upload(storagePath, file, {
    cacheControl: "3600",
    upsert: false,
  });
  if (error) {
    throw new Error(error.message || "Unable to upload file.");
  }

  return storagePath;
}

async function persistApplicationDocument(permitDocumentId, fileName, uploadStatus, fileUrl = "") {
  const applicationId = window.sessionStorage.getItem(CURRENT_APPLICATION_KEY);
  if (!applicationId) {
    return;
  }

  await applicantApi("/applicant/api/application-documents", {
    method: "POST",
    body: JSON.stringify({
      applicationId,
      permitDocumentId,
      fileName,
      fileUrl,
      uploadStatus,
    }),
  });
}

async function handleChecklistFileSelected(input) {
  const permitDocumentId = input.dataset.fileInput || "";
  const file = input.files?.[0];
  if (!permitDocumentId || !file) {
    return;
  }

  const result = document.querySelector(`[data-upload-result="${CSS.escape(permitDocumentId)}"]`);
  const removeButton = document.querySelector(`[data-remove-upload="${CSS.escape(permitDocumentId)}"]`);
  if (result) {
    result.textContent = "Uploading...";
    result.classList.remove("is-uploaded");
  }
  try {
    const fileUrl = await uploadApplicationFile(permitDocumentId, file);
    uploadedDocumentNames.set(permitDocumentId, file.name);
    if (result) {
      result.textContent = file.name;
      result.classList.add("is-uploaded");
    }
    if (removeButton) {
      removeButton.hidden = false;
    }
    updateRequirementsNextState();
    await persistApplicationDocument(permitDocumentId, file.name, "Uploaded", fileUrl);
  } catch (error) {
    uploadedDocumentNames.delete(permitDocumentId);
    if (result) {
      result.textContent = error.message || "Unable to upload file.";
      result.classList.remove("is-uploaded");
    }
    if (removeButton) {
      removeButton.hidden = true;
    }
    if (requirementsStatus) {
      requirementsStatus.textContent = error.message || "Unable to upload file.";
      requirementsStatus.classList.remove("is-ready");
    }
    updateRequirementsNextState();
  }
}

async function removeChecklistUpload(permitDocumentId) {
  uploadedDocumentNames.delete(permitDocumentId);
  const result = document.querySelector(`[data-upload-result="${CSS.escape(permitDocumentId)}"]`);
  const removeButton = document.querySelector(`[data-remove-upload="${CSS.escape(permitDocumentId)}"]`);
  const input = document.querySelector(`[data-file-input="${CSS.escape(permitDocumentId)}"]`);
  if (input) {
    input.value = "";
  }
  if (result) {
    result.textContent = "No file uploaded";
    result.classList.remove("is-uploaded");
  }
  if (removeButton) {
    removeButton.hidden = true;
  }
  updateRequirementsNextState();
  try {
    await persistApplicationDocument(permitDocumentId, "", "Removed");
  } catch {
    // Keep the local UI responsive; the applicant can reselect the file.
  }
}

async function loadRequirementsChecklist() {
  if (!dynamicDocumentGrid) {
    return;
  }

  const permitId = window.sessionStorage.getItem(SELECTED_PERMIT_KEY);
  if (!permitId) {
    dynamicDocumentGrid.innerHTML = `
      <article class="document-card">
        <p>No permit selected. Please start from the permit page.</p>
      </article>
    `;
    return;
  }

  try {
    const payload = await applicantApi(`/applicant/api/permits/${encodeURIComponent(permitId)}`);
    const permit = payload.permit;
    if (checklistPermitName) {
      checklistPermitName.textContent = permit.permitName || "Permit";
    }
    if (checklistPermitCode) {
      checklistPermitCode.textContent = permit.permitCode || "Code";
    }
    renderChecklistDocuments(permit.documents || []);
  } catch (error) {
    dynamicDocumentGrid.innerHTML = `
      <article class="document-card">
        <p>${escapeHtml(error.message || "Unable to load requirements.")}</p>
      </article>
    `;
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

async function recordApplicantAudit(action, details = {}, entityType = "", entityId = "") {
  try {
    const client = initSupabase();
    const { data } = await client.auth.getSession();
    const session = data.session;

    if (!session?.access_token) {
      return;
    }

    await fetch("/api/audit-logs", {
      method: "POST",
      headers: {
        "Authorization": `Bearer ${session.access_token}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        action,
        details,
        entityType,
        entityId,
      }),
    });
  } catch {
    // Audit failures should not block applicant workflows.
  }
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

  await recordApplicantAudit(
    "business_permit_submitted",
    { permitId: record.permit_id, businessName: record.business_name },
    "business_permit_application",
    record.permit_id
  );
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

  const profilePayload = await applicantApi("/api/me/profile");
  const accessProfile = profilePayload.profile || {};
  if (accessProfile.status !== "active") {
    alert(`This account is ${accessProfile.status}. Please contact the administrator.`);
    await client.auth.signOut();
    window.location.href = "/login";
    return;
  }
  if (accessProfile.role !== "applicant") {
    alert("This dashboard is only for applicant accounts.");
    window.location.href = profilePayload.redirectPath || "/login";
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
  await recordApplicantAudit(
    "page_view",
    { path: window.location.pathname, title: document.title },
    "page",
    window.location.pathname
  );
}

profileToggle?.addEventListener("click", () => {
  profileDropdown?.classList.toggle("is-open");
});

document.addEventListener("click", (event) => {
  const clickedElement = event.target instanceof HTMLElement ? event.target : null;

  const startPermitButton = clickedElement?.closest("[data-start-permit]");
  if (startPermitButton instanceof HTMLElement) {
    const permitId = startPermitButton.dataset.startPermit || "";
    void startPermitApplication(permitId);
    return;
  }

  const uploadTrigger = clickedElement?.closest("[data-upload-trigger]");
  if (uploadTrigger instanceof HTMLElement) {
    const documentId = uploadTrigger.dataset.uploadTrigger || "";
    const input = document.querySelector(`[data-file-input="${CSS.escape(documentId)}"]`);
    input?.click();
    return;
  }

  const removeUploadButton = clickedElement?.closest("[data-remove-upload]");
  if (removeUploadButton instanceof HTMLElement) {
    void removeChecklistUpload(removeUploadButton.dataset.removeUpload || "");
    return;
  }

  if (!profileDropdown?.classList.contains("is-open")) {
    return;
  }

  const target = event.target;
  if (target instanceof Node && !profileDropdown.contains(target) && !profileToggle?.contains(target)) {
    profileDropdown.classList.remove("is-open");
  }
});

document.addEventListener("change", (event) => {
  const target = event.target;
  if (target instanceof HTMLInputElement && target.matches("[data-file-input]")) {
    void handleChecklistFileSelected(target);
  }
});

logoutButton?.addEventListener("click", async () => {
  const client = initSupabase();
  await recordApplicantAudit("logout", { path: window.location.pathname }, "session");
  await client?.auth.signOut();
  window.location.href = "/login";
});

businessContinueButton?.addEventListener("click", handleBusinessContinue);
finishApplicationButton?.addEventListener("click", () => {
  void handleFinishApplication();
});

requirementsNextButton?.addEventListener("click", () => {
  updateRequirementsNextState();
  if (!requirementsNextButton.disabled) {
    window.location.href = "/applicant/business-information";
  }
});

window.addEventListener("DOMContentLoaded", () => {
  window.lucide?.createIcons();
  syncBusinessPermitType();
  loadApplicantDashboard().then(() => {
    void loadActivePermits();
    void loadRequirementsChecklist();
  });
});
