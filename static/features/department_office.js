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

  const response = await fetch(path, {
    ...options,
    headers: {
      "Authorization": `Bearer ${session.access_token}`,
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
  });
  const result = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(result.error || "Request failed.");
  }
  return result;
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

function syncAssessmentTotals() {
  const form = document.querySelector("[data-assessment-form]");
  if (!form) {
    return;
  }
  const amount = Number(form.elements.amount?.value || 0);
  const penalty = Number(form.elements.penalty?.value || 0);
  form.elements.amountSummary.value = formatMoney(amount);
  form.elements.penaltySummary.value = formatMoney(penalty);
  form.elements.totalSummary.value = formatMoney(amount + penalty);
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
    `<article class="detail-card field-full"><span>Uploaded Documents / Application Payload</span><pre>${escapeHtml(JSON.stringify(payload, null, 2))}</pre></article>`,
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
  document.querySelectorAll("[data-export-placeholder]").forEach((button) => {
    button.addEventListener("click", () => setStatus("Export design is ready. File export generation can be connected next."));
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
  assessmentForm?.addEventListener("input", syncAssessmentTotals);
  assessmentForm?.addEventListener("submit", (event) => {
    event.preventDefault();
    syncAssessmentTotals();
    setStatus("Assessment fee prepared for the selected application.");
  });

  document.querySelector("[data-preview-assessment]")?.addEventListener("click", () => {
    syncAssessmentTotals();
    setStatus("Assessment preview generated.");
  });

  const staffInspectionForm = document.querySelector("[data-staff-inspection-form]");
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

    setStatus("Saving inspection schedule...");
    await apiFetch("/department/api/inspections", {
      method: "POST",
      body: JSON.stringify({
        applicationId: application.applicationId,
        scheduledDate,
        scheduledTime,
        status: formData.get("status").toString(),
        remarks: formData.get("remarks").toString().trim(),
      }),
    });
    setStatus("Inspection schedule saved.");
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
  });

  document.querySelectorAll("[data-upload-placeholder]").forEach((button) => {
    button.addEventListener("click", () => {
      setStatus("Upload UI is ready. Storage upload endpoint is not configured yet.");
    });
  });

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
