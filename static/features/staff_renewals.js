const RENEWAL_SUPABASE_URL = window.APP_CONFIG?.supabaseUrl || "";
const RENEWAL_SUPABASE_KEY =
  window.APP_CONFIG?.supabaseAnonKey || window.APP_CONFIG?.supabasePublishableKey || "";

const renewalBody = document.querySelector("[data-renewals-body]");
const renewalStatus = document.querySelector("[data-renewal-status]");
const renewalFooter = document.querySelector("[data-renewal-footer]");
const summaryGrid = document.querySelector("[data-renewal-summary]");
const settingsForm = document.querySelector("[data-renewal-settings-form]");
const extensionForm = document.querySelector("[data-renewal-extension-form]");

let renewalClient = null;
let renewalPage = 1;
let renewalPageSize = 25;
let renewalTotal = 0;

function initRenewalClient() {
  if (!renewalClient && window.supabase?.createClient) {
    renewalClient = window.supabase.createClient(RENEWAL_SUPABASE_URL, RENEWAL_SUPABASE_KEY);
  }
  return renewalClient;
}

function esc(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function dateText(value) {
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

function setStatus(message, isError = false) {
  if (!renewalStatus) return;
  renewalStatus.textContent = message || "";
  renewalStatus.style.color = isError ? "#b42318" : "#68736c";
}

async function getSession() {
  const client = initRenewalClient();
  if (!client) throw new Error("Supabase client is unavailable in this browser.");
  const { data, error } = await client.auth.getSession();
  if (error) throw error;
  if (!data.session?.access_token) throw new Error("Please log in as a BPLO staff administrator.");
  return data.session;
}

async function api(path, options = {}) {
  const session = await getSession();
  const response = await fetch(path, {
    ...options,
    headers: {
      "Authorization": `Bearer ${session.access_token}`,
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
  });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || "Unable to complete request.");
  return payload;
}

function filterParams() {
  const params = new URLSearchParams({ page: String(renewalPage), pageSize: String(renewalPageSize) });
  document.querySelectorAll("[data-filter]").forEach((field) => {
    const value = field.value?.trim();
    if (value) params.set(field.dataset.filter, value);
  });
  return params;
}

function populateStatusOptions(summary = {}) {
  const select = document.querySelector('[data-filter="renewalStatus"]');
  if (!select) return;
  const current = select.value;
  const statuses = ["upcoming", "open", "draft", "submitted", "under_review", "for_payment", "paid", "late", "renewed", "closed"]
    .filter((status) => status === current || summary[status] || ["upcoming", "open", "submitted", "late", "for_payment", "renewed"].includes(status));
  select.innerHTML = '<option value="">All statuses</option>' + statuses.map((status) => `<option value="${esc(status)}">${esc(status.replaceAll("_", " "))}</option>`).join("");
  select.value = statuses.includes(current) ? current : "";
}

function renderSummary(summary) {
  summaryGrid?.querySelectorAll("[data-summary-filter]").forEach((button) => {
    const key = button.dataset.summaryFilter || "";
    const strong = button.querySelector("strong");
    if (strong) strong.textContent = String(summary[key] || 0);
  });
  populateStatusOptions(summary);
}

function renderRows(rows) {
  if (!renewalBody) return;
  if (!rows.length) {
    renewalBody.innerHTML = '<tr><td colspan="8" class="staff-empty-cell">No renewal records found.</td></tr>';
    return;
  }
  renewalBody.innerHTML = rows.map((row) => {
    const status = row.renewal_status || "-";
    const appId = row.renewal_application_id || "";
    const assessmentStatus = row.renewal_assessment_status || row.assessment_status || "-";
    return `
      <tr>
        <td>${esc(row.permit_number || "-")}</td>
        <td><strong>${esc(row.business_name || "-")}</strong><small>${esc(row.permit_type || "Business Permit")}</small></td>
        <td>${esc(row.owner_name || "-")}</td>
        <td>${esc(row.existing_permit_year || "-")} -> ${esc(row.renewal_year || "-")}</td>
        <td>${esc(dateText(row.effective_renewal_due_date || row.renewal_due_date))}${row.is_late ? "<small>Late filing</small>" : ""}</td>
        <td><span class="staff-status">${esc(status.replaceAll("_", " "))}</span></td>
        <td>${esc(assessmentStatus.replaceAll("_", " "))}<small>${esc(money(row.renewal_total_amount))}</small></td>
        <td>
          ${appId ? `<a class="staff-view-all" href="/admin/staff-administrator/applications/${encodeURIComponent(appId)}">Review</a>` : ""}
          ${appId ? `<button type="button" class="table-action" data-calculate-assessment="${esc(appId)}">Assess</button>` : ""}
        </td>
      </tr>
    `;
  }).join("");
}

function updateFooter() {
  const start = renewalTotal ? (renewalPage - 1) * renewalPageSize + 1 : 0;
  const end = Math.min(renewalTotal, renewalPage * renewalPageSize);
  if (renewalFooter) renewalFooter.textContent = `Showing ${start} to ${end} of ${renewalTotal} entries`;
  document.querySelector("[data-renewal-prev]").disabled = renewalPage <= 1;
  document.querySelector("[data-renewal-next]").disabled = renewalPage * renewalPageSize >= renewalTotal;
}

async function loadSummary() {
  const payload = await api("/admin/api/renewals/summary");
  renderSummary(payload.summary || {});
}

async function loadSettings() {
  const payload = await api("/admin/api/renewal/settings");
  const settings = payload.settings || {};
  if (!settingsForm) return;
  Object.entries({
    renewalStartMonth: settings.renewal_start_month,
    renewalStartDay: settings.renewal_start_day,
    renewalDueMonth: settings.renewal_due_month,
    renewalDueDay: settings.renewal_due_day,
    surchargeRate: settings.surcharge_rate,
    monthlyInterestRate: settings.monthly_interest_rate,
    maximumInterestMonths: settings.maximum_interest_months,
    interestMonthRule: settings.interest_month_rule,
  }).forEach(([name, value]) => {
    if (settingsForm.elements[name]) settingsForm.elements[name].value = value ?? "";
  });
  if (settingsForm.elements.penaltiesEnabled) {
    settingsForm.elements.penaltiesEnabled.checked = settings.penalties_enabled !== false;
  }
}

async function loadRenewals() {
  try {
    setStatus("Loading renewal records...");
    const payload = await api(`/admin/api/renewals?${filterParams().toString()}`);
    renewalTotal = Number(payload.total || 0);
    renewalPageSize = Number(payload.pageSize || renewalPageSize);
    renderRows(payload.renewals || []);
    updateFooter();
    setStatus(`${renewalTotal} renewal record(s) loaded.`);
    window.lucide?.createIcons();
  } catch (error) {
    renewalTotal = 0;
    renderRows([]);
    updateFooter();
    setStatus(error.message || "Unable to load renewal records.", true);
  }
}

async function refreshAll() {
  await Promise.all([loadSummary(), loadSettings(), loadRenewals()]);
}

document.querySelector("[data-refresh-renewals]")?.addEventListener("click", () => {
  renewalPage = 1;
  loadRenewals();
});

document.querySelector("[data-renewal-prev]")?.addEventListener("click", () => {
  renewalPage = Math.max(1, renewalPage - 1);
  loadRenewals();
});

document.querySelector("[data-renewal-next]")?.addEventListener("click", () => {
  if (renewalPage * renewalPageSize < renewalTotal) {
    renewalPage += 1;
    loadRenewals();
  }
});

document.querySelectorAll("[data-filter]").forEach((field) => {
  field.addEventListener("change", () => {
    renewalPage = 1;
    loadRenewals();
  });
  field.addEventListener("input", () => {
    if (field.type === "search") {
      renewalPage = 1;
      window.clearTimeout(field._renewalTimer);
      field._renewalTimer = window.setTimeout(loadRenewals, 250);
    }
  });
});

summaryGrid?.addEventListener("click", async (event) => {
  const target = event.target instanceof HTMLElement ? event.target : null;
  const job = target?.closest("[data-run-renewal-job]");
  if (job) {
    try {
      setStatus("Running renewal status check...");
      const payload = await api("/admin/api/renewals/run-daily", { method: "POST", body: "{}" });
      setStatus(`Processed ${payload.processed || 0} permits, sent ${payload.notifications || 0} reminder(s).`);
      await refreshAll();
    } catch (error) {
      setStatus(error.message || "Unable to run renewal check.", true);
    }
    return;
  }
  const button = target?.closest("[data-summary-filter]");
  if (!button) return;
  const select = document.querySelector('[data-filter="renewalStatus"]');
  if (select) {
    const value = button.dataset.summaryFilter || "";
    if (value === "unrenewed" && ![...select.options].some((option) => option.value === "unrenewed")) {
      select.append(new Option("Unrenewed", "unrenewed"));
    }
    select.value = value;
  }
  renewalPage = 1;
  loadRenewals();
});

renewalBody?.addEventListener("click", async (event) => {
  const target = event.target instanceof HTMLElement ? event.target : null;
  const button = target?.closest("[data-calculate-assessment]");
  if (!button) return;
  const baseRenewalFee = window.prompt("Base renewal fee", "0");
  if (baseRenewalFee === null) return;
  const otherFees = window.prompt("Other fees", "0");
  if (otherFees === null) return;
  try {
    const payload = await api(`/admin/api/renewals/${encodeURIComponent(button.dataset.calculateAssessment || "")}/assessment/calculate`, {
      method: "POST",
      body: JSON.stringify({ baseRenewalFee, otherFees }),
    });
    setStatus(payload.message || "Renewal assessment calculated.");
    await loadRenewals();
  } catch (error) {
    setStatus(error.message || "Unable to calculate assessment.", true);
  }
});

settingsForm?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const payload = Object.fromEntries(new FormData(form).entries());
  payload.penaltiesEnabled = form.elements.penaltiesEnabled.checked;
  try {
    const result = await api("/admin/api/renewal/settings", { method: "PATCH", body: JSON.stringify(payload) });
    setStatus(result.message || "Renewal settings saved.");
    await refreshAll();
  } catch (error) {
    setStatus(error.message || "Unable to save renewal settings.", true);
  }
});

extensionForm?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const payload = Object.fromEntries(new FormData(form).entries());
  payload.surchargeSuspended = form.elements.surchargeSuspended.checked;
  payload.interestSuspended = form.elements.interestSuspended.checked;
  try {
    const result = await api("/admin/api/renewal/deadline-extensions", { method: "POST", body: JSON.stringify(payload) });
    setStatus(result.message || "Renewal deadline extension saved.");
    form.reset();
    await refreshAll();
  } catch (error) {
    setStatus(error.message || "Unable to save deadline extension.", true);
  }
});

window.addEventListener("DOMContentLoaded", () => {
  window.lucide?.createIcons();
});

(async function bootRenewals() {
  try {
    await refreshAll();
    window.lucide?.createIcons();
  } catch (error) {
    setStatus(error.message || "Unable to load renewals.", true);
  }
})();
