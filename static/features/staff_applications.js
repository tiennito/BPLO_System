const STAFF_SUPABASE_URL = window.APP_CONFIG?.supabaseUrl || "";
const STAFF_SUPABASE_KEY =
  window.APP_CONFIG?.supabaseAnonKey || window.APP_CONFIG?.supabasePublishableKey || "";

const applicationsBody = document.querySelector("[data-applications-body]");
const applicationSummary = document.querySelector("[data-application-summary]");
const applicationFooter = document.querySelector("[data-application-footer]");
const applicationSearch = document.querySelector("[data-application-search]");
const permitFilter = document.querySelector("[data-application-permit-filter]");
const statusFilter = document.querySelector("[data-application-status-filter]");
const refreshButton = document.querySelector("[data-refresh-applications]");
const detailPanel = document.querySelector("[data-application-detail]");

let staffSupabaseClient = null;
let applications = [];
let selectedApplicationId = "";

function initStaffSupabase() {
  if (!window.supabase?.createClient) {
    return null;
  }
  if (!staffSupabaseClient) {
    staffSupabaseClient = window.supabase.createClient(STAFF_SUPABASE_URL, STAFF_SUPABASE_KEY);
  }
  return staffSupabaseClient;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function normalizeStatus(value) {
  return String(value || "").trim();
}

function setSummary(message, isError = false) {
  if (!applicationSummary) {
    return;
  }
  applicationSummary.textContent = message || "";
  applicationSummary.style.color = isError ? "#b42318" : "#68736c";
}

function formatDateTime(value) {
  if (!value) {
    return "-";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "-";
  }
  return date.toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "2-digit",
  });
}

function getPermitName(application) {
  const permit = application.permit || {};
  return permit.permitName || permit.permit_name || permit.name || permit.permitCode || permit.permit_code || "Business Permit";
}

function getAssignedOffices(application) {
  const offices = application.officeProgress || [];
  if (!offices.length) {
    return "-";
  }
  return offices.map((office) => office.department_key || office.department || "Office").join(", ");
}

function statusClass(status) {
  const normalized = normalizeStatus(status).toLowerCase();
  if (normalized.includes("submitted") || normalized.includes("pending")) {
    return "staff-status--pending";
  }
  if (normalized.includes("review")) {
    return "staff-status--review";
  }
  if (normalized.includes("check") || normalized.includes("verified")) {
    return "staff-status--checking";
  }
  return "staff-status--assessment";
}

async function getStaffSession() {
  const client = initStaffSupabase();
  if (!client) {
    throw new Error("Supabase client is unavailable in this browser.");
  }
  const { data, error } = await client.auth.getSession();
  if (error) {
    throw error;
  }
  if (!data.session?.access_token) {
    throw new Error("Please log in as a BPLO staff administrator.");
  }
  return data.session;
}

function getFilteredApplications() {
  const searchTerm = (applicationSearch?.value || "").trim().toLowerCase();
  const selectedPermit = permitFilter?.value || "";
  const selectedStatus = statusFilter?.value || "";

  return applications.filter((application) => {
    const searchable = [
      application.referenceNumber,
      application.ownerName,
      application.businessName,
      getPermitName(application),
      application.status,
    ]
      .join(" ")
      .toLowerCase();

    const matchesSearch = !searchTerm || searchable.includes(searchTerm);
    const matchesPermit = !selectedPermit || getPermitName(application) === selectedPermit;
    const matchesStatus = !selectedStatus || application.status === selectedStatus;
    return matchesSearch && matchesPermit && matchesStatus;
  });
}

function setCount(key, value, note = "") {
  document.querySelectorAll(`[data-application-count="${key}"]`).forEach((node) => {
    node.textContent = String(value);
  });
  document.querySelectorAll(`[data-application-note="${key}"]`).forEach((node) => {
    node.textContent = note || (value ? "Loaded" : "No data yet");
  });
}

function updateCounts() {
  const pending = applications.filter((item) => normalizeStatus(item.status).toLowerCase().includes("pending") || normalizeStatus(item.status).toLowerCase().includes("submitted"));
  const review = applications.filter((item) => normalizeStatus(item.progress).toLowerCase().includes("review"));
  const checking = applications.filter((item) => (item.officeProgress || []).some((office) => office.verification_status === "Unverified"));
  setCount("total", applications.length, applications.length ? "Records loaded" : "No data yet");
  setCount("pending", pending.length, pending.length ? "Awaiting action" : "No data yet");
  setCount("review", review.length, review.length ? "In workflow" : "No data yet");
  setCount("checking", checking.length, checking.length ? "Office checks" : "No data yet");
}

function populateFilters() {
  const permitNames = [...new Set(applications.map(getPermitName).filter(Boolean))].sort();
  const statuses = [...new Set(applications.map((item) => item.status).filter(Boolean))].sort();

  if (permitFilter) {
    const current = permitFilter.value;
    permitFilter.innerHTML = '<option value="">All Permit Types</option>' + permitNames
      .map((name) => `<option value="${escapeHtml(name)}">${escapeHtml(name)}</option>`)
      .join("");
    permitFilter.value = permitNames.includes(current) ? current : "";
  }

  if (statusFilter) {
    const current = statusFilter.value;
    statusFilter.innerHTML = '<option value="">All Status</option>' + statuses
      .map((status) => `<option value="${escapeHtml(status)}">${escapeHtml(status)}</option>`)
      .join("");
    statusFilter.value = statuses.includes(current) ? current : "";
  }
}

function renderApplications() {
  if (!applicationsBody) {
    return;
  }

  const filtered = getFilteredApplications();

  if (!filtered.length) {
    applicationsBody.innerHTML = '<tr><td colspan="8" class="staff-empty-cell">No applications available.</td></tr>';
  } else {
    applicationsBody.innerHTML = filtered
      .map((application) => `
        <tr class="${application.id === selectedApplicationId ? "is-selected" : ""}" data-application-id="${escapeHtml(application.id)}">
          <td>${escapeHtml(application.referenceNumber || "-")}</td>
          <td>${escapeHtml(application.ownerName || "-")}</td>
          <td>${escapeHtml(application.businessName || "-")}</td>
          <td>${escapeHtml(getPermitName(application))}</td>
          <td>${escapeHtml(formatDateTime(application.submittedAt || application.createdAt))}</td>
          <td>${escapeHtml(getAssignedOffices(application))}</td>
          <td><span class="staff-status ${statusClass(application.status)}">${escapeHtml(application.status || "Draft")}</span></td>
          <td><button class="table-action" type="button" data-view-application="${escapeHtml(application.id)}">View</button></td>
        </tr>
      `)
      .join("");
  }

  setSummary(filtered.length ? `${filtered.length} application record${filtered.length === 1 ? "" : "s"} available.` : "No application records available.");
  if (applicationFooter) {
    applicationFooter.textContent = `Showing ${filtered.length ? 1 : 0} to ${filtered.length} of ${filtered.length} entries`;
  }
}

function renderApplicationDetails(application = null) {
  if (!detailPanel) {
    return;
  }

  if (!application) {
    detailPanel.innerHTML = `
      <header class="staff-detail-header">
        <h2 id="application-details-title">Application Details</h2>
        <button type="button" aria-label="Close details"><i data-lucide="x" aria-hidden="true"></i></button>
      </header>
      <div class="staff-empty-state">
        <i data-lucide="inbox" aria-hidden="true"></i>
        <strong>No application selected</strong>
        <span>Details will appear here after an application record is selected.</span>
      </div>
    `;
    window.lucide?.createIcons();
    return;
  }

  const info = application.businessInfo || {};
  detailPanel.innerHTML = `
    <header class="staff-detail-header">
      <h2 id="application-details-title">Application Details</h2>
      <button type="button" aria-label="Close details" data-clear-application-detail><i data-lucide="x" aria-hidden="true"></i></button>
    </header>
    <section class="staff-detail-section">
      <h3>${escapeHtml(application.businessName || "Business")}</h3>
      <dl class="staff-detail-list">
        <div><dt>Control No.</dt><dd>${escapeHtml(application.referenceNumber || "-")}</dd></div>
        <div><dt>Applicant</dt><dd>${escapeHtml(application.ownerName || "-")}</dd></div>
        <div><dt>Classification</dt><dd>${escapeHtml(info.business_classification || "-")}</dd></div>
        <div><dt>Permit Type</dt><dd>${escapeHtml(getPermitName(application))}</dd></div>
        <div><dt>Status</dt><dd>${escapeHtml(application.status || "-")}</dd></div>
        <div><dt>Date Submitted</dt><dd>${escapeHtml(formatDateTime(application.submittedAt || application.createdAt))}</dd></div>
        <div><dt>Business Address</dt><dd>${escapeHtml(info.business_address || "-")}</dd></div>
        <div><dt>Uploaded Documents</dt><dd>${application.documents?.length || 0}</dd></div>
      </dl>
    </section>
  `;
  window.lucide?.createIcons();
}

async function loadApplications() {
  try {
    setSummary("Loading application records...");
    const session = await getStaffSession();
    const response = await fetch("/admin/api/applications", {
      headers: { "Authorization": `Bearer ${session.access_token}` },
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || "Unable to load applications.");
    }

    applications = Array.isArray(payload.applications) ? payload.applications : [];
    updateCounts();
    populateFilters();
    renderApplications();
    renderApplicationDetails(applications.find((item) => item.id === selectedApplicationId) || null);
  } catch (error) {
    applications = [];
    updateCounts();
    renderApplications();
    renderApplicationDetails(null);
    setSummary(error.message || "Unable to load applications.", true);
  }
}

applicationsBody?.addEventListener("click", (event) => {
  const target = event.target;
  if (!(target instanceof HTMLElement)) {
    return;
  }
  const row = target.closest("[data-application-id]");
  if (!(row instanceof HTMLElement)) {
    return;
  }
  selectedApplicationId = row.dataset.applicationId || "";
  const application = applications.find((item) => item.id === selectedApplicationId);
  renderApplications();
  renderApplicationDetails(application);
});

detailPanel?.addEventListener("click", (event) => {
  const target = event.target;
  if (target instanceof HTMLElement && target.closest("[data-clear-application-detail]")) {
    selectedApplicationId = "";
    renderApplications();
    renderApplicationDetails(null);
  }
});

applicationSearch?.addEventListener("input", renderApplications);
permitFilter?.addEventListener("change", renderApplications);
statusFilter?.addEventListener("change", renderApplications);
refreshButton?.addEventListener("click", () => {
  void loadApplications();
});

window.addEventListener("DOMContentLoaded", () => {
  window.lucide?.createIcons();
  void loadApplications();
});
