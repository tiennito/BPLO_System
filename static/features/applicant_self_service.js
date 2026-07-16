const SELF_SUPABASE_URL = window.APP_CONFIG?.supabaseUrl || "";
const SELF_SUPABASE_KEY = window.APP_CONFIG?.supabaseAnonKey || window.APP_CONFIG?.supabasePublishableKey || "";
const page = document.body.dataset.applicantPage || "";
const pageSize = 10;

let selfClient = null;
let selfUser = null;
let selfProfile = null;
let permits = [];
let documents = [];
let documentApplications = [];
let permitPage = 1;
let documentPage = 1;
let pendingProfilePayload = null;
let profilePhotoUrl = "";
let originalProfileEmail = "";
let activePreviewUrl = "";
let profileSuccessRedirectTimer = null;

function initClient() {
  if (!selfClient && window.supabase?.createClient) {
    selfClient = window.supabase.createClient(SELF_SUPABASE_URL, SELF_SUPABASE_KEY);
  }
  return selfClient;
}

function esc(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function formatDate(value) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value).slice(0, 10) || "-";
  return date.toLocaleDateString();
}

function money(value) {
  if (value === null || value === undefined || value === "") return "-";
  const amount = Number(value);
  if (Number.isNaN(amount)) return String(value);
  return amount.toLocaleString(undefined, { style: "currency", currency: "PHP" });
}

function normalize(value) {
  return String(value || "").trim().toLowerCase();
}

function setStatus(message, isError = false) {
  const node = document.querySelector("[data-record-status], [data-profile-status]");
  if (!node) return;
  node.textContent = message || "";
  node.classList.toggle("is-error", Boolean(isError));
}

function setBusy(node, busy) {
  if (!node) return;
  node.disabled = Boolean(busy);
  node.classList.toggle("is-loading", Boolean(busy));
}

async function accessToken() {
  const client = initClient();
  if (!client) throw new Error("Supabase is not configured.");
  const { data, error } = await client.auth.getSession();
  if (error || !data.session?.access_token) throw new Error("Please sign in before continuing.");
  return data.session.access_token;
}

async function api(path, options = {}) {
  const token = await accessToken();
  const response = await fetch(path, {
    ...options,
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
  });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || "Unable to complete request.");
  return payload;
}

async function requireApplicant() {
  const client = initClient();
  if (!client) {
    window.location.href = "/login";
    return false;
  }
  const { data, error } = await client.auth.getUser();
  if (error || !data.user) {
    window.location.href = "/login";
    return false;
  }
  selfUser = data.user;
  const payload = await api("/api/me/profile");
  selfProfile = payload.profile || {};
  if (selfProfile.status !== "active" || selfProfile.role !== "applicant") {
    window.location.href = payload.redirectPath || "/login";
    return false;
  }
  const nameNode = document.querySelector("[data-profile-name]");
  if (nameNode) nameNode.textContent = selfProfile.name || "Applicant";
  return true;
}

function fillSelect(select, values, firstLabel) {
  if (!select) return;
  const current = select.value;
  select.innerHTML = `<option value="">${esc(firstLabel)}</option>` + values.map((value) => `<option>${esc(value)}</option>`).join("");
  select.value = values.includes(current) ? current : "";
}

function uniqueValues(rows, key) {
  return [...new Set(rows.map((row) => row[key]).filter(Boolean))].sort();
}

function renderPagination(container, total, currentPage, onPage) {
  if (!container) return;
  const pages = Math.max(1, Math.ceil(total / pageSize));
  container.innerHTML = `
    <button type="button" ${currentPage <= 1 ? "disabled" : ""} data-page-prev>Previous</button>
    <span>Page ${currentPage} of ${pages}</span>
    <button type="button" ${currentPage >= pages ? "disabled" : ""} data-page-next>Next</button>
  `;
  container.querySelector("[data-page-prev]")?.addEventListener("click", () => onPage(Math.max(1, currentPage - 1)));
  container.querySelector("[data-page-next]")?.addEventListener("click", () => onPage(Math.min(pages, currentPage + 1)));
}

function filteredPermits() {
  const query = normalize(document.querySelector("[data-permit-search]")?.value);
  const status = document.querySelector("[data-permit-status-filter]")?.value || "";
  const type = document.querySelector("[data-permit-type-filter]")?.value || "";
  const appType = document.querySelector("[data-application-type-filter]")?.value || "";
  const sort = document.querySelector("[data-permit-sort]")?.value || "newest";
  const rows = permits.filter((permit) => {
    const searchable = normalize(`${permit.permitNumber} ${permit.businessName} ${permit.applicationReferenceNumber}`);
    return (!query || searchable.includes(query)) &&
      (!status || permit.permitStatus === status || permit.applicationStatus === status) &&
      (!type || permit.permitType === type) &&
      (!appType || permit.applicationType === appType);
  });
  rows.sort((a, b) => {
    if (sort === "oldest") return new Date(a.createdDate || 0) - new Date(b.createdDate || 0);
    if (sort === "expiration") return new Date(a.expirationDate || "9999-12-31") - new Date(b.expirationDate || "9999-12-31");
    return new Date(b.createdDate || 0) - new Date(a.createdDate || 0);
  });
  return rows;
}

function renewalActionLabel(permit) {
  if (permit.renewalApplicationId) return "Continue Renewal";
  if (permit.renewalEligible) return "Start Renewal";
  if (permit.renewalStatus === "renewed") return "Renewed";
  if (permit.renewalStatus === "not_open") return "Not Open";
  return "Unavailable";
}

function renderRenewalCards() {
  const container = document.querySelector("[data-renewal-permit-cards]");
  if (!container) return;
  const rows = permits.filter((permit) => permit.permitNumber);
  if (!rows.length) {
    container.innerHTML = "";
    return;
  }
  container.innerHTML = rows.map((permit) => {
    const canAct = Boolean(permit.renewalEligible || permit.renewalApplicationId);
    const status = permit.renewalStatus || "not_open";
    const total = permit.renewalOfficialTotal ? money(permit.renewalOfficialTotal) : "Pending assessment";
    return `
      <article class="renewal-card" data-renewal-card="${esc(permit.id)}">
        <header>
          <span>${esc(permit.permitNumber || "-")}</span>
          <strong>${esc(permit.businessName || "Business Permit")}</strong>
        </header>
        <dl>
          <div><dt>Permit Year</dt><dd>${esc(permit.permitYear || "-")}</dd></div>
          <div><dt>Valid Until</dt><dd>${esc(formatDate(permit.validUntil || permit.expirationDate))}</dd></div>
          <div><dt>Renewal Year</dt><dd>${esc(permit.renewalYear || "-")}</dd></div>
          <div><dt>Deadline</dt><dd>${esc(formatDate(permit.renewalDueDate))}</dd></div>
          <div><dt>Status</dt><dd>${esc(status.replaceAll("_", " "))}</dd></div>
          <div><dt>Official Total</dt><dd>${esc(total)}</dd></div>
        </dl>
        <footer>
          <button class="table-link-button renewal-action" type="button" data-renew-permit="${esc(permit.id)}" ${canAct ? "" : "disabled"}>${esc(renewalActionLabel(permit))}</button>
          <button class="table-link-button" type="button" data-view-permit="${esc(permit.id)}">Details</button>
        </footer>
      </article>
    `;
  }).join("");
}

function renderPermits() {
  const body = document.querySelector("[data-permits-body]");
  if (!body) return;
  renderRenewalCards();
  const rows = filteredPermits();
  const start = (permitPage - 1) * pageSize;
  const visible = rows.slice(start, start + pageSize);
  if (!visible.length) {
    body.innerHTML = '<tr><td colspan="7" class="empty-state">No permit records found for your account.</td></tr>';
  } else {
    body.innerHTML = visible.map((permit) => `
      <tr>
        <td>${esc(permit.permitNumber || "-")}</td>
        <td>${esc(permit.applicationReferenceNumber || "-")}</td>
        <td>${esc(permit.permitType || "-")}</td>
        <td>${esc(permit.businessName || "-")}</td>
        <td>${esc(permit.applicationType || "New")}</td>
        <td>${esc(permit.permitStatus || permit.applicationStatus || "-")}</td>
        <td>
          <button class="table-link-button" type="button" data-view-permit="${esc(permit.id)}">Details</button>
          <button class="table-link-button" type="button" data-progress="${esc(permit.applicationId)}">Progress</button>
        </td>
      </tr>
    `).join("");
  }
  renderPagination(document.querySelector("[data-permit-pagination]"), rows.length, permitPage, (next) => {
    permitPage = next;
    renderPermits();
  });
  setStatus(rows.length ? `${rows.length} permit record(s) loaded.` : "No permits exist yet.");
  window.lucide?.createIcons();
}

function showPermitDetails(id) {
  const permit = permits.find((item) => item.id === id);
  const modal = document.querySelector("[data-permit-modal]");
  const body = document.querySelector("[data-permit-modal-body]");
  if (!permit || !modal || !body) return;
  const releaseCopy = permit.permitStatus === "Released" ? "Released" : permit.releaseStatus || "Not ready for release";
  body.innerHTML = `
    <div class="record-detail-grid">
      ${Object.entries({
        "Permit ID": permit.permitId,
        "Permit number": permit.permitNumber,
        "Application reference number": permit.applicationReferenceNumber,
        "Permit type": permit.permitType,
        "Business name": permit.businessName,
        "Business owner": permit.businessOwner,
        "Application type": permit.applicationType,
        "Date submitted": formatDate(permit.dateSubmitted),
        "Date approved": formatDate(permit.dateApproved),
        "Validity start date": formatDate(permit.validityStartDate),
        "Expiration date": formatDate(permit.expirationDate),
        "Application status": permit.applicationStatus,
        "Permit status": permit.permitStatus,
        "Release status": releaseCopy,
        "Payment status": permit.paymentStatus,
        "Date released": formatDate(permit.dateReleased),
        "Created date": formatDate(permit.createdDate),
        "Last updated date": formatDate(permit.lastUpdatedDate),
      }).map(([label, value]) => `<article><span>${esc(label)}</span><strong>${esc(value || "-")}</strong></article>`).join("")}
    </div>
    <p class="release-note">Final permit download or printing is unavailable here. Please follow the release or pickup status shown by BPLO.</p>
    <div class="modal-actions">
      <a class="table-link-button" href="/applicant/business-information?applicationId=${encodeURIComponent(permit.applicationId || "")}">Open Application</a>
      ${(permit.renewalEligible || permit.renewalApplicationId) ? `<button class="table-link-button" type="button" data-renew-permit="${esc(permit.id)}">${esc(renewalActionLabel(permit))}</button>` : ""}
    </div>
  `;
  modal.hidden = false;
  window.lucide?.createIcons();
}

async function startPermitRenewal(permitId, button) {
  if (!permitId) return;
  setBusy(button, true);
  try {
    const payload = await api(`/applicant/api/permits/${encodeURIComponent(permitId)}/renew`, { method: "POST", body: "{}" });
    const nextUrl = payload.nextUrl || `/applicant/business-information?applicationId=${encodeURIComponent(payload.application?.id || "")}`;
    setStatus(payload.message || "Renewal application is ready.");
    window.location.href = nextUrl;
  } catch (error) {
    setStatus(error.message || "Unable to start renewal.", true);
  } finally {
    setBusy(button, false);
  }
}

async function showProgress(applicationId) {
  const modal = document.querySelector("[data-permit-modal]");
  const body = document.querySelector("[data-permit-modal-body]");
  if (!applicationId || !modal || !body) return;
  body.innerHTML = '<p class="empty-state">Loading progress...</p>';
  modal.hidden = false;
  const payload = await api(`/applicant/api/applications/${encodeURIComponent(applicationId)}/progress`);
  body.innerHTML = `
    <div class="record-detail-grid">
      ${(payload.steps || []).map((step) => `
        <article>
          <span>${esc(step.label)}</span>
          <strong>${esc(step.state || "Pending")}</strong>
          ${step.remarks ? `<small>${esc(step.remarks)}</small>` : ""}
        </article>
      `).join("")}
    </div>
    ${(payload.departments || []).length ? `
      <h3>Department Review</h3>
      <div class="record-detail-grid">
        ${payload.departments.map((department) => `
          <article>
            <span>${esc(department.departmentName || "Department")}</span>
            <strong>${esc(department.state || "Pending")}</strong>
            ${department.remarks ? `<small>${esc(department.remarks)}</small>` : ""}
          </article>
        `).join("")}
      </div>
    ` : ""}
  `;
}

async function loadPermits() {
  const payload = await api("/applicant/api/my-permits");
  permits = payload.permits || [];
  fillSelect(document.querySelector("[data-permit-status-filter]"), uniqueValues(permits, "permitStatus"), "All statuses");
  fillSelect(document.querySelector("[data-permit-type-filter]"), uniqueValues(permits, "permitType"), "All permit types");
  fillSelect(document.querySelector("[data-application-type-filter]"), uniqueValues(permits, "applicationType"), "All application types");
  renderPermits();
  const focus = new URLSearchParams(window.location.search).get("focus");
  if (focus) {
    const permit = permits.find((item) => item.id === focus || item.permitNumber === focus);
    if (permit) showPermitDetails(permit.id);
  }
}

function filteredDocuments() {
  const query = normalize(document.querySelector("[data-document-search]")?.value);
  const application = document.querySelector("[data-document-application-filter]")?.value || "";
  const category = document.querySelector("[data-document-category-filter]")?.value || "";
  const status = document.querySelector("[data-document-status-filter]")?.value || "";
  const date = document.querySelector("[data-document-date-filter]")?.value || "";
  return documents.filter((doc) => {
    const searchable = normalize(`${doc.originalFilename} ${doc.documentType}`);
    const uploadDate = doc.uploadDate ? String(doc.uploadDate).slice(0, 10) : "";
    return (!query || searchable.includes(query)) &&
      (!application || doc.applicationId === application) &&
      (!category || doc.documentCategory === category) &&
      (!status || doc.verificationStatus === status) &&
      (!date || uploadDate === date);
  });
}

function renderDocuments() {
  const body = document.querySelector("[data-documents-body]");
  if (!body) return;
  const rows = filteredDocuments();
  const visible = rows.slice((documentPage - 1) * pageSize, documentPage * pageSize);
  if (!visible.length) {
    body.innerHTML = '<tr><td colspan="6" class="empty-state">No documents are available for your account.</td></tr>';
  } else {
    body.innerHTML = visible.map((doc) => `
      <tr>
        <td><strong>${esc(doc.documentType)}</strong><small>${esc(doc.originalFilename || "No file uploaded")}</small></td>
        <td>${esc(doc.documentCategory)}</td>
        <td>${esc(doc.applicationReferenceNumber || "-")}</td>
        <td>${esc(doc.verificationStatus)}</td>
        <td>${formatDate(doc.uploadDate)}</td>
        <td>
          <button class="table-link-button" type="button" data-view-document="${esc(doc.id)}" ${doc.fileUrl ? "" : "disabled"}>View</button>
          <button class="table-link-button" type="button" data-download-document="${esc(doc.id)}" ${doc.downloadUrl ? "" : "disabled"}>Download</button>
          <input type="file" hidden data-replace-input="${esc(doc.id)}" />
          <button class="table-link-button" type="button" data-replace-document="${esc(doc.id)}" ${doc.canReplace ? "" : "disabled"}>Replace</button>
        </td>
      </tr>
      ${doc.rejectionRemarks ? `<tr><td colspan="6" class="document-remarks">Correction needed: ${esc(doc.rejectionRemarks)}</td></tr>` : ""}
    `).join("");
  }
  renderPagination(document.querySelector("[data-document-pagination]"), rows.length, documentPage, (next) => {
    documentPage = next;
    renderDocuments();
  });
  setStatus(rows.length ? `${rows.length} document record(s) loaded.` : "No documents are available.");
}

async function fetchDocumentBlob(doc, mode = "view") {
  const token = await accessToken();
  const url = mode === "download" ? doc.downloadUrl : doc.fileUrl;
  const response = await fetch(url, { headers: { Authorization: `Bearer ${token}` } });
  if (!response.ok) {
    let message = "Unable to load document.";
    try {
      const payload = await response.json();
      message = payload.error || message;
    } catch {
      // Binary endpoints do not always return JSON.
    }
    throw new Error(message);
  }
  return response.blob();
}

async function previewDocument(id) {
  const doc = documents.find((item) => item.id === id);
  const modal = document.querySelector("[data-document-modal]");
  const body = document.querySelector("[data-document-modal-body]");
  if (!doc || !modal || !body) return;
  body.innerHTML = '<p class="empty-state">Loading preview...</p>';
  modal.hidden = false;
  if (activePreviewUrl) {
    URL.revokeObjectURL(activePreviewUrl);
    activePreviewUrl = "";
  }
  const blob = await fetchDocumentBlob(doc, "view");
  activePreviewUrl = URL.createObjectURL(blob);
  const format = normalize(doc.fileFormat);
  const preview = ["pdf"].includes(format)
    ? `<iframe title="Document preview" src="${esc(activePreviewUrl)}"></iframe>`
    : ["png", "jpg", "jpeg", "gif", "webp"].includes(format)
      ? `<img src="${esc(activePreviewUrl)}" alt="${esc(doc.documentType)}" />`
      : `<p class="empty-state">Preview is not available for this file type. You can download your uploaded file.</p>`;
  body.innerHTML = `
    <section class="document-preview">${preview}</section>
    <div class="record-detail-grid">
      ${Object.entries({
        "Document ID": doc.documentId,
        "Application ID": doc.applicationId,
        "Permit ID": doc.permitId,
        "Document type": doc.documentType,
        "Category": doc.documentCategory,
        "Filename": doc.originalFilename,
        "Verification status": doc.verificationStatus,
        "OCR status": doc.ocrProcessingStatus,
        "OCR confidence": doc.ocrConfidenceScore || "-",
        "Expiration date": formatDate(doc.documentExpirationDate),
      }).map(([label, value]) => `<article><span>${esc(label)}</span><strong>${esc(value || "-")}</strong></article>`).join("")}
    </div>
  `;
}

async function downloadDocument(id, button) {
  const doc = documents.find((item) => item.id === id);
  if (!doc) return;
  setBusy(button, true);
  try {
    const blob = await fetchDocumentBlob(doc, "download");
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = doc.originalFilename || "document";
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  } finally {
    setBusy(button, false);
  }
}

function parseMaxBytes(value) {
  const text = String(value || "10MB").toUpperCase();
  const amount = Number.parseFloat(text);
  if (Number.isNaN(amount)) return 10 * 1024 * 1024;
  if (text.includes("KB")) return amount * 1024;
  if (text.includes("GB")) return amount * 1024 * 1024 * 1024;
  return amount * 1024 * 1024;
}

async function assertReadable(file) {
  if (file.type.startsWith("image/")) {
    await new Promise((resolve, reject) => {
      const img = new Image();
      const url = URL.createObjectURL(file);
      img.onload = () => { URL.revokeObjectURL(url); resolve(); };
      img.onerror = () => { URL.revokeObjectURL(url); reject(new Error("The image file cannot be read.")); };
      img.src = url;
    });
  } else if (file.type === "application/pdf") {
    const header = await file.slice(0, 5).text();
    if (header !== "%PDF-") throw new Error("The PDF file cannot be read.");
  }
}

async function replaceDocument(id, file, button) {
  const doc = documents.find((item) => item.id === id);
  if (!doc || !file) return;
  const ext = file.name.split(".").pop().toLowerCase();
  const allowed = String(doc.acceptedFileTypes || "pdf,png,jpg,jpeg").toLowerCase();
  if (!allowed.includes(ext)) throw new Error("This file type is not accepted for the selected document.");
  if (file.size > parseMaxBytes(doc.maxFileSize)) throw new Error(`The file is larger than ${doc.maxFileSize || "10MB"}.`);
  if (documents.some((item) => item.applicationId === doc.applicationId && item.id !== id && item.originalFilename === file.name)) {
    throw new Error("A document with the same filename already exists for this application.");
  }
  await assertReadable(file);
  setBusy(button, true);
  const storagePath = `${selfUser.id}/${doc.applicationId}/${doc.id}/${Date.now()}-${file.name.replace(/[^a-zA-Z0-9._-]/g, "_")}`;
  const { error } = await initClient().storage.from("application-documents").upload(storagePath, file, { cacheControl: "3600", upsert: false });
  if (error) throw new Error(error.message || "Unable to upload replacement.");
  await api(`/applicant/api/documents/${encodeURIComponent(id)}/replacement`, {
    method: "POST",
    body: JSON.stringify({ fileName: file.name, fileUrl: storagePath, fileSize: file.size }),
  });
  await loadDocuments();
  setStatus("Replacement uploaded. It is now pending review.");
}

async function loadDocuments() {
  const payload = await api("/applicant/api/my-documents");
  documents = payload.documents || [];
  documentApplications = payload.applications || [];
  const appSelect = document.querySelector("[data-document-application-filter]");
  if (appSelect) {
    appSelect.innerHTML = '<option value="">All applications</option>' + documentApplications.map((app) => `<option value="${esc(app.id)}">${esc(app.label)}</option>`).join("");
  }
  fillSelect(document.querySelector("[data-document-category-filter]"), uniqueValues(documents, "documentCategory"), "All categories");
  fillSelect(document.querySelector("[data-document-status-filter]"), uniqueValues(documents, "verificationStatus"), "All statuses");
  renderDocuments();
}

function formValues(form) {
  return Object.fromEntries(new FormData(form).entries());
}

function fillProfile(profile) {
  const form = document.querySelector("[data-profile-form]");
  if (!form) return;
  Object.entries(profile).forEach(([key, value]) => {
    const field = form.elements[key];
    if (field) field.value = typeof value === "boolean" ? (value ? "Yes" : "No") : (value || "");
  });
  profilePhotoUrl = profile.profilePhotoUrl || "";
  originalProfileEmail = profile.email || "";
  const preview = document.querySelector("[data-profile-photo-preview]");
  if (preview) {
    preview.style.backgroundImage = profilePhotoUrl ? `url("${profilePhotoUrl}")` : "";
    preview.textContent = profilePhotoUrl ? "" : "Photo";
  }
  const nameNode = document.querySelector("[data-profile-name]");
  if (nameNode) nameNode.textContent = [profile.firstName, profile.lastName].filter(Boolean).join(" ") || "Applicant";
}

function validateProfile(payload) {
  if (!payload.firstName || !payload.lastName || !payload.email || !payload.contactNumber) {
    throw new Error("First name, last name, email, and contact number are required.");
  }
  if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(payload.email)) throw new Error("Enter a valid email address.");
  if (!/^(\+639|09)\d{9}$/.test(payload.contactNumber.replace(/[\s()-]+/g, ""))) {
    throw new Error("Enter a valid Philippine mobile number.");
  }
}

function redirectToApplicantHome() {
  window.location.href = "/applicant";
}

function showProfileSuccessModal(message) {
  const modal = document.querySelector("[data-success-modal]");
  const messageNode = document.querySelector("[data-success-message]");
  if (!modal) return;
  if (messageNode) {
    messageNode.textContent = message || "Your profile changes have been saved successfully.";
  }
  modal.hidden = false;
  modal.querySelector("[data-close-modal]")?.focus();
  if (profileSuccessRedirectTimer) {
    window.clearTimeout(profileSuccessRedirectTimer);
  }
  profileSuccessRedirectTimer = window.setTimeout(redirectToApplicantHome, 1400);
  window.lucide?.createIcons();
}

async function saveProfile(button) {
  if (!pendingProfilePayload) return;
  setBusy(button, true);
  try {
    const payload = await api("/applicant/api/profile", {
      method: "PATCH",
      body: JSON.stringify(pendingProfilePayload),
    });
    if (payload.emailVerificationRequired && pendingProfilePayload.email && pendingProfilePayload.email !== originalProfileEmail) {
      const { error } = await initClient().auth.updateUser({ email: pendingProfilePayload.email });
      if (error) {
        throw new Error(error.message || "Profile saved, but email verification could not be sent.");
      }
    }
    fillProfile(payload.profile || {});
    document.querySelector("[data-confirm-modal]").hidden = true;
    const message = payload.emailVerificationRequired
      ? "Profile saved. Please verify your updated email address."
      : "Your profile changes have been saved successfully.";
    setStatus(payload.emailVerificationRequired ? message : "Profile updated successfully.");
    showProfileSuccessModal(message);
  } finally {
    setBusy(button, false);
    pendingProfilePayload = null;
  }
}

async function loadProfile() {
  const payload = await api("/applicant/api/profile");
  fillProfile(payload.profile || {});
  setStatus("Your saved profile information is loaded.");
}

async function uploadProfilePhoto(file) {
  if (!file) return;
  if (!file.type.startsWith("image/")) throw new Error("Please choose a readable image file.");
  if (file.size > 3 * 1024 * 1024) throw new Error("Profile photo must be 3MB or smaller.");
  await assertReadable(file);
  const storagePath = `${selfUser.id}/profile/${Date.now()}-${file.name.replace(/[^a-zA-Z0-9._-]/g, "_")}`;
  const { error } = await initClient().storage.from("profile-photos").upload(storagePath, file, { cacheControl: "3600", upsert: true });
  if (error) throw new Error(error.message || "Unable to upload profile photo.");
  const { data } = initClient().storage.from("profile-photos").getPublicUrl(storagePath);
  profilePhotoUrl = data.publicUrl || storagePath;
  const preview = document.querySelector("[data-profile-photo-preview]");
  if (preview) {
    preview.style.backgroundImage = `url("${profilePhotoUrl}")`;
    preview.textContent = "";
  }
}

document.addEventListener("click", async (event) => {
  const target = event.target instanceof HTMLElement ? event.target : null;
  if (target?.closest("[data-close-modal]")) {
    const successModal = target.closest("[data-success-modal]");
    if (successModal) {
      if (profileSuccessRedirectTimer) {
        window.clearTimeout(profileSuccessRedirectTimer);
      }
      redirectToApplicantHome();
      return;
    }
    document.querySelectorAll(".record-modal").forEach((modal) => { modal.hidden = true; });
    if (activePreviewUrl) {
      URL.revokeObjectURL(activePreviewUrl);
      activePreviewUrl = "";
    }
    return;
  }
  const permitButton = target?.closest("[data-view-permit]");
  if (permitButton) showPermitDetails(permitButton.dataset.viewPermit || "");
  const renewalButton = target?.closest("[data-renew-permit]");
  if (renewalButton) {
    await startPermitRenewal(renewalButton.dataset.renewPermit || "", renewalButton);
    return;
  }
  const progressButton = target?.closest("[data-progress]");
  if (progressButton) {
    try {
      await showProgress(progressButton.dataset.progress || "");
    } catch (error) {
      setStatus(error.message || "Unable to load progress.", true);
    }
  }
  const documentButton = target?.closest("[data-view-document]");
  if (documentButton) {
    try {
      await previewDocument(documentButton.dataset.viewDocument || "");
    } catch (error) {
      setStatus(error.message || "Unable to preview document.", true);
    }
  }
  const downloadButton = target?.closest("[data-download-document]");
  if (downloadButton) {
    try {
      await downloadDocument(downloadButton.dataset.downloadDocument || "", downloadButton);
    } catch (error) {
      setStatus(error.message || "Unable to download document.", true);
    }
  }
  const replaceButton = target?.closest("[data-replace-document]");
  if (replaceButton) document.querySelector(`[data-replace-input="${CSS.escape(replaceButton.dataset.replaceDocument || "")}"]`)?.click();
  if (target?.closest("[data-profile-photo-upload]")) document.querySelector("[data-profile-photo-input]")?.click();
  if (target?.closest("[data-profile-photo-remove]")) {
    profilePhotoUrl = "";
    const preview = document.querySelector("[data-profile-photo-preview]");
    if (preview) {
      preview.style.backgroundImage = "";
      preview.textContent = "Photo";
    }
  }
  const confirm = target?.closest("[data-confirm-save]");
  if (confirm) {
    try {
      await saveProfile(confirm);
    } catch (error) {
      setStatus(error.message || "Unable to save profile.", true);
    }
  }
});

document.addEventListener("change", async (event) => {
  const target = event.target;
  if (!(target instanceof HTMLInputElement || target instanceof HTMLSelectElement)) return;
  if (target.matches("[data-permit-search], [data-permit-status-filter], [data-permit-type-filter], [data-application-type-filter], [data-permit-sort]")) {
    permitPage = 1;
    renderPermits();
  }
  if (target.matches("[data-document-search], [data-document-application-filter], [data-document-category-filter], [data-document-status-filter], [data-document-date-filter]")) {
    documentPage = 1;
    renderDocuments();
  }
  if (target.matches("[data-replace-input]") && target.files?.[0]) {
    const button = document.querySelector(`[data-replace-document="${CSS.escape(target.dataset.replaceInput || "")}"]`);
    try {
      await replaceDocument(target.dataset.replaceInput || "", target.files[0], button);
    } catch (error) {
      setStatus(error.message || "Unable to replace document.", true);
    } finally {
      setBusy(button, false);
      target.value = "";
    }
  }
  if (target.matches("[data-profile-photo-input]") && target.files?.[0]) {
    try {
      await uploadProfilePhoto(target.files[0]);
      setStatus("Profile photo ready. Save changes to apply it.");
    } catch (error) {
      setStatus(error.message || "Unable to upload profile photo.", true);
    } finally {
      target.value = "";
    }
  }
});

document.addEventListener("input", (event) => {
  const target = event.target;
  if (!(target instanceof HTMLInputElement)) return;
  if (target.matches("[data-permit-search]")) {
    permitPage = 1;
    renderPermits();
  }
  if (target.matches("[data-document-search]")) {
    documentPage = 1;
    renderDocuments();
  }
});

document.querySelector("[data-profile-form]")?.addEventListener("submit", (event) => {
  event.preventDefault();
  try {
    pendingProfilePayload = { ...formValues(event.currentTarget), profilePhotoUrl };
    validateProfile(pendingProfilePayload);
    document.querySelector("[data-confirm-modal]").hidden = false;
  } catch (error) {
    setStatus(error.message || "Please check your profile details.", true);
  }
});

document.querySelector("[data-profile-toggle]")?.addEventListener("click", () => {
  document.querySelector("[data-profile-dropdown]")?.classList.toggle("is-open");
});

(async function boot() {
  try {
    const ok = await requireApplicant();
    if (!ok) return;
    if (page === "permits") await loadPermits();
    if (page === "documents") await loadDocuments();
    if (page === "profile") await loadProfile();
    window.lucide?.createIcons();
  } catch (error) {
    setStatus(error.message || "Unable to load this page.", true);
  }
})();
