const SUPABASE_URL = window.APP_CONFIG?.supabaseUrl || "";
const SUPABASE_ANON_KEY =
  window.APP_CONFIG?.supabaseAnonKey || window.APP_CONFIG?.supabasePublishableKey || "";

const page = document.body.dataset.page || "dashboard";
const statusNode = document.querySelector("[data-status]");
let supabaseClient = null;
let session = null;
let currentUser = null;
let applicationCache = [];
let selectedApplicationId = "";
let inspectionCache = [];
let reportCache = [];
let settingsCache = null;
let workspaceCache = {};
let inspectionAutosaveTimer = null;
let isPopulatingInspectionForm = false;

const INSPECTION_DRAFT_PREFIX = "bplo_department_inspection_draft";

function initSupabase() {
  if (!window.supabase?.createClient) {
    return null;
  }
  if (!supabaseClient) {
    supabaseClient = window.supabase.createClient(SUPABASE_URL, SUPABASE_ANON_KEY);
  }
  return supabaseClient;
}

function setStatus(message, isError = false) {
  if (!statusNode) {
    return;
  }
  statusNode.textContent = message;
  statusNode.style.color = isError ? "#b42318" : "#626262";
}

function normalizeRole(value) {
  const role = String(value || "").trim().toLowerCase().replace(/[-\s]+/g, "_");
  const aliases = {
    department: "department_office",
    department_user: "department_office",
    department_office_user: "department_office",
  };
  return aliases[role] || role;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function statusClass(value) {
  return `status-${String(value || "draft").toLowerCase().replace(/[^a-z0-9]+/g, "-")}`;
}

function statusPill(value) {
  return `<span class="status-pill ${statusClass(value)}">${escapeHtml(value || "-")}</span>`;
}

async function apiFetch(path, options = {}) {
  if (!session?.access_token) {
    throw new Error("Please log in as a department office user.");
  }
  const isFormData = options.body instanceof FormData;

  const response = await fetch(path, {
    ...options,
    headers: {
      "Authorization": `Bearer ${session.access_token}`,
      ...(isFormData ? {} : { "Content-Type": "application/json" }),
      ...(options.headers || {}),
    },
  });
  const result = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(result.error || "Request failed.");
  }
  return result;
}

async function openAuthenticatedFile(path, fileName, mode = "view") {
  const response = await fetch(path, {
    headers: { "Authorization": `Bearer ${session.access_token}` },
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload.error || "Unable to load file.");
  }
  const blob = await response.blob();
  const disposition = response.headers.get("Content-Disposition") || "";
  const match = disposition.match(/filename="([^"]+)"/);
  const url = URL.createObjectURL(blob);
  if (mode === "download") {
    const link = document.createElement("a");
    link.href = url;
    link.download = match?.[1] || fileName || "download";
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
    return;
  }
  showFilePreviewModal(url, blob.type, match?.[1] || fileName || "Preview file");
}

function setFilePreviewModalOpen(isOpen) {
  const modal = document.querySelector("[data-file-preview-modal]");
  if (!modal) {
    return;
  }
  modal.hidden = !isOpen;
  document.body.style.overflow = isOpen ? "hidden" : "";
  if (isOpen) {
    modal.querySelector("[data-close-file-preview]")?.focus();
  }
}

function clearFilePreviewModal() {
  const body = document.querySelector("[data-file-preview-body]");
  if (!body) {
    return;
  }
  const currentUrl = body.dataset.previewUrl || "";
  if (currentUrl) {
    URL.revokeObjectURL(currentUrl);
  }
  body.dataset.previewUrl = "";
  body.innerHTML = "<p>Select a file to preview.</p>";
}

function showFilePreviewModal(url, mimeType = "", fileName = "Preview file") {
  const body = document.querySelector("[data-file-preview-body]");
  const title = document.querySelector("#file-preview-title");
  if (!body) {
    URL.revokeObjectURL(url);
    return;
  }

  clearFilePreviewModal();
  body.dataset.previewUrl = url;
  if (title) {
    title.innerHTML = `<i data-lucide="eye"></i> ${escapeHtml(fileName)}`;
  }

  const normalizedMime = String(mimeType || "").toLowerCase();
  const normalizedName = String(fileName || "").toLowerCase();
  if (normalizedMime.startsWith("image/") || /\.(png|jpe?g|webp|gif|bmp)$/i.test(normalizedName)) {
    body.innerHTML = `<img class="file-preview-image" src="${url}" alt="${escapeHtml(fileName)} preview" />`;
  } else if (normalizedMime === "application/pdf" || normalizedName.endsWith(".pdf")) {
    body.innerHTML = `<iframe class="file-preview-frame" src="${url}" title="${escapeHtml(fileName)} preview"></iframe>`;
  } else {
    body.innerHTML = `
      <div class="file-preview-empty">
        <i data-lucide="file-question"></i>
        <strong>${escapeHtml(fileName)}</strong>
        <p>This file type cannot be previewed here. Use Download to open it on your device.</p>
      </div>
    `;
  }

  setFilePreviewModalOpen(true);
  window.lucide?.createIcons();
}

function closeFilePreviewModal() {
  setFilePreviewModalOpen(false);
  clearFilePreviewModal();
}

async function requireDepartmentSession() {
  const client = initSupabase();
  if (!client) {
    throw new Error("Supabase client is unavailable.");
  }

  const sessionResult = await client.auth.getSession();
  session = sessionResult.data.session;
  if (!session) {
    window.location.assign("/login");
    return false;
  }

  const profilePayload = await apiFetch("/api/me/profile");
  const accessProfile = profilePayload.profile || {};
  const role = normalizeRole(accessProfile.role);
  const departmentKey = accessProfile.departmentKey;
  if (accessProfile.status !== "active") {
    setStatus(`This account is ${accessProfile.status} and cannot access the dashboard.`, true);
    return false;
  }
  if (role !== "department_office" || !accessProfile.departmentId) {
    setStatus("This account is signed in, but it is not assigned to an active department office.", true);
    console.debug("[auth] department guard rejected", {
      authUserId: accessProfile.authUserId,
      role,
      departmentKey: departmentKey || "",
    });
    return false;
  }

  const profile = await apiFetch("/department/api/me");
  console.debug("[auth] department profile", profile.user);
  currentUser = profile.user;
  document.querySelectorAll("[data-user-name]").forEach((node) => {
    node.textContent = currentUser.name || "Department user";
  });
  document.querySelectorAll("[data-department-name]").forEach((node) => {
    node.textContent = currentUser.departmentName || "Department Office";
  });
  return true;
}

async function loadApplications() {
  const result = await apiFetch("/department/api/applications");
  applicationCache = result.applications || [];
  updateCounts(result.counts || {});
  return result;
}

function updateCounts(counts) {
  Object.entries(counts).forEach(([key, value]) => {
    document.querySelectorAll(`[data-count="${key}"]`).forEach((node) => {
      node.textContent = value ?? 0;
    });
  });
  document.querySelectorAll("[data-pending-badge]").forEach((node) => {
    node.textContent = counts.pending ?? 0;
  });
  document.querySelectorAll("[data-rejected-badge]").forEach((node) => {
    node.textContent = counts.rejected ?? 0;
  });
}

function renderApplications(applications) {
  const table = document.querySelector("[data-applications-table]");
  if (!table) {
    return;
  }
  if (!applications.length) {
    const colspan = page === "applications" ? 5 : 4;
    table.innerHTML = `<tr><td colspan="${colspan}" class="empty-state">No applications assigned to this department.</td></tr>`;
    return;
  }

  if (page === "applications") {
    table.innerHTML = applications
      .map(
        (application) => `
          <tr class="${application.applicationId === selectedApplicationId ? "is-selected" : ""}">
            <td><button type="button" data-select-application="${application.applicationId}">${escapeHtml(application.referenceNumber)}</button></td>
            <td>${escapeHtml(application.businessName)}</td>
            <td>${escapeHtml(application.applicant?.name || application.applicant?.email || "-")}</td>
            <td>${escapeHtml(application.application?.submittedId || "-")}</td>
            <td>${statusPill(application.status)}</td>
          </tr>
        `
      )
      .join("");
    return;
  }

  table.innerHTML = applications
    .map(
      (application) => `
        <tr>
          <td>${escapeHtml(application.referenceNumber)}</td>
          <td>${escapeHtml(application.businessName)}</td>
          <td>${statusPill(application.status)}</td>
          <td>
            <div class="action-row">
              <a class="btn" href="/department/applications?id=${encodeURIComponent(application.applicationId)}&ref=${encodeURIComponent(application.referenceNumber || "")}">View</a>
            </div>
          </td>
        </tr>
      `
    )
    .join("");
}

function getFilteredApplications() {
  const search = (document.querySelector("[data-search]")?.value || "").toLowerCase();
  const status = document.querySelector("[data-status-filter]")?.value || "";
  return applicationCache.filter((application) => {
    const matchesStatus = !status || application.status === status;
    const haystack = `${application.referenceNumber} ${application.businessName} ${application.applicant?.name || ""}`.toLowerCase();
    return matchesStatus && haystack.includes(search);
  });
}

function applyApplicationFilters() {
  const filtered = getFilteredApplications();
  renderApplications(filtered);
  populateApplicationPicker(filtered);
}

function getRequestedApplication() {
  const params = new URLSearchParams(window.location.search);
  const requested = (params.get("id") || params.get("applicationId") || params.get("ref") || "").trim().toLowerCase();
  if (!requested) {
    return null;
  }
  return applicationCache.find((application) => {
    const applicationId = String(application.applicationId || "").toLowerCase();
    const referenceNumber = String(application.referenceNumber || "").toLowerCase();
    const submittedId = String(application.application?.submittedId || "").toLowerCase();
    return applicationId === requested || referenceNumber === requested || submittedId === requested;
  }) || null;
}

async function loadDashboardLike() {
  setStatus("Loading department applications...");
  const result = await loadApplications();
  if (page === "applications") {
    const requestedApplication = getRequestedApplication();
    selectedApplicationId = requestedApplication?.applicationId || selectedApplicationId || applicationCache[0]?.applicationId || "";
    populateApplicationPicker(applicationCache);
    renderApplicationWorkspace();
    if (requestedApplication) {
      setStatus(`${result.departmentName || "Department"} application ${requestedApplication.referenceNumber} loaded.`);
      return;
    }
  }
  renderApplications(page === "dashboard" ? applicationCache.slice(0, 6) : applicationCache);
  setStatus(`${result.departmentName || "Department"} data loaded.`);
}

function populateApplicationPicker(applications) {
  const picker = document.querySelector("[data-application-picker]");
  if (!picker) {
    return;
  }
  const current = picker.value || selectedApplicationId;
  picker.innerHTML = '<option value="">Select application</option>' + applications
    .map((application) => `<option value="${application.applicationId}">${escapeHtml(application.referenceNumber)} - ${escapeHtml(application.businessName)}</option>`)
    .join("");
  picker.value = applications.some((application) => application.applicationId === current) ? current : selectedApplicationId;
}

function appMiniCard(label, value) {
  return `<article class="app-mini-card"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value || "-")}</strong></article>`;
}

function getSelectedApplication() {
  return applicationCache.find((application) => application.applicationId === selectedApplicationId) || applicationCache[0] || null;
}

function formatMoney(value) {
  const numeric = Number(value || 0);
  return `PHP ${numeric.toLocaleString("en-PH", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function findApplicationById(applicationId) {
  return applicationCache.find((application) => application.applicationId === applicationId) || null;
}

function formatInspectionDate(value) {
  if (!value) {
    return "-";
  }
  const date = new Date(`${value}T00:00:00`);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleDateString("en-US", { month: "long", day: "numeric", year: "numeric" });
}

function formatInspectionTime(value) {
  if (!value) {
    return "-";
  }
  const [hours = "0", minutes = "0"] = value.split(":");
  const date = new Date();
  date.setHours(Number(hours), Number(minutes), 0, 0);
  return date.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit" });
}

function inspectionDisplayStatus(status) {
  if (status === "Draft") {
    return "Pending";
  }
  return status || "Pending";
}

function inspectionStatusPill(status) {
  const display = inspectionDisplayStatus(status);
  return `<span class="inspection-status inspection-status--${statusClass(display).replace("status-", "")}">${escapeHtml(display)}</span>`;
}

function createEmptyAssessmentItem() {
  return {
    id: "",
    fee_name: "",
    category: "",
    amount: "",
    penalty: "",
    remarks: "",
  };
}

function assessmentRowTemplate(item = {}) {
  const normalized = {
    id: item.id || "",
    fee_name: item.fee_name || item.feeName || "",
    category: item.category || "",
    amount: item.amount ?? "",
    penalty: item.penalty ?? "",
  };
  return `
    <div class="assessment-row" data-assessment-row data-assessment-item-id="${escapeHtml(normalized.id)}">
      <input name="feeDescription" placeholder="Department fee" value="${escapeHtml(normalized.fee_name)}" />
      <input name="category" placeholder="Code" value="${escapeHtml(normalized.category)}" />
      <input name="amount" type="number" min="0" step="0.01" placeholder="0.00" value="${escapeHtml(normalized.amount)}" />
      <input name="penalty" type="number" min="0" step="0.01" placeholder="0.00" value="${escapeHtml(normalized.penalty)}" />
      <button class="assessment-row-remove" type="button" data-remove-assessment-row aria-label="Remove fee row">
        <i data-lucide="trash-2"></i>
      </button>
    </div>
  `;
}

function getAssessmentRows() {
  return Array.from(document.querySelectorAll("[data-assessment-row]"));
}

function collectAssessmentItems(form) {
  const rows = getAssessmentRows();
  const remarks = form?.elements.assessmentRemarks?.value?.trim() || "";
  return rows
    .map((row) => {
      const inputs = row.querySelectorAll("input");
      const [feeInput, categoryInput, amountInput, penaltyInput] = inputs;
      return {
        id: row.dataset.assessmentItemId || "",
        feeName: feeInput?.value?.trim() || "",
        category: categoryInput?.value?.trim() || "",
        amount: Number(amountInput?.value || 0),
        penalty: Number(penaltyInput?.value || 0),
        remarks,
      };
    })
    .filter((item) => item.feeName || item.category || item.amount || item.penalty);
}

function updateAssessmentRowActions() {
  const rows = getAssessmentRows();
  rows.forEach((row) => {
    const removeButton = row.querySelector("[data-remove-assessment-row]");
    if (removeButton) {
      removeButton.hidden = rows.length <= 1;
    }
  });
}

function renderAssessmentRows(items = []) {
  const container = document.querySelector("[data-assessment-rows]");
  if (!container) {
    return;
  }
  const rows = items.length ? items : [createEmptyAssessmentItem()];
  container.innerHTML = rows.map((item) => assessmentRowTemplate(item)).join("");
  updateAssessmentRowActions();
  window.lucide?.createIcons();
}

function addAssessmentRow(item = createEmptyAssessmentItem()) {
  const container = document.querySelector("[data-assessment-rows]");
  if (!container) {
    return;
  }
  container.insertAdjacentHTML("beforeend", assessmentRowTemplate(item));
  updateAssessmentRowActions();
  window.lucide?.createIcons();
}

function syncAssessmentTotals() {
  const form = document.querySelector("[data-assessment-form]");
  if (!form) {
    return;
  }
  const items = collectAssessmentItems(form);
  const amount = items.reduce((sum, item) => sum + Number(item.amount || 0), 0);
  const penalty = items.reduce((sum, item) => sum + Number(item.penalty || 0), 0);
  form.elements.amountSummary.value = formatMoney(amount);
  form.elements.penaltySummary.value = formatMoney(penalty);
  form.elements.totalSummary.value = formatMoney(amount + penalty);
}

function normalizeTimeInput(value) {
  return value ? String(value).slice(0, 5) : "";
}

function getInspectionDraftKey(applicationId = selectedApplicationId) {
  if (!applicationId) {
    return "";
  }
  const departmentKey = currentUser?.departmentKey || "department";
  return `${INSPECTION_DRAFT_PREFIX}:${departmentKey}:${applicationId}`;
}

function readInspectionDraft(applicationId = selectedApplicationId) {
  const key = getInspectionDraftKey(applicationId);
  if (!key) {
    return null;
  }
  try {
    return JSON.parse(window.localStorage.getItem(key) || "null");
  } catch {
    return null;
  }
}

function writeInspectionDraft(applicationId, payload) {
  const key = getInspectionDraftKey(applicationId);
  if (!key) {
    return;
  }
  const draft = {
    scheduled_date: payload.scheduledDate || "",
    scheduled_time: payload.scheduledTime || "",
    end_time: payload.endTime || "",
    status: payload.status || "Draft",
    location_address: payload.locationAddress || "",
    remarks: payload.remarks || "",
    saved_at: new Date().toISOString(),
  };
  try {
    window.localStorage.setItem(key, JSON.stringify(draft));
  } catch {
    // Local drafts are a convenience layer; server saves remain the source of truth.
  }
}

function normalizeInspectionRecordForForm(inspection = {}) {
  return {
    scheduled_date: inspection.scheduled_date || "",
    scheduled_time: normalizeTimeInput(inspection.scheduled_time),
    end_time: normalizeTimeInput(inspection.end_time),
    status: inspection.status || "Draft",
    location_address: inspection.location_address || "",
    remarks: inspection.remarks || "",
    proof_files: inspection.proof_files || [],
  };
}

function mergeInspectionWithDraft(inspection, applicationId = selectedApplicationId) {
  const normalized = normalizeInspectionRecordForForm(inspection || {});
  const draft = readInspectionDraft(applicationId);
  if (!draft) {
    return normalized;
  }

  return {
    ...normalized,
    scheduled_date: Object.prototype.hasOwnProperty.call(draft, "scheduled_date") ? draft.scheduled_date : normalized.scheduled_date,
    scheduled_time: Object.prototype.hasOwnProperty.call(draft, "scheduled_time") ? normalizeTimeInput(draft.scheduled_time) : normalized.scheduled_time,
    end_time: Object.prototype.hasOwnProperty.call(draft, "end_time") ? normalizeTimeInput(draft.end_time) : normalized.end_time,
    status: draft.status || normalized.status || "Draft",
    location_address: Object.prototype.hasOwnProperty.call(draft, "location_address") ? draft.location_address : normalized.location_address,
    remarks: Object.prototype.hasOwnProperty.call(draft, "remarks") ? draft.remarks : normalized.remarks,
  };
}

function getInspectionProofFiles(form) {
  const savedFiles = workspaceCache[selectedApplicationId]?.inspection?.proof_files || [];
  const files = Array.from(form?.elements.inspectionProof?.files || []);
  if (!files.length) {
    return savedFiles;
  }
  return files.map((file) => ({
    name: file.name,
    size: file.size,
    type: file.type,
    savedAt: new Date().toISOString(),
  }));
}

function renderInspectionProofFiles(files = []) {
  const list = document.querySelector("[data-inspection-proof-list]");
  if (!list) {
    return;
  }
  if (!files.length) {
    list.hidden = true;
    list.textContent = "";
    return;
  }
  list.hidden = false;
  list.innerHTML = files
    .map((file) => `<span>${escapeHtml(file.name || "Inspection proof")}</span>`)
    .join("");
}

function collectInspectionPayload(form, statusOverride = "") {
  const application = getSelectedApplication();
  if (!application || !form) {
    return null;
  }
  const formData = new FormData(form);
  return {
    applicationId: application.applicationId,
    scheduledDate: formData.get("scheduledDate").toString(),
    scheduledTime: formData.get("scheduledTime").toString(),
    endTime: formData.get("endTime").toString(),
    locationAddress: formData.get("locationAddress").toString().trim(),
    status: statusOverride || formData.get("status").toString(),
    remarks: formData.get("remarks").toString().trim(),
    proofFiles: getInspectionProofFiles(form),
  };
}

async function saveInspectionScheduleFromForm(form, options = {}) {
  window.clearTimeout(inspectionAutosaveTimer);
  const payload = collectInspectionPayload(form, options.status || "");
  if (!payload) {
    return null;
  }

  writeInspectionDraft(payload.applicationId, payload);

  if (!payload.scheduledDate || !payload.scheduledTime) {
    if (options.requireSchedule) {
      throw new Error("Inspection date and start time are required.");
    }
    return null;
  }

  const result = await apiFetch("/department/api/inspections", {
    method: "POST",
    body: JSON.stringify({
      ...payload,
      silent: options.silent !== false,
    }),
  });
  workspaceCache[payload.applicationId] = {
    ...(workspaceCache[payload.applicationId] || {}),
    inspection: result.inspection,
  };
  return result;
}

function scheduleInspectionAutosave(form) {
  if (isPopulatingInspectionForm || !form || !selectedApplicationId) {
    return;
  }

  const payload = collectInspectionPayload(form);
  if (payload) {
    writeInspectionDraft(payload.applicationId, payload);
  }

  window.clearTimeout(inspectionAutosaveTimer);
  inspectionAutosaveTimer = window.setTimeout(async () => {
    try {
      const result = await saveInspectionScheduleFromForm(form);
      if (result?.inspection) {
        setStatus("Inspection scheduling details saved.");
      }
    } catch (error) {
      setStatus(error.message || "Unable to save inspection scheduling details.", true);
    }
  }, 700);
}

function formatDateTime(value) {
  if (!value) {
    return "-";
  }
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function renderEvidenceList(evidence = []) {
  const list = document.querySelector("[data-evidence-list]");
  if (!list) {
    return;
  }
  if (!evidence.length) {
    list.innerHTML = '<div class="record-item">No department evidence uploaded yet.</div>';
    return;
  }
  list.innerHTML = evidence.map((item) => `
    <div class="record-item evidence-record">
      <strong>${escapeHtml(item.fileName || "Evidence attachment")}</strong>
      <span>${escapeHtml(item.remarks || "No remarks")}</span>
      <small>Uploaded by ${escapeHtml(item.uploadedByName || "Department staff")} on ${escapeHtml(formatDateTime(item.createdAt))}</small>
      <div class="app-actions">
        <button class="btn" type="button" data-view-file="${escapeHtml(item.viewUrl)}" data-file-name="${escapeHtml(item.fileName)}">View</button>
        <button class="btn btn-blue" type="button" data-download-file="${escapeHtml(item.downloadUrl)}" data-file-name="${escapeHtml(item.fileName)}">Download</button>
        ${item.allowDelete ? `<button class="btn btn-danger" type="button" data-delete-evidence="${escapeHtml(item.id)}">Delete</button>` : ""}
      </div>
    </div>
  `).join("");
}

function populateAssessmentForm(items = [], item = null) {
  const form = document.querySelector("[data-assessment-form]");
  if (!form) {
    return;
  }
  const normalizedItems = Array.isArray(items) && items.length ? items : item ? [item] : [createEmptyAssessmentItem()];
  renderAssessmentRows(normalizedItems);
  form.elements.assessmentRemarks.value = normalizedItems[0]?.remarks || item?.remarks || "";
  syncAssessmentTotals();
}

function populateInspectionForm(inspection) {
  const form = document.querySelector("[data-staff-inspection-form]");
  if (!form) {
    return;
  }
  const application = getSelectedApplication();
  const payload = application?.application?.payload || {};
  const hasDraft = Boolean(readInspectionDraft(selectedApplicationId));
  const restoredInspection = mergeInspectionWithDraft(inspection, selectedApplicationId);
  isPopulatingInspectionForm = true;
  form.elements.scheduledDate.value = restoredInspection.scheduled_date || "";
  form.elements.scheduledTime.value = normalizeTimeInput(restoredInspection.scheduled_time);
  form.elements.endTime.value = normalizeTimeInput(restoredInspection.end_time);
  form.elements.status.value = restoredInspection.status || "Draft";
  form.elements.locationAddress.value = hasDraft || inspection?.location_address
    ? restoredInspection.location_address
    : payload.businessAddress || application?.applicant?.address || "";
  form.elements.remarks.value = restoredInspection.remarks || "";
  renderInspectionProofFiles(restoredInspection.proof_files || []);
  isPopulatingInspectionForm = false;
}

async function loadSelectedApplicationWorkspace(applicationId = selectedApplicationId) {
  if (!applicationId) {
    return null;
  }
  const result = await apiFetch(`/department/api/applications/${encodeURIComponent(applicationId)}/workspace`);
  workspaceCache[applicationId] = result;
  if (applicationId === selectedApplicationId) {
    populateAssessmentForm(result.assessmentItems, result.assessmentItem);
    populateInspectionForm(result.inspection);
    renderEvidenceList(result.evidence || []);
  }
  return result;
}

function setAssessmentSubmitModalOpen(isOpen) {
  const modal = document.querySelector("[data-assessment-submit-modal]");
  if (!modal) {
    return;
  }
  modal.hidden = !isOpen;
  document.body.style.overflow = isOpen ? "hidden" : "";
  if (isOpen) {
    modal.querySelector("[data-close-assessment-submit]")?.focus();
  }
}

function showAssessmentSubmitModal(form) {
  const application = getSelectedApplication();
  const items = collectAssessmentItems(form);
  const amount = items.reduce((sum, item) => sum + Number(item.amount || 0), 0);
  const penalty = items.reduce((sum, item) => sum + Number(item.penalty || 0), 0);
  const categories = new Set(items.map((item) => item.category).filter(Boolean));
  const values = {
    application: application?.referenceNumber || application?.businessName || "Selected application",
    description: items.length > 1 ? `${items.length} fee items` : items[0]?.feeName || "Department fee",
    category: categories.size > 1 ? "Multiple categories" : items[0]?.category || "-",
    amount: formatMoney(amount),
    penalty: formatMoney(penalty),
    total: formatMoney(amount + penalty),
  };

  Object.entries(values).forEach(([key, value]) => {
    document.querySelector(`[data-assessment-modal-${key}]`)?.replaceChildren(document.createTextNode(value));
  });
  setAssessmentSubmitModalOpen(true);
  window.lucide?.createIcons();
}

function setInspectionNotifyModalOpen(isOpen) {
  const modal = document.querySelector("[data-inspection-notify-modal]");
  if (!modal) {
    return;
  }
  modal.hidden = !isOpen;
  document.body.style.overflow = isOpen ? "hidden" : "";
  if (isOpen) {
    modal.querySelector("[data-confirm-inspection-notify]")?.focus();
  }
}

function getInspectionNotificationPayload(form) {
  const application = getSelectedApplication();
  if (!application || !form) {
    return null;
  }
  const formData = new FormData(form);
  return {
    applicationId: application.applicationId,
    applicationLabel: application.referenceNumber || application.businessName || "Selected application",
    scheduledDate: formData.get("scheduledDate").toString(),
    scheduledTime: formData.get("scheduledTime").toString(),
    endTime: formData.get("endTime").toString(),
    status: formData.get("status").toString(),
    locationAddress: formData.get("locationAddress").toString(),
    remarks: formData.get("remarks").toString().trim(),
  };
}

function showInspectionNotifyModal(payload) {
  const values = {
    application: payload.applicationLabel,
    date: payload.scheduledDate || "-",
    time: payload.scheduledTime || "-",
    "end-time": payload.endTime || "-",
    status: payload.status || "Draft",
    location: payload.locationAddress || "-",
  };

  Object.entries(values).forEach(([key, value]) => {
    document.querySelector(`[data-inspection-notify-${key}]`)?.replaceChildren(document.createTextNode(value));
  });
  const message = document.querySelector("[data-inspection-notify-message]");
  if (message) {
    message.textContent = "Notify the applicant and BPLO staff admin about this inspection schedule.";
    message.classList.remove("is-error", "is-ready");
  }
  const confirmButton = document.querySelector("[data-confirm-inspection-notify]");
  if (confirmButton) {
    confirmButton.hidden = false;
    confirmButton.style.display = "";
    confirmButton.disabled = false;
    confirmButton.textContent = "Send Notification";
  }
  setInspectionNotifyModalOpen(true);
  window.lucide?.createIcons();
}

function setCompletionModalOpen(isOpen) {
  const modal = document.querySelector("[data-completion-modal]");
  if (!modal) {
    return;
  }
  modal.hidden = !isOpen;
  document.body.style.overflow = isOpen ? "hidden" : "";
  if (isOpen) {
    modal.querySelector("[data-close-completion-modal]")?.focus();
  }
}

function showCompletionModal({ title, message, status }) {
  const application = getSelectedApplication();
  const values = {
    title: title || "Completed Successfully",
    message: message || "The selected application has been completed.",
    application: application?.referenceNumber || application?.businessName || "Selected application",
    status: status || "Complete",
  };

  document.querySelector("[data-completion-modal-title]")?.replaceChildren(document.createTextNode(values.title));
  document.querySelector("[data-completion-modal-message]")?.replaceChildren(document.createTextNode(values.message));
  document.querySelector("[data-completion-modal-application]")?.replaceChildren(document.createTextNode(values.application));
  document.querySelector("[data-completion-modal-status]")?.replaceChildren(document.createTextNode(values.status));
  setCompletionModalOpen(true);
  window.lucide?.createIcons();
}

function renderApplicationWorkspace() {
  const application = getSelectedApplication();
  const applicantNode = document.querySelector("[data-review-applicant-details]");
  const businessNode = document.querySelector("[data-review-business-profile]");
  if (!application || !applicantNode || !businessNode) {
    return;
  }

  selectedApplicationId = application.applicationId;
  const payload = application.application?.payload || {};
  const picker = document.querySelector("[data-application-picker]");
  if (picker) {
    picker.value = selectedApplicationId;
  }

  applicantNode.innerHTML = [
    appMiniCard("Applicant Name", application.applicant?.name || `${payload.firstName || ""} ${payload.lastName || ""}`.trim()),
    appMiniCard("Email", application.applicant?.email || payload.email),
    appMiniCard("Contact Number", application.applicant?.contact || payload.contactNumber),
    appMiniCard("Address", application.applicant?.address || payload.homeAddress),
  ].join("");

  businessNode.innerHTML = [
    appMiniCard("Business Name", application.businessName || payload.businessName),
    appMiniCard("Business Address", payload.businessAddress || application.applicant?.address),
    appMiniCard("Business Email", payload.businessEmail || application.applicant?.email),
    appMiniCard("Business Mobile", payload.businessMobile || application.applicant?.contact),
  ].join("");

  const locationInput = document.querySelector("[data-location-address]");
  if (locationInput) {
    locationInput.value = payload.businessAddress || application.applicant?.address || "";
  }
  populateAssessmentForm(null);
  populateInspectionForm(null);
  void loadSelectedApplicationWorkspace(selectedApplicationId).catch((error) => {
    setStatus(error.message || "Unable to load saved department form data.", true);
  });

  const evaluationForm = document.querySelector("[data-staff-evaluation-form]");
  if (evaluationForm) {
    evaluationForm.elements.remarks.value = application.remarks || "";
  }

  renderApplications(getFilteredApplications());
}

function detailCard(label, value) {
  return `<article class="detail-card"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value || "-")}</strong></article>`;
}

function renderRecordList(selector, records, formatter) {
  const node = document.querySelector(selector);
  if (!node) {
    return;
  }
  if (!records.length) {
    node.innerHTML = '<div class="record-item">No records yet.</div>';
    return;
  }
  node.innerHTML = records.map(formatter).join("");
}

async function loadApplicationDetails() {
  const applicationId = new URLSearchParams(window.location.search).get("id");
  if (!applicationId) {
    setStatus("Missing application id.", true);
    return;
  }

  const result = await apiFetch(`/department/api/applications/${encodeURIComponent(applicationId)}`);
  const application = result.application;
  const payload = application.application?.payload || {};
  document.querySelector("[data-detail-grid]").innerHTML = [
    detailCard("Reference Number", application.referenceNumber),
    detailCard("Business Name", application.businessName),
    detailCard("Status", application.status),
    detailCard("Applicant Name", application.applicant?.name),
    detailCard("Applicant Email", application.applicant?.email),
    detailCard("Applicant Contact", application.applicant?.contact),
    detailCard("Applicant Address", application.applicant?.address),
    detailCard("Submitted ID", application.application?.submittedId),
    `<article class="detail-card field-full"><span>Application Information</span><pre>${escapeHtml(JSON.stringify(payload, null, 2))}</pre></article>`,
  ].join("");

  const evaluationForm = document.querySelector("[data-evaluation-form]");
  evaluationForm.status.value = application.status || "Pending";
  evaluationForm.verificationStatus.value = application.verificationStatus || "Unverified";
  evaluationForm.remarks.value = application.remarks || "";

  renderRecordList("[data-remark-list]", result.remarks || [], (record) => `
    <div class="record-item">
      <strong>${statusPill(record.status)}</strong> ${escapeHtml(record.remark)}
      ${record.status === "Draft" ? `<button class="btn btn-danger" data-delete-remark="${record.id}">Delete draft</button>` : ""}
    </div>
  `);
  renderRecordList("[data-inspection-list]", result.inspections || [], (record) => `
    <div class="record-item">
      <strong>${statusPill(record.status)}</strong> ${escapeHtml(record.scheduled_date)} ${escapeHtml(record.scheduled_time || "")}<br />
      ${escapeHtml(record.remarks || "")}
      ${record.status === "Draft" ? `<button class="btn btn-danger" data-delete-inspection="${record.id}">Delete draft</button>` : ""}
    </div>
  `);
  renderRecordList("[data-verification-list]", result.verifications || [], (record) => `
    <div class="record-item"><strong>${statusPill(record.verification_status)}</strong> ${escapeHtml(record.remarks || "")}</div>
  `);

  bindDetailForms(applicationId);
  setStatus("Application details loaded.");
}

function bindDetailForms(applicationId) {
  const evaluationForm = document.querySelector("[data-evaluation-form]");
  evaluationForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const formData = new FormData(evaluationForm);
    const status = formData.get("status").toString();
    const remarks = formData.get("remarks").toString().trim();
    if (status === "Rejected" && !remarks) {
      setStatus("Remarks are required when rejecting an application.", true);
      return;
    }
    setStatus("Updating evaluation...");
    await apiFetch(`/department/api/applications/${encodeURIComponent(applicationId)}/evaluation`, {
      method: "PATCH",
      body: JSON.stringify({
        status,
        remarks,
        verificationStatus: formData.get("verificationStatus").toString(),
      }),
    });
    await loadApplicationDetails();
  }, { once: true });

  const remarkForm = document.querySelector("[data-remark-form]");
  remarkForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const formData = new FormData(remarkForm);
    const remark = formData.get("remark").toString().trim();
    if (!remark) {
      setStatus("Remark is required.", true);
      return;
    }
    await apiFetch("/department/api/remarks", {
      method: "POST",
      body: JSON.stringify({ applicationId, remark, status: formData.get("status").toString() }),
    });
    remarkForm.reset();
    await loadApplicationDetails();
  }, { once: true });

  const inspectionForm = document.querySelector("[data-inspection-form]");
  inspectionForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const formData = new FormData(inspectionForm);
    await apiFetch("/department/api/inspections", {
      method: "POST",
      body: JSON.stringify({
        applicationId,
        scheduledDate: formData.get("scheduledDate").toString(),
        scheduledTime: formData.get("scheduledTime").toString(),
        status: formData.get("status").toString(),
        remarks: formData.get("remarks").toString().trim(),
      }),
    });
    inspectionForm.reset();
    await loadApplicationDetails();
  }, { once: true });

  const verificationForm = document.querySelector("[data-verification-form]");
  verificationForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const formData = new FormData(verificationForm);
    await apiFetch("/department/api/verifications", {
      method: "POST",
      body: JSON.stringify({
        applicationId,
        status: formData.get("status").toString(),
        requirementId: formData.get("requirementId").toString().trim(),
        remarks: formData.get("remarks").toString().trim(),
      }),
    });
    verificationForm.reset();
    await loadApplicationDetails();
  }, { once: true });
}

async function loadRequirements() {
  const result = await apiFetch("/department/api/requirements");
  const table = document.querySelector("[data-requirements-table]");
  const list = document.querySelector("[data-requirements-list]");
  const requirements = result.requirements || [];
  if (table) {
    table.innerHTML = requirements.length
    ? requirements.map((record) => `
        <tr>
          <td>${escapeHtml(record.title)}<br /><small>${escapeHtml(record.description || "")}</small></td>
          <td>${statusPill(record.status)}</td>
          <td>${record.is_required ? "Required" : "Optional"}</td>
          <td><div class="action-row">
            <button class="btn" data-edit-requirement="${record.id}">Edit</button>
            ${record.status === "Draft" ? `<button class="btn btn-danger" data-delete-requirement="${record.id}">Delete draft</button>` : ""}
          </div></td>
        </tr>
      `).join("")
    : '<tr><td colspan="4" class="empty-state">No checklist records yet.</td></tr>';
    table.dataset.records = JSON.stringify(requirements);
  }
  if (list) {
    list.innerHTML = requirements.length
      ? requirements.map((record) => `
          <article class="requirement-item">
            <div>
              <strong>${escapeHtml(record.title)}</strong>
              <p>${escapeHtml(record.description || "No applicant instructions added yet.")}</p>
              <p>${statusPill(record.status)} ${record.is_required ? "Required" : "Optional"}</p>
            </div>
            <div class="requirement-item-actions">
              <button class="btn" data-edit-requirement="${record.id}">Edit</button>
              ${record.status === "Draft" ? `<button class="btn btn-danger" data-delete-requirement="${record.id}">Delete draft</button>` : ""}
            </div>
          </article>
        `).join("")
      : '<div class="selected-permit-empty">No requirements yet. Add the first document requirement for this permit type.</div>';
    list.dataset.records = JSON.stringify(requirements);
  }
  document.querySelectorAll("[data-requirement-count]").forEach((node) => {
    node.textContent = requirements.length;
  });
  setStatus("Requirements loaded.");
}

function bindRequirementPage() {
  const form = document.querySelector("[data-requirement-form]");
  document.querySelectorAll("[data-permit-type]").forEach((button) => {
    button.addEventListener("click", () => {
      document.querySelectorAll("[data-permit-type]").forEach((item) => item.classList.remove("is-active"));
      button.classList.add("is-active");
      if (form?.elements.permitType) {
        form.elements.permitType.value = button.dataset.permitType || "BP01";
      }
      const title = document.querySelector("[data-selected-permit-title]");
      if (title) {
        title.textContent = button.dataset.permitName || "Selected Permit";
      }
      document.querySelector("[data-requirement-empty]")?.classList.add("is-hidden");
    });
  });

  form?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const formData = new FormData(form);
    const id = formData.get("id").toString();
    const permitType = formData.get("permitType").toString() || "BP01";
    const description = formData.get("description").toString().trim();
    const payload = {
      title: formData.get("title").toString().trim(),
      description: `[${permitType}] ${description}`,
      status: formData.get("status").toString(),
      isRequired: formData.get("isRequired").toString() === "true",
    };
    if (!payload.title) {
      setStatus("Requirement title is required.", true);
      return;
    }
    await apiFetch(id ? `/department/api/requirements/${id}` : "/department/api/requirements", {
      method: id ? "PATCH" : "POST",
      body: JSON.stringify(payload),
    });
    form.reset();
    form.elements.permitType.value = document.querySelector("[data-permit-type].is-active")?.dataset.permitType || "BP01";
    await loadRequirements();
  });

  form?.addEventListener("reset", () => {
    window.setTimeout(() => {
      form.elements.id.value = "";
      form.elements.permitType.value = document.querySelector("[data-permit-type].is-active")?.dataset.permitType || "BP01";
    }, 0);
  });

  document.querySelector("[data-permit-type].is-active")?.click();
}

async function loadInspections() {
  const [applicationsResult, inspectionsResult] = await Promise.all([
    loadApplications(),
    apiFetch("/department/api/inspections"),
  ]);
  const options = document.querySelector("[data-application-options]");
  if (options) {
    options.innerHTML = (applicationsResult.applications || [])
      .map((application) => `<option value="${application.applicationId}">${escapeHtml(application.referenceNumber)} - ${escapeHtml(application.businessName)}</option>`)
      .join("");
  }

  inspectionCache = inspectionsResult.inspections || [];
  renderInspectionSchedule(inspectionCache);
  setStatus("Inspections loaded.");
}

function renderInspectionSchedule(inspections) {
  const table = document.querySelector("[data-inspections-table]");
  if (!table) {
    return;
  }

  if (!inspections.length) {
    table.innerHTML = '<tr><td colspan="9" class="empty-state">No inspections scheduled yet.</td></tr>';
    table.dataset.records = "[]";
    const countNode = document.querySelector("[data-inspection-entry-count]");
    if (countNode) {
      countNode.textContent = "Showing 0 entries";
    }
    return;
  }

  table.innerHTML = inspections.map((record, index) => {
    const application = findApplicationById(record.application_id);
    const payload = application?.application?.payload || {};
    const applicant = application?.applicant?.name || application?.applicant?.email || "Unassigned applicant";
    const location = payload.businessAddress || application?.applicant?.address || record.remarks || "No location yet";
    const inspectionType = currentUser?.departmentName || "Department Inspection";
    return `
      <tr>
        <td>${escapeHtml(`INS-${new Date(record.created_at || Date.now()).getFullYear()}-${String(index + 1).padStart(3, "0")}`)}</td>
        <td>${escapeHtml(applicant)}</td>
        <td>${escapeHtml(location)}</td>
        <td>${escapeHtml(inspectionType)}</td>
        <td>${escapeHtml(formatInspectionDate(record.scheduled_date))}</td>
        <td>${escapeHtml(formatInspectionTime(record.scheduled_time || ""))}</td>
        <td>${inspectionStatusPill(record.status)}</td>
        <td>${escapeHtml(currentUser?.name || "Staff")}</td>
        <td>
          <button class="inspection-action-button" type="button" data-edit-inspection="${record.id}" aria-label="Edit inspection">
            <i data-lucide="more-vertical"></i>
          </button>
          ${record.status === "Draft" ? `<button class="btn btn-danger" data-delete-inspection="${record.id}">Delete draft</button>` : ""}
        </td>
      </tr>
    `;
  }).join("");
  table.dataset.records = JSON.stringify(inspections);
  const countNode = document.querySelector("[data-inspection-entry-count]");
  if (countNode) {
    countNode.textContent = `Showing 1 to ${inspections.length} of ${inspectionCache.length} entries`;
  }
  window.lucide?.createIcons();
}

function applyInspectionFilters() {
  const query = (document.querySelector("[data-inspection-search]")?.value || "").toLowerCase();
  const filtered = inspectionCache.filter((record) => {
    const application = findApplicationById(record.application_id);
    const payload = application?.application?.payload || {};
    const haystack = [
      record.id,
      application?.referenceNumber,
      application?.businessName,
      application?.applicant?.name,
      application?.applicant?.email,
      payload.businessAddress,
      record.remarks,
      record.status,
    ].join(" ").toLowerCase();
    return haystack.includes(query);
  });
  renderInspectionSchedule(filtered);
}

async function loadReports() {
  await loadApplications();
  const result = await apiFetch("/department/api/reports");
  reportCache = result.reports || [];
  renderReports(reportCache);
  setStatus("Reports loaded.");
}

function reportStatusPill(status) {
  return `<span class="status-pill ${statusClass(status)}">${escapeHtml(status || "-")}</span>`;
}

function calculateReportCounts(reports) {
  const appCounts = applicationCache.reduce((counts, application) => {
    counts.total += 1;
    if (application.status === "Approved") counts.approved += 1;
    if (application.status === "Pending") counts.pending += 1;
    if (application.status === "Rejected") counts.revision += 1;
    return counts;
  }, { total: 0, approved: 0, pending: 0, revision: 0 });

  return {
    total: reports.length + appCounts.total,
    completed: reports.filter((report) => report.status === "Completed").length + inspectionCache.filter((inspection) => inspection.status === "Completed").length,
    pending: reports.filter((report) => report.status === "Pending").length + appCounts.pending,
    approved: reports.filter((report) => report.status === "Approved").length + appCounts.approved,
    revision: reports.filter((report) => report.status === "For Revision").length + appCounts.revision,
  };
}

function renderReportWidgets(reports) {
  const counts = calculateReportCounts(reports);
  Object.entries(counts).forEach(([key, value]) => {
    document.querySelectorAll(`[data-report-count="${key}"]`).forEach((node) => {
      node.textContent = value.toLocaleString();
    });
  });

  const bars = document.querySelector("[data-report-bars]");
  if (bars) {
    const values = [820, 950, 1020, 1110, 1230, Math.max(counts.total, 1)];
    const labels = ["Dec 2023", "Jan 2024", "Feb 2024", "Mar 2024", "Apr 2024", "May 2024"];
    const max = Math.max(...values);
    bars.innerHTML = values.map((value, index) => `
      <span class="bar-item ${index === values.length - 1 ? "is-current" : ""}">
        <strong>${value.toLocaleString()}</strong>
        <em style="height: ${Math.max(18, Math.round((value / max) * 96))}px"></em>
        <small>${labels[index]}</small>
      </span>
    `).join("");
  }

  const breakdown = document.querySelector("[data-report-breakdown]");
  if (breakdown) {
    const rows = [
      ["Completed", counts.completed, "#4ade80"],
      ["Pending", counts.pending, "#facc15"],
      ["Approved", counts.approved, "#60a5fa"],
      ["For Revision", counts.revision, "#f87171"],
    ];
    const total = Math.max(counts.total, 1);
    breakdown.innerHTML = rows.map(([label, value, color]) => `
      <div class="breakdown-row">
        <em style="background:${color}"></em>
        <span>${label}</span>
        <strong>${Number(value).toLocaleString()}</strong>
        <span>${Math.round((Number(value) / total) * 1000) / 10}%</span>
      </div>
    `).join("");
  }
}

function renderReports(reports) {
  const table = document.querySelector("[data-reports-table]");
  if (!table) {
    return;
  }

  renderReportWidgets(reports);

  if (!reports.length) {
    table.innerHTML = '<tr><td colspan="7" class="empty-state">No reports yet.</td></tr>';
    table.dataset.records = "[]";
    document.querySelector("[data-report-entry-count]").textContent = "Showing 0 reports";
    return;
  }

  table.innerHTML = reports.map((report, index) => `
    <tr>
      <td>${escapeHtml(`RPT-${new Date(report.created_at || Date.now()).getFullYear()}-${String(index + 1).padStart(5, "0")}`)}</td>
      <td>${escapeHtml(report.applicant_name)}</td>
      <td>${escapeHtml(report.business_name)}</td>
      <td>${escapeHtml(report.report_type)}</td>
      <td>${escapeHtml(formatInspectionDate(report.report_date))}</td>
      <td>${reportStatusPill(report.status)}</td>
      <td>
        <div class="report-action-row">
          <button class="report-icon-button" type="button" data-edit-report="${report.id}" aria-label="Edit report"><i data-lucide="eye"></i></button>
          ${report.status === "Draft" ? `<button class="btn btn-danger" data-delete-report="${report.id}">Delete draft</button>` : ""}
        </div>
      </td>
    </tr>
  `).join("");
  table.dataset.records = JSON.stringify(reports);
  document.querySelector("[data-report-entry-count]").textContent = `Showing 1 to ${reports.length} of ${reportCache.length} reports`;
  window.lucide?.createIcons();
}

function applyReportFilters() {
  const search = (document.querySelector("[data-report-search]")?.value || "").toLowerCase();
  const status = document.querySelector("[data-report-status-filter]")?.value || "";
  const type = document.querySelector("[data-report-type-filter]")?.value || "";
  const filtered = reportCache.filter((report) => {
    const haystack = `${report.applicant_name} ${report.business_name} ${report.report_type} ${report.status}`.toLowerCase();
    return haystack.includes(search) && (!status || report.status === status) && (!type || report.report_type === type);
  });
  renderReports(filtered);
}

function bindReportsPage() {
  const form = document.querySelector("[data-report-form]");
  document.querySelector("[data-toggle-report-form]")?.addEventListener("click", () => {
    form.hidden = !form.hidden;
    if (!form.hidden) {
      form.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  });
  document.querySelector("[data-report-search]")?.addEventListener("input", applyReportFilters);
  document.querySelector("[data-report-status-filter]")?.addEventListener("change", applyReportFilters);
  document.querySelector("[data-report-type-filter]")?.addEventListener("change", applyReportFilters);
  document.querySelectorAll("[data-department-export]").forEach((button) => {
    button.addEventListener("click", async () => {
      const format = button.dataset.departmentExport === "pdf" ? "pdf" : "csv";
      setStatus("Preparing report export...");
      const activeSession = session;
      const response = await fetch(`/department/api/reports/export?format=${encodeURIComponent(format)}`, {
        headers: { "Authorization": `Bearer ${activeSession.access_token}` },
      });
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        throw new Error(payload.error || "Unable to export report.");
      }
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = format === "pdf" ? "department-report.html" : "department-report.csv";
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
      setStatus("Report export downloaded.");
    });
  });

  form?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const formData = new FormData(form);
    const id = formData.get("id").toString();
    const payload = {
      applicantName: formData.get("applicantName").toString().trim(),
      businessName: formData.get("businessName").toString().trim(),
      reportType: formData.get("reportType").toString(),
      reportDate: formData.get("reportDate").toString(),
      status: formData.get("status").toString(),
      remarks: formData.get("remarks").toString().trim(),
    };
    await apiFetch(id ? `/department/api/reports/${encodeURIComponent(id)}` : "/department/api/reports", {
      method: id ? "PATCH" : "POST",
      body: JSON.stringify(payload),
    });
    form.reset();
    form.hidden = true;
    await loadReports();
  });

  form?.addEventListener("reset", () => {
    window.setTimeout(() => {
      form.elements.id.value = "";
    }, 0);
  });
}

function bindInspectionPage() {
  document.querySelector("[data-toggle-inspection-form]")?.addEventListener("click", () => {
    const panel = document.querySelector("[data-inspection-create-panel]");
    if (panel) {
      panel.hidden = !panel.hidden;
      if (!panel.hidden) {
        panel.scrollIntoView({ behavior: "smooth", block: "start" });
      }
    }
  });

  document.querySelector("[data-inspection-search]")?.addEventListener("input", applyInspectionFilters);

  const form = document.querySelector("[data-global-inspection-form]");
  form?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const formData = new FormData(form);
    const id = formData.get("id").toString();
    const payload = {
      applicationId: formData.get("applicationId").toString(),
      scheduledDate: formData.get("scheduledDate").toString(),
      scheduledTime: formData.get("scheduledTime").toString(),
      status: formData.get("status").toString(),
      remarks: formData.get("remarks").toString().trim(),
    };
    if (!payload.applicationId || !payload.scheduledDate || !payload.scheduledTime) {
      setStatus("Application, date, and time are required.", true);
      return;
    }
    await apiFetch(id ? `/department/api/inspections/${id}` : "/department/api/inspections", {
      method: id ? "PATCH" : "POST",
      body: JSON.stringify(payload),
    });
    form.reset();
    document.querySelector("[data-inspection-create-panel]")?.setAttribute("hidden", "");
    await loadInspections();
  });
}

function bindApplicationsWorkspace() {
  const picker = document.querySelector("[data-application-picker]");
  picker?.addEventListener("change", () => {
    selectedApplicationId = picker.value;
    renderApplicationWorkspace();
  });

  const assessmentForm = document.querySelector("[data-assessment-form]");
  renderAssessmentRows();
  assessmentForm?.addEventListener("input", syncAssessmentTotals);
  assessmentForm?.addEventListener("click", (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) {
      return;
    }
    if (target.closest("[data-add-assessment-row]")) {
      addAssessmentRow();
      return;
    }
    const removeButton = target.closest("[data-remove-assessment-row]");
    if (removeButton instanceof HTMLElement) {
      removeButton.closest("[data-assessment-row]")?.remove();
      if (!getAssessmentRows().length) {
        renderAssessmentRows();
      } else {
        updateAssessmentRowActions();
        window.lucide?.createIcons();
      }
      syncAssessmentTotals();
    }
  });
  assessmentForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const application = getSelectedApplication();
    if (!application) {
      setStatus("Select an application before saving assessment.", true);
      return;
    }
    syncAssessmentTotals();
    const formData = new FormData(assessmentForm);
    const items = collectAssessmentItems(assessmentForm);
    if (!items.length) {
      setStatus("Add at least one fee item before saving assessment.", true);
      return;
    }
    setStatus("Saving department assessment...");
    const result = await apiFetch(`/department/api/applications/${encodeURIComponent(application.applicationId)}/assessment`, {
      method: "POST",
      body: JSON.stringify({
        applicationId: application.applicationId,
        remarks: formData.get("assessmentRemarks").toString().trim(),
        items,
      }),
    });
    workspaceCache[application.applicationId] = {
      ...(workspaceCache[application.applicationId] || {}),
      assessment: result.assessment,
      assessmentItems: result.items || [],
      assessmentItem: result.item,
    };
    populateAssessmentForm(result.items, result.item);
    showAssessmentSubmitModal(assessmentForm);
    setStatus(result.message || "Department assessment saved.");
  });

  document.querySelectorAll("[data-close-assessment-submit]").forEach((button) => {
    button.addEventListener("click", () => setAssessmentSubmitModalOpen(false));
  });

  document.querySelector("[data-assessment-submit-modal]")?.addEventListener("click", (event) => {
    if (event.target === event.currentTarget) {
      setAssessmentSubmitModalOpen(false);
    }
  });

  document.querySelector("[data-preview-assessment]")?.addEventListener("click", () => {
    syncAssessmentTotals();
    setStatus("Assessment preview generated.");
  });

  const staffInspectionForm = document.querySelector("[data-staff-inspection-form]");
  staffInspectionForm?.addEventListener("input", () => scheduleInspectionAutosave(staffInspectionForm));
  staffInspectionForm?.addEventListener("change", () => scheduleInspectionAutosave(staffInspectionForm));

  document.querySelector("[data-notify-inspection]")?.addEventListener("click", () => {
    const application = getSelectedApplication();
    if (!application) {
      setStatus("Select an application before sending inspection notification.", true);
      return;
    }
    if (!staffInspectionForm) {
      setStatus("Inspection form is unavailable.", true);
      return;
    }

    const formData = new FormData(staffInspectionForm);
    const scheduledDate = formData.get("scheduledDate").toString();
    const scheduledTime = formData.get("scheduledTime").toString();
    if (!scheduledDate || !scheduledTime) {
      setStatus("Inspection date and start time are required before notifying.", true);
      return;
    }

    void saveInspectionScheduleFromForm(staffInspectionForm, { requireSchedule: true })
      .then(() => showInspectionNotifyModal(getInspectionNotificationPayload(staffInspectionForm)))
      .catch((error) => setStatus(error.message || "Unable to save inspection scheduling details.", true));
  });

  document.querySelectorAll("[data-close-inspection-notify]").forEach((button) => {
    button.addEventListener("click", () => setInspectionNotifyModalOpen(false));
  });

  document.querySelector("[data-inspection-notify-modal]")?.addEventListener("click", (event) => {
    if (event.target === event.currentTarget) {
      setInspectionNotifyModalOpen(false);
    }
  });

  document.querySelectorAll("[data-close-completion-modal]").forEach((button) => {
    button.addEventListener("click", () => setCompletionModalOpen(false));
  });

  document.querySelector("[data-completion-modal]")?.addEventListener("click", (event) => {
    if (event.target === event.currentTarget) {
      setCompletionModalOpen(false);
    }
  });

  document.querySelector("[data-confirm-inspection-notify]")?.addEventListener("click", async () => {
    const payload = getInspectionNotificationPayload(staffInspectionForm);
    const message = document.querySelector("[data-inspection-notify-message]");
    const confirmButton = document.querySelector("[data-confirm-inspection-notify]");
    if (!payload?.scheduledDate || !payload?.scheduledTime) {
      setStatus("Inspection date and start time are required before notifying.", true);
      setInspectionNotifyModalOpen(false);
      return;
    }

    if (confirmButton) {
      confirmButton.disabled = true;
      confirmButton.textContent = "Sending...";
    }
    if (message) {
      message.textContent = "Sending notification...";
      message.classList.remove("is-error");
    }

    try {
      setStatus("Sending inspection notification...");
      const result = await apiFetch("/department/api/inspection-notifications", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      setStatus(result.message || "Inspection notification sent.");
      if (message) {
        message.textContent = result.message || "Inspection notification sent to the applicant and BPLO staff.";
        message.classList.add("is-ready");
      }
      if (confirmButton) {
        confirmButton.textContent = "Sent";
        confirmButton.style.display = "none";
      }
      window.setTimeout(() => setInspectionNotifyModalOpen(false), 700);
    } catch (error) {
      setStatus(error.message || "Unable to send inspection notification.", true);
      if (message) {
        message.textContent = error.message || "Unable to send inspection notification.";
        message.classList.add("is-error");
      }
      if (confirmButton) {
        confirmButton.style.display = "";
        confirmButton.disabled = false;
        confirmButton.textContent = "Try Again";
      }
    }
  });

  staffInspectionForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const application = getSelectedApplication();
    if (!application) {
      setStatus("Select an application before scheduling inspection.", true);
      return;
    }

    const formData = new FormData(staffInspectionForm);
    const scheduledDate = formData.get("scheduledDate").toString();
    const scheduledTime = formData.get("scheduledTime").toString();
    if (!scheduledDate || !scheduledTime) {
      setStatus("Inspection date and start time are required.", true);
      return;
    }

    const status = event.submitter?.dataset?.inspectionStatus || formData.get("status").toString();
    setStatus("Saving inspection schedule...");
    await saveInspectionScheduleFromForm(staffInspectionForm, { status, requireSchedule: true, silent: false });
    const workspace = await loadSelectedApplicationWorkspace(application.applicationId);
    renderInspectionProofFiles(workspace?.inspection?.proof_files || []);
    setStatus("Inspection schedule saved.");
    if (status === "Completed") {
      showCompletionModal({
        title: "Inspection Completed",
        message: "The inspection has been marked as completed for this application.",
        status,
      });
    }
  });

  staffInspectionForm?.elements.inspectionProof?.addEventListener("change", () => {
    renderInspectionProofFiles(getInspectionProofFiles(staffInspectionForm));
  });

  const evaluationForm = document.querySelector("[data-staff-evaluation-form]");
  evaluationForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const application = getSelectedApplication();
    if (!application) {
      setStatus("Select an application before updating status.", true);
      return;
    }

    const submitter = event.submitter;
    const status = submitter?.dataset?.evaluationStatus || "Pending";
    const remarks = new FormData(evaluationForm).get("remarks").toString().trim();
    if (status === "Rejected" && !remarks) {
      setStatus("Remarks are required when rejecting an application.", true);
      return;
    }

    setStatus("Updating application status...");
    await apiFetch(`/department/api/applications/${encodeURIComponent(application.applicationId)}/evaluation`, {
      method: "PATCH",
      body: JSON.stringify({
        status,
        remarks,
        verificationStatus: status === "Approved" ? "Verified" : "Pending",
      }),
    });
    await loadApplications();
    selectedApplicationId = application.applicationId;
    populateApplicationPicker(applicationCache);
    renderApplicationWorkspace();
    setStatus(`Application marked as ${status}.`);
    if (status === "Approved") {
      showCompletionModal({
        title: "Department Review Complete",
        message: "The application has been approved by your department.",
        status,
      });
    }
  });

  bindEvidenceModal();
  bindDocumentRequestModal();
}

function setDocumentRequestModalOpen(isOpen) {
  const modal = document.querySelector("[data-document-request-modal]");
  if (!modal) {
    return;
  }
  modal.hidden = !isOpen;
  document.body.style.overflow = isOpen ? "hidden" : "";

  if (isOpen) {
    window.setTimeout(() => {
      modal.querySelector("select, input, textarea, button")?.focus();
    }, 0);
  }
}

function setEvidenceModalOpen(isOpen) {
  const modal = document.querySelector("[data-evidence-modal]");
  if (!modal) {
    return;
  }
  modal.hidden = !isOpen;
  document.body.style.overflow = isOpen ? "hidden" : "";
  if (isOpen) {
    modal.querySelector("input, textarea, button")?.focus();
  }
}

function bindEvidenceModal() {
  const modal = document.querySelector("[data-evidence-modal]");
  const form = document.querySelector("[data-evidence-form]");
  if (!modal || !form) {
    return;
  }

  document.querySelectorAll("[data-open-evidence-upload]").forEach((button) => {
    button.addEventListener("click", () => {
      const application = getSelectedApplication();
      if (!application) {
        setStatus("Select an application before uploading evidence.", true);
        return;
      }
      form.reset();
      document.querySelector("[data-evidence-application-label]")?.replaceChildren(
        document.createTextNode(application.referenceNumber || application.businessName || "Selected application")
      );
      setEvidenceModalOpen(true);
    });
  });

  modal.querySelectorAll("[data-close-evidence-modal]").forEach((button) => {
    button.addEventListener("click", () => setEvidenceModalOpen(false));
  });

  modal.addEventListener("click", (event) => {
    if (event.target === modal) {
      setEvidenceModalOpen(false);
    }
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const application = getSelectedApplication();
    if (!application) {
      setStatus("Select an application before uploading evidence.", true);
      return;
    }
    const file = form.elements.file?.files?.[0];
    if (!file) {
      setStatus("Evidence file is required.", true);
      return;
    }
    if (file.size > 10 * 1024 * 1024) {
      setStatus("Evidence file must be 10 MB or smaller.", true);
      return;
    }
    const submitButton = form.querySelector('[type="submit"]');
    if (submitButton) {
      submitButton.disabled = true;
      submitButton.textContent = "Uploading...";
    }
    try {
      const body = new FormData(form);
      setStatus("Uploading evidence...");
      await apiFetch(`/department/api/applications/${encodeURIComponent(application.applicationId)}/evidence`, {
        method: "POST",
        body,
      });
      setEvidenceModalOpen(false);
      await loadSelectedApplicationWorkspace(application.applicationId);
      setStatus("Evidence uploaded.");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Unable to upload evidence.", true);
    } finally {
      if (submitButton) {
        submitButton.disabled = false;
        submitButton.textContent = "Upload Evidence";
      }
    }
  });
}

function bindDocumentRequestModal() {
  const openButton = document.querySelector("[data-open-document-request]");
  const modal = document.querySelector("[data-document-request-modal]");
  const form = document.querySelector("[data-document-request-form]");
  if (!openButton || !modal || !form) {
    return;
  }

  openButton.addEventListener("click", () => {
    const application = getSelectedApplication();
    if (!application) {
      setStatus("Select an application before requesting documents.", true);
      return;
    }
    setDocumentRequestModalOpen(true);
  });

  modal.querySelectorAll("[data-close-document-request]").forEach((button) => {
    button.addEventListener("click", () => {
      setDocumentRequestModalOpen(false);
    });
  });

  modal.addEventListener("click", (event) => {
    if (event.target === modal) {
      setDocumentRequestModalOpen(false);
    }
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !modal.hidden) {
      setDocumentRequestModalOpen(false);
    }
  });

  modal.querySelector("[data-add-document-row]")?.addEventListener("click", () => {
    setStatus("One document request can be sent now. Multiple document rows can be connected next.");
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const application = getSelectedApplication();
    if (!application) {
      setStatus("Select an application before requesting documents.", true);
      return;
    }

    const formData = new FormData(form);
    const documentType = formData.get("documentType").toString().trim();
    const customDocumentName = formData.get("customDocumentName").toString().trim();
    const reason = formData.get("reason").toString().trim();

    if (!documentType && !customDocumentName) {
      setStatus("Select a document or enter a custom document name.", true);
      return;
    }

    if (!reason) {
      setStatus("Reason or instructions are required.", true);
      return;
    }

    const requestedDocument = customDocumentName || documentType;
    const details = {
      requestedDocument,
      documentType,
      customDocumentName,
      documentNotes: formData.get("documentNotes").toString().trim(),
      applicantMustUpload: formData.get("applicantMustUpload") === "on",
      municipalSource: formData.get("municipalSource").toString().trim(),
      reason,
      deadline: formData.get("deadline").toString(),
      referenceNumber: application.referenceNumber,
      businessName: application.businessName,
    };

    await apiFetch("/department/api/remarks", {
      method: "POST",
      body: JSON.stringify({
        applicationId: application.applicationId,
        status: "Submitted",
        remark: `Additional document requested: ${requestedDocument}. ${reason}`,
      }),
    });

    setDocumentRequestModalOpen(false);
    form.reset();
    form.elements.applicantMustUpload.checked = true;
    setStatus(`Additional document request sent for ${application.referenceNumber}.`);
  });
}

function bindFilePreviewModal() {
  const modal = document.querySelector("[data-file-preview-modal]");
  if (!modal) {
    return;
  }

  modal.querySelectorAll("[data-close-file-preview]").forEach((button) => {
    button.addEventListener("click", closeFilePreviewModal);
  });

  modal.addEventListener("click", (event) => {
    if (event.target === modal) {
      closeFilePreviewModal();
    }
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !modal.hidden) {
      closeFilePreviewModal();
    }
  });
}

function bindTableActions() {
  document.addEventListener("click", async (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) {
      return;
    }

    const selectedId = target.dataset.selectApplication;
    if (selectedId) {
      selectedApplicationId = selectedId;
      renderApplicationWorkspace();
      return;
    }

    const viewFilePath = target.dataset.viewFile;
    if (viewFilePath) {
      try {
        await openAuthenticatedFile(viewFilePath, target.dataset.fileName || "document", "view");
      } catch (error) {
        setStatus(error.message || "Unable to preview file.", true);
      }
      return;
    }

    const downloadFilePath = target.dataset.downloadFile;
    if (downloadFilePath) {
      await openAuthenticatedFile(downloadFilePath, target.dataset.fileName || "document", "download");
      return;
    }

    const requirementId = target.dataset.editRequirement;
    if (requirementId) {
      const recordsNode = document.querySelector("[data-requirements-list]") || document.querySelector("[data-requirements-table]");
      const record = JSON.parse(recordsNode?.dataset.records || "[]").find((item) => item.id === requirementId);
      const form = document.querySelector("[data-requirement-form]");
      if (record && form) {
        form.elements.id.value = record.id;
        form.elements.title.value = record.title || "";
        form.elements.description.value = (record.description || "").replace(/^\[[^\]]+\]\s*/, "");
        form.elements.status.value = record.status || "Draft";
        form.elements.isRequired.value = record.is_required ? "true" : "false";
        form.scrollIntoView({ behavior: "smooth", block: "start" });
      }
    }

    const inspectionId = target.dataset.editInspection;
    if (inspectionId) {
      const table = document.querySelector("[data-inspections-table]");
      const record = JSON.parse(table?.dataset.records || "[]").find((item) => item.id === inspectionId);
      const form = document.querySelector("[data-global-inspection-form]");
      if (record && form) {
        const panel = document.querySelector("[data-inspection-create-panel]");
        if (panel) {
          panel.hidden = false;
        }
        form.elements.id.value = record.id;
        form.elements.applicationId.value = record.application_id || "";
        form.elements.scheduledDate.value = record.scheduled_date || "";
        form.elements.scheduledTime.value = (record.scheduled_time || "").slice(0, 5);
        form.elements.status.value = record.status || "Draft";
        form.elements.remarks.value = record.remarks || "";
        form.scrollIntoView({ behavior: "smooth", block: "start" });
      }
    }

    const reportId = target.dataset.editReport;
    if (reportId) {
      const table = document.querySelector("[data-reports-table]");
      const record = JSON.parse(table?.dataset.records || "[]").find((item) => item.id === reportId);
      const form = document.querySelector("[data-report-form]");
      if (record && form) {
        form.hidden = false;
        form.elements.id.value = record.id;
        form.elements.applicantName.value = record.applicant_name || "";
        form.elements.businessName.value = record.business_name || "";
        form.elements.reportType.value = record.report_type || "Site Inspection Report";
        form.elements.reportDate.value = record.report_date || "";
        form.elements.status.value = record.status || "Pending";
        form.elements.remarks.value = record.remarks || "";
        form.scrollIntoView({ behavior: "smooth", block: "start" });
      }
    }

    const deleteMap = [
      ["deleteRequirement", "/department/api/requirements/", loadRequirements],
      ["deleteInspection", "/department/api/inspections/", page === "inspections" ? loadInspections : loadApplicationDetails],
      ["deleteRemark", "/department/api/remarks/", loadApplicationDetails],
      ["deleteReport", "/department/api/reports/", loadReports],
    ];
    for (const [key, path, reload] of deleteMap) {
      const id = target.dataset[key];
      if (id) {
        await apiFetch(`${path}${encodeURIComponent(id)}`, { method: "DELETE" });
        await reload();
      }
    }

    const evidenceId = target.dataset.deleteEvidence;
    if (evidenceId) {
      if (!window.confirm("Delete this evidence attachment?")) {
        return;
      }
      await apiFetch(`/department/api/evidence/${encodeURIComponent(evidenceId)}`, { method: "DELETE" });
      await loadSelectedApplicationWorkspace(selectedApplicationId);
      setStatus("Evidence deleted.");
    }
  });
}

async function loadSettings() {
  const result = await apiFetch("/department/api/settings");
  settingsCache = result.settings || {};
  renderSettings();
  setStatus("Settings loaded.");
}

function setFormValue(form, name, value) {
  const field = form?.elements?.[name];
  if (!field) return;
  if (field.type === "checkbox") {
    field.checked = Boolean(value);
  } else {
    field.value = value ?? "";
  }
}

function getFormValue(form, name) {
  const field = form?.elements?.[name];
  if (!field) return "";
  return field.type === "checkbox" ? field.checked : field.value.trim();
}

function renderSettings() {
  const form = document.querySelector("[data-settings-form]");
  if (!form || !settingsCache) {
    return;
  }
  const profile = settingsCache.profile_settings || {};
  const office = settingsCache.office_information || {};
  const notifications = settingsCache.notification_settings || {};
  const inspection = settingsCache.inspection_settings || {};
  const report = settingsCache.report_settings || {};
  const security = settingsCache.security_settings || {};

  setFormValue(form, "profile.staffName", profile.staffName || currentUser?.name);
  setFormValue(form, "profile.departmentOffice", profile.departmentOffice || currentUser?.departmentName);
  setFormValue(form, "profile.emailAddress", profile.emailAddress || currentUser?.email);
  setFormValue(form, "profile.positionRole", profile.positionRole);
  setFormValue(form, "profile.contactNumber", profile.contactNumber);

  setFormValue(form, "office.officeName", office.officeName || currentUser?.departmentName);
  setFormValue(form, "office.officeEmail", office.officeEmail || currentUser?.email);
  setFormValue(form, "office.officeHead", office.officeHead);
  setFormValue(form, "office.officeAddress", office.officeAddress);
  setFormValue(form, "office.officeContactNumber", office.officeContactNumber);

  Object.entries({
    "notifications.newApplicationAssigned": notifications.newApplicationAssigned,
    "notifications.newDocumentUploaded": notifications.newDocumentUploaded,
    "notifications.inspectionScheduleReminder": notifications.inspectionScheduleReminder,
    "notifications.applicantResubmission": notifications.applicantResubmission,
    "notifications.bploAdminUpdates": notifications.bploAdminUpdates,
    "notifications.emailNotifications": notifications.emailNotifications,
    "notifications.systemNotifications": notifications.systemNotifications,
  }).forEach(([name, value]) => setFormValue(form, name, value));

  setFormValue(form, "inspection.defaultInspectionDuration", inspection.defaultInspectionDuration);
  setFormValue(form, "inspection.maximumInspectionsPerDay", inspection.maximumInspectionsPerDay);
  setFormValue(form, "inspection.availableInspectionDays", inspection.availableInspectionDays);
  setFormValue(form, "inspection.defaultAssignedInspector", inspection.defaultAssignedInspector);
  setFormValue(form, "inspection.availableInspectionTime", inspection.availableInspectionTime);

  setFormValue(form, "report.defaultReportFormat", report.defaultReportFormat);
  setFormValue(form, "report.includeOfficeLogo", report.includeOfficeLogo);
  setFormValue(form, "report.includeInspectorSignature", report.includeInspectorSignature);
  setFormValue(form, "report.reportHeaderText", report.reportHeaderText);
  setFormValue(form, "report.reportFooterText", report.reportFooterText);
  setFormValue(form, "security.twoStepVerification", security.twoStepVerification);

  const lastLogin = document.querySelector("[data-last-login]");
  if (lastLogin) {
    lastLogin.textContent = security.lastLogin || new Date().toLocaleString();
  }
}

function collectSettingsPayload(form) {
  return {
    profile_settings: {
      staffName: getFormValue(form, "profile.staffName"),
      departmentOffice: getFormValue(form, "profile.departmentOffice"),
      emailAddress: getFormValue(form, "profile.emailAddress"),
      positionRole: getFormValue(form, "profile.positionRole"),
      contactNumber: getFormValue(form, "profile.contactNumber"),
    },
    office_information: {
      officeName: getFormValue(form, "office.officeName"),
      officeEmail: getFormValue(form, "office.officeEmail"),
      officeHead: getFormValue(form, "office.officeHead"),
      officeAddress: getFormValue(form, "office.officeAddress"),
      officeContactNumber: getFormValue(form, "office.officeContactNumber"),
    },
    notification_settings: {
      newApplicationAssigned: getFormValue(form, "notifications.newApplicationAssigned"),
      newDocumentUploaded: getFormValue(form, "notifications.newDocumentUploaded"),
      inspectionScheduleReminder: getFormValue(form, "notifications.inspectionScheduleReminder"),
      applicantResubmission: getFormValue(form, "notifications.applicantResubmission"),
      bploAdminUpdates: getFormValue(form, "notifications.bploAdminUpdates"),
      emailNotifications: getFormValue(form, "notifications.emailNotifications"),
      systemNotifications: getFormValue(form, "notifications.systemNotifications"),
    },
    inspection_settings: {
      defaultInspectionDuration: getFormValue(form, "inspection.defaultInspectionDuration"),
      maximumInspectionsPerDay: getFormValue(form, "inspection.maximumInspectionsPerDay"),
      availableInspectionDays: getFormValue(form, "inspection.availableInspectionDays"),
      defaultAssignedInspector: getFormValue(form, "inspection.defaultAssignedInspector"),
      availableInspectionTime: getFormValue(form, "inspection.availableInspectionTime"),
    },
    report_settings: {
      defaultReportFormat: getFormValue(form, "report.defaultReportFormat"),
      includeOfficeLogo: getFormValue(form, "report.includeOfficeLogo"),
      includeInspectorSignature: getFormValue(form, "report.includeInspectorSignature"),
      reportHeaderText: getFormValue(form, "report.reportHeaderText"),
      reportFooterText: getFormValue(form, "report.reportFooterText"),
    },
    security_settings: {
      twoStepVerification: getFormValue(form, "security.twoStepVerification"),
      lastLogin: new Date().toLocaleString(),
      accountActivity: "Settings updated from department office.",
    },
  };
}

function bindSettingsPage() {
  const form = document.querySelector("[data-settings-form]");
  form?.addEventListener("submit", async (event) => {
    event.preventDefault();
    setStatus("Saving settings...");
    const result = await apiFetch("/department/api/settings", {
      method: "POST",
      body: JSON.stringify(collectSettingsPayload(form)),
    });
    settingsCache = result.settings;
    renderSettings();
    setStatus("Settings saved.");
  });

  document.querySelector("[data-reset-settings]")?.addEventListener("click", async () => {
    setStatus("Resetting settings...");
    await apiFetch("/department/api/settings", { method: "DELETE" });
    await loadSettings();
    setStatus("Settings reset to defaults.");
  });

  document.querySelector("[data-change-password]")?.addEventListener("click", () => {
    setStatus("Password change uses Supabase Auth and can be connected to email reset next.");
  });
  document.querySelector("[data-logout-all]")?.addEventListener("click", () => {
    setStatus("Logout-all action is ready for a session revocation endpoint.");
  });
  document.querySelector("[data-view-activity]")?.addEventListener("click", () => {
    setStatus("Account activity view can be connected to audit logs next.");
  });
}

async function handleLogout(event) {
  event.preventDefault();
  const confirmed = window.BPLOLogoutModal?.confirm
    ? await window.BPLOLogoutModal.confirm()
    : true;
  if (!confirmed) {
    return;
  }

  await initSupabase()?.auth.signOut();
  window.location.assign("/login");
}

async function boot() {
  try {
    window.lucide?.createIcons();
    document.querySelector("[data-department-logout]")?.addEventListener("click", handleLogout);
    const allowed = await requireDepartmentSession();
    if (!allowed) {
      return;
    }
    bindTableActions();
    bindFilePreviewModal();
    if (page === "dashboard" || page === "applications") {
      if (page === "applications") {
        bindApplicationsWorkspace();
      }
      await loadDashboardLike();
      document.querySelector("[data-search]")?.addEventListener("input", applyApplicationFilters);
      document.querySelector("[data-status-filter]")?.addEventListener("change", applyApplicationFilters);
    }
    if (page === "reports") {
      bindReportsPage();
      await loadReports();
    }
    if (page === "application-details") {
      await loadApplications();
      await loadApplicationDetails();
    }
    if (page === "requirements") {
      await loadApplications();
      bindRequirementPage();
      await loadRequirements();
    }
    if (page === "inspections") {
      bindInspectionPage();
      await loadInspections();
    }
    if (page === "settings") {
      bindSettingsPage();
      await loadApplications();
      await loadSettings();
    }
  } catch (error) {
    setStatus(error instanceof Error ? error.message : "Unable to load page.", true);
  }
}

window.addEventListener("DOMContentLoaded", () => {
  void boot();
});
