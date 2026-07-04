const STAFF_DASHBOARD_SUPABASE_URL = window.APP_CONFIG?.supabaseUrl || "";
const STAFF_DASHBOARD_SUPABASE_KEY =
  window.APP_CONFIG?.supabaseAnonKey || window.APP_CONFIG?.supabasePublishableKey || "";

const dashboardApplicationsBody = document.querySelector("[data-dashboard-applications-body]");
const dashboardApplicationFooter = document.querySelector("[data-dashboard-application-footer]");
const dashboardRefreshButton = document.querySelector("[data-dashboard-refresh]");
const renewalNote = document.querySelector("[data-renewal-note]");
const renewalList = document.querySelector("[data-renewal-list]");
const renewalEmpty = document.querySelector("[data-renewal-empty]");
const chart = document.querySelector("[data-dashboard-chart]");
const chartScale = document.querySelector("[data-dashboard-chart-scale]");
const chartBars = document.querySelector("[data-dashboard-chart-bars]");
const chartEmpty = document.querySelector("[data-dashboard-chart-empty]");

let staffDashboardClient = null;
let dashboardApplications = [];
let dashboardRange = "today";

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

function trendBuckets() {
  const now = new Date();
  if (dashboardRange === "today") {
    return Array.from({ length: 7 }, (_, index) => {
      const hour = index * 4;
      return { label: `${hour}:00`, startHour: hour, count: 0 };
    });
  }
  if (dashboardRange === "monthly") {
    return Array.from({ length: 5 }, (_, index) => ({ label: `W${index + 1}`, week: index, count: 0 }));
  }
  if (dashboardRange === "yearly") {
    return ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"].map((label, month) => ({
      label,
      month,
      count: 0,
    }));
  }
  return Array.from({ length: 7 }, (_, index) => {
    const date = new Date(now);
    date.setDate(now.getDate() - (6 - index));
    return { label: date.toLocaleDateString(undefined, { weekday: "short" }), dateKey: date.toDateString(), count: 0 };
  });
}

function renderChart() {
  if (!chart || !chartBars || !chartScale || !chartEmpty) {
    return;
  }

  const buckets = trendBuckets();
  dashboardApplications.forEach((application) => {
    if (!applicationMatchesRange(application, dashboardRange)) {
      return;
    }
    const date = new Date(getApplicationDate(application));
    if (Number.isNaN(date.getTime())) {
      return;
    }
    if (dashboardRange === "today") {
      const bucket = buckets[Math.min(6, Math.floor(date.getHours() / 4))];
      bucket.count += 1;
    } else if (dashboardRange === "monthly") {
      const bucket = buckets[Math.min(4, Math.floor((date.getDate() - 1) / 7))];
      bucket.count += 1;
    } else if (dashboardRange === "yearly") {
      buckets[date.getMonth()].count += 1;
    } else {
      const bucket = buckets.find((item) => item.dateKey === date.toDateString());
      if (bucket) {
        bucket.count += 1;
      }
    }
  });

  const max = Math.max(...buckets.map((bucket) => bucket.count), 0);
  chart.hidden = max === 0;
  chartEmpty.hidden = max > 0;
  if (!max) {
    return;
  }

  const top = Math.max(max, 1);
  chartScale.innerHTML = [top, Math.ceil(top * 0.66), Math.ceil(top * 0.33), 0]
    .map((value) => `<span>${value}</span>`)
    .join("");
  chartBars.innerHTML = buckets
    .map((bucket) => {
      const height = Math.max(14, Math.round((bucket.count / top) * 130));
      return `<span style="--bar: ${height}px"><strong>${bucket.count}</strong><em>${escapeHtml(bucket.label)}</em></span>`;
    })
    .join("");
}

function renderDashboard() {
  renderRecentApplications();
  renderRenewals();
  renderMetrics();
  renderChart();
  window.lucide?.createIcons();
}

async function loadStaffDashboard() {
  try {
    const session = await getStaffDashboardSession();
    const response = await fetch("/admin/api/applications", {
      headers: { "Authorization": `Bearer ${session.access_token}` },
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || "Unable to load dashboard data.");
    }
    dashboardApplications = Array.isArray(payload.applications) ? payload.applications : [];
    renderDashboard();
  } catch (error) {
    dashboardApplications = [];
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
    renderChart();
  });
});

dashboardRefreshButton?.addEventListener("click", () => {
  void loadStaffDashboard();
});

window.addEventListener("DOMContentLoaded", () => {
  window.lucide?.createIcons();
  void loadStaffDashboard();
});
