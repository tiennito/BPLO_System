const STAFF_DASHBOARD_SUPABASE_URL = window.APP_CONFIG?.supabaseUrl || "";
const STAFF_DASHBOARD_SUPABASE_KEY =
  window.APP_CONFIG?.supabaseAnonKey || window.APP_CONFIG?.supabasePublishableKey || "";

const dashboardApplicationsBody = document.querySelector("[data-dashboard-applications-body]");
const dashboardApplicationFooter = document.querySelector("[data-dashboard-application-footer]");
const dashboardRefreshButton = document.querySelector("[data-dashboard-refresh]");
const renewalNote = document.querySelector("[data-renewal-note]");
const renewalList = document.querySelector("[data-renewal-list]");
const renewalEmpty = document.querySelector("[data-renewal-empty]");

let staffDashboardClient = null;
let dashboardApplications = [];
let dashboardRange = "today";
let renewalSummary = null;

function initStaffDashboardSupabase() {
  if (!window.supabase?.createClient) {
    return null;
  }
  if (!staffDashboardClient) {
    staffDashboardClient = window.supabase.createClient(STAFF_DASHBOARD_SUPABASE_URL, STAFF_DASHBOARD_SUPABASE_KEY);
  }
  return staffDashboardClient;
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
  return String(value || "").trim().toLowerCase();
}

function formatDate(value) {
  if (!value) {
    return "-";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "-";
  }
  return date.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "2-digit" });
}

function getApplicationDate(application) {
  return application.submittedAt || application.createdAt || application.updatedAt || "";
}

function getPermitName(application) {
  const permit = application.permit || {};
  return permit.permitName || permit.permit_name || permit.name || permit.permitCode || permit.permit_code || "Business Permit";
}

function getApplicationType(application) {
  const info = application.businessInfo || {};
  return info.application_type || info.applicationType || application.applicationType || "";
}

function isRenewalApplication(application) {
  const haystack = [getApplicationType(application), getPermitName(application), application.status, application.progress]
    .join(" ")
    .toLowerCase();
  return haystack.includes("renewal") || haystack.includes("re-newal");
}

function statusClass(status) {
  const normalized = normalizeStatus(status);
  if (normalized.includes("reject") || normalized.includes("revision")) {
    return "staff-status--revision";
  }
  if (normalized.includes("approve") || normalized.includes("final") || normalized.includes("verified")) {
    return "staff-status--checking";
  }
  if (normalized.includes("review") || normalized.includes("assessment")) {
    return "staff-status--review";
  }
  return "staff-status--pending";
}

async function getStaffDashboardSession() {
  const client = initStaffDashboardSupabase();
  if (!client) {
    throw new Error("Supabase client is unavailable.");
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

function setMetric(key, value, note) {
  document.querySelectorAll(`[data-dashboard-metric="${key}"]`).forEach((node) => {
    node.textContent = String(value);
  });
  document.querySelectorAll(`[data-dashboard-note="${key}"]`).forEach((node) => {
    node.textContent = note || (value ? "Records loaded" : "No data yet");
  });
}

function applicationMatchesRange(application, range) {
  const rawDate = getApplicationDate(application);
  if (!rawDate || range === "yearly") {
    return true;
  }

  const date = new Date(rawDate);
  if (Number.isNaN(date.getTime())) {
    return false;
  }

  const now = new Date();
  const start = new Date(now);
  start.setHours(0, 0, 0, 0);

  if (range === "today") {
    return date >= start;
  }

  if (range === "week") {
    start.setDate(start.getDate() - 6);
    return date >= start;
  }

  if (range === "monthly") {
    return date.getFullYear() === now.getFullYear() && date.getMonth() === now.getMonth();
  }

  return true;
}

function renderMetrics() {
  const scoped = dashboardApplications.filter((application) => applicationMatchesRange(application, dashboardRange));
  const approved = scoped.filter((application) => {
    const status = normalizeStatus(application.status);
    return status.includes("approve") || status.includes("final") || status.includes("verified");
  });
  const pending = scoped.filter((application) => {
    const status = normalizeStatus(application.status);
    return status.includes("pending") || status.includes("submitted") || status.includes("review") || status.includes("assessment");
  });
  const rejected = scoped.filter((application) => {
    const status = normalizeStatus(application.status);
    return status.includes("reject") || status.includes("revision");
  });

  setMetric("total", scoped.length, scoped.length ? `${dashboardRangeLabel()} records` : "No data yet");
  setMetric("approved", approved.length, approved.length ? "Approved records" : "No data yet");
  setMetric("pending", pending.length, pending.length ? "Awaiting action" : "No data yet");
  setMetric("rejected", rejected.length, rejected.length ? "Needs attention" : "No data yet");
}

function dashboardRangeLabel() {
  return {
    today: "Today",
    week: "This week",
    monthly: "This month",
    yearly: "All year",
  }[dashboardRange] || "Records";
}

function renderRecentApplications() {
  if (!dashboardApplicationsBody) {
    return;
  }

  const recent = dashboardApplications.slice(0, 5);
  if (!recent.length) {
    dashboardApplicationsBody.innerHTML = '<tr><td colspan="6" class="staff-empty-cell">No applications available.</td></tr>';
    if (dashboardApplicationFooter) {
      dashboardApplicationFooter.textContent = "Showing 0 to 0 of 0 entries";
    }
    return;
  }

  dashboardApplicationsBody.innerHTML = recent
    .map((application) => `
      <tr>
        <td>${escapeHtml(application.ownerName || "-")}</td>
        <td>${escapeHtml(application.businessName || "-")}</td>
        <td>${escapeHtml(getPermitName(application))}</td>
        <td>${escapeHtml(formatDate(getApplicationDate(application)))}</td>
        <td><span class="staff-status ${statusClass(application.status)}">${escapeHtml(application.status || "Draft")}</span></td>
        <td><a class="table-action" href="/admin/staff-administrator/applications/${encodeURIComponent(application.id)}">View</a></td>
      </tr>
    `)
    .join("");

  if (dashboardApplicationFooter) {
    dashboardApplicationFooter.textContent = `Showing 1 to ${recent.length} of ${dashboardApplications.length} entries`;
  }
}

function renderRenewals() {
  if (!renewalList || !renewalEmpty) {
    return;
  }

  if (renewalSummary) {
    const rows = [
      ["Open", renewalSummary.open || 0],
      ["Submitted", renewalSummary.submitted || 0],
      ["Late", renewalSummary.late || 0],
      ["For Payment", renewalSummary.for_payment || 0],
      ["Renewed", renewalSummary.renewed || 0],
    ].filter((item) => item[1] > 0);
    const total = Number(renewalSummary.total || Object.values(renewalSummary).reduce((sum, value) => sum + Number(value || 0), 0));
    if (renewalNote) {
      renewalNote.textContent = total ? `${total} renewal permit record${total === 1 ? "" : "s"} monitored.` : "No renewal records yet.";
    }
    renewalList.hidden = !rows.length;
    renewalEmpty.hidden = Boolean(rows.length);
    renewalList.innerHTML = rows.map(([label, count]) => `
      <li>
        <i data-lucide="clipboard-check" aria-hidden="true"></i>
        <span><strong>${escapeHtml(label)}</strong><small>${count} record${count === 1 ? "" : "s"}</small></span>
      </li>
    `).join("");
    return;
  }

  const renewals = dashboardApplications.filter(isRenewalApplication).slice(0, 4);
  if (renewalNote) {
    renewalNote.textContent = renewals.length
      ? `${renewals.length} renewal record${renewals.length === 1 ? "" : "s"} available.`
      : "No renewal requirement data available.";
  }

  renewalList.hidden = !renewals.length;
  renewalEmpty.hidden = Boolean(renewals.length);

  renewalList.innerHTML = renewals
    .map((application) => `
      <li>
        <i data-lucide="clipboard-check" aria-hidden="true"></i>
        <span>
          <strong>${escapeHtml(application.businessName || "Renewal Application")}</strong>
          <small>${escapeHtml(application.ownerName || "-")} · ${escapeHtml(application.status || "Draft")} · ${escapeHtml(formatDate(getApplicationDate(application)))}</small>
        </span>
      </li>
    `)
    .join("");
}

function renderDashboard() {
  renderRecentApplications();
  renderRenewals();
  renderMetrics();
  window.lucide?.createIcons();
}

async function loadStaffDashboard() {
  try {
    const session = await getStaffDashboardSession();
    const [response, renewalResponse] = await Promise.all([
      fetch("/admin/api/applications", { headers: { "Authorization": `Bearer ${session.access_token}` } }),
      fetch("/admin/api/renewals/summary", { headers: { "Authorization": `Bearer ${session.access_token}` } }),
    ]);
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || "Unable to load dashboard data.");
    }
    const renewalPayload = await renewalResponse.json();
    renewalSummary = renewalResponse.ok ? { ...(renewalPayload.summary || {}), total: renewalPayload.total || 0 } : null;
    dashboardApplications = Array.isArray(payload.applications) ? payload.applications : [];
    renderDashboard();
  } catch (error) {
    dashboardApplications = [];
    renewalSummary = null;
    renderDashboard();
    if (dashboardApplicationFooter) {
      dashboardApplicationFooter.textContent = error.message || "Unable to load dashboard data.";
    }
    if (renewalNote) {
      renewalNote.textContent = error.message || "Unable to load dashboard data.";
    }
  }
}

document.querySelectorAll("[data-dashboard-range]").forEach((button) => {
  button.addEventListener("click", () => {
    dashboardRange = button.dataset.dashboardRange || "today";
    document.querySelectorAll("[data-dashboard-range]").forEach((item) => item.classList.remove("is-active"));
    button.classList.add("is-active");
    renderMetrics();
  });
});

dashboardRefreshButton?.addEventListener("click", () => {
  void loadStaffDashboard();
});

window.addEventListener("DOMContentLoaded", () => {
  window.lucide?.createIcons();
  void loadStaffDashboard();
});
