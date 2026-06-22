const AUDIT_SUPABASE_URL = window.APP_CONFIG?.supabaseUrl || "";
const AUDIT_SUPABASE_KEY =
  window.APP_CONFIG?.supabaseAnonKey || window.APP_CONFIG?.supabasePublishableKey || "";
const AUDIT_ADMIN_EMAIL = (window.APP_CONFIG?.adminEmail || "").toLowerCase();

const auditBody = document.querySelector("[data-audit-body]");
const auditStatus = document.querySelector("[data-audit-status]");
const auditSearchInput = document.querySelector("[data-audit-search]");
const actionFilter = document.querySelector("[data-action-filter]");
const refreshAuditButton = document.querySelector("[data-refresh-audit-logs]");
const auditCount = document.querySelector("[data-audit-count]");
const auditPagination = document.querySelector("[data-audit-pagination]");
const auditPageSummary = document.querySelector("[data-audit-page-summary]");
const auditPageLabel = document.querySelector("[data-audit-page-label]");
const auditPrevButton = document.querySelector("[data-audit-prev]");
const auditNextButton = document.querySelector("[data-audit-next]");

let auditClient = null;
let auditLogs = [];
let auditPage = 1;
const AUDIT_PAGE_SIZE = 10;

function initAuditSupabase() {
  if (!window.supabase?.createClient) {
    return null;
  }

  if (!auditClient) {
    auditClient = window.supabase.createClient(AUDIT_SUPABASE_URL, AUDIT_SUPABASE_KEY);
  }

  return auditClient;
}

function setAuditStatus(message, isError = false) {
  if (!auditStatus) {
    return;
  }

  auditStatus.textContent = message;
  auditStatus.style.color = isError ? "#b42318" : "#078d36";
}

async function getAdminSession() {
  const client = initAuditSupabase();
  if (!client) {
    throw new Error("Supabase client is unavailable in this browser.");
  }

  const { data, error } = await client.auth.getSession();
  if (error) {
    throw error;
  }

  const session = data.session;
  if (!session) {
    throw new Error("Please log in as the admin account first.");
  }

  const signedInEmail = (session.user?.email || "").toLowerCase();
  if (AUDIT_ADMIN_EMAIL && signedInEmail !== AUDIT_ADMIN_EMAIL) {
    throw new Error("Only the configured admin account can view audit logs.");
  }

  return session;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function formatDateTime(value) {
  if (!value) {
    return "-";
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "-";
  }

  return date.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatAction(action) {
  return String(action || "")
    .replaceAll("_", " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function compactDetails(details) {
  if (!details || typeof details !== "object") {
    return "-";
  }

  const entries = Object.entries(details).filter(([, value]) => value !== "" && value != null);
  if (!entries.length) {
    return "-";
  }

  return entries
    .slice(0, 3)
    .map(([key, value]) => `${key}: ${typeof value === "object" ? JSON.stringify(value) : value}`)
    .join(", ");
}

function getFilteredAuditLogs() {
  const searchTerm = (auditSearchInput?.value || "").toLowerCase().trim();
  const selectedAction = actionFilter?.value || "";

  return auditLogs.filter((log) => {
    const details = compactDetails(log.details).toLowerCase();
    const matchesSearch =
      !searchTerm ||
      (log.actorEmail || "").toLowerCase().includes(searchTerm) ||
      (log.action || "").toLowerCase().includes(searchTerm) ||
      details.includes(searchTerm);
    const matchesAction = !selectedAction || log.action === selectedAction;

    return matchesSearch && matchesAction;
  });
}

function renderAuditLogs() {
  if (!auditBody) {
    return;
  }

  const filteredLogs = getFilteredAuditLogs();
  const pageCount = Math.max(1, Math.ceil(filteredLogs.length / AUDIT_PAGE_SIZE));
  auditPage = Math.min(Math.max(1, auditPage), pageCount);
  const startIndex = (auditPage - 1) * AUDIT_PAGE_SIZE;
  const pageLogs = filteredLogs.slice(startIndex, startIndex + AUDIT_PAGE_SIZE);

  if (!auditLogs.length) {
    syncAuditPagination(0, 0, 0);
    auditBody.innerHTML = `
      <tr>
        <td colspan="7">
          <div class="users-empty-state">
            <strong>No audit logs yet</strong>
            <p>User actions will appear here after the audit table is applied.</p>
          </div>
        </td>
      </tr>
    `;
    return;
  }

  if (!filteredLogs.length) {
    syncAuditPagination(0, 0, 0);
    auditBody.innerHTML = `
      <tr>
        <td colspan="7">
          <div class="users-empty-state">
            <strong>No matching audit logs</strong>
            <p>Try a different search or action filter.</p>
          </div>
        </td>
      </tr>
    `;
    return;
  }

  auditBody.innerHTML = pageLogs
    .map(
      (log) => `
        <tr>
          <td>${escapeHtml(formatDateTime(log.createdAt))}</td>
          <td>${escapeHtml(log.actorEmail)}</td>
          <td>${escapeHtml(log.actorRole)}</td>
          <td><span class="audit-action-pill">${escapeHtml(formatAction(log.action))}</span></td>
          <td>${escapeHtml(log.entityType)}<br /><small>${escapeHtml(log.entityId)}</small></td>
          <td>${escapeHtml(compactDetails(log.details))}</td>
          <td>${escapeHtml(log.ipAddress)}</td>
        </tr>
      `
    )
    .join("");
  syncAuditPagination(filteredLogs.length, startIndex + 1, startIndex + pageLogs.length);
}

function syncAuditPagination(totalLogs, start, end) {
  if (!auditPagination) {
    return;
  }

  const hasLogs = totalLogs > 0;
  const pageCount = Math.max(1, Math.ceil(totalLogs / AUDIT_PAGE_SIZE));
  auditPagination.hidden = !hasLogs;

  if (auditPageSummary) {
    auditPageSummary.textContent = hasLogs ? `Showing ${start} to ${end} of ${totalLogs} logs` : "Showing 0 logs";
  }

  if (auditPageLabel) {
    auditPageLabel.textContent = `Page ${auditPage} of ${pageCount}`;
  }

  if (auditPrevButton) {
    auditPrevButton.disabled = auditPage <= 1;
  }

  if (auditNextButton) {
    auditNextButton.disabled = auditPage >= pageCount;
  }
}

async function loadAuditLogs() {
  try {
    setAuditStatus("Loading audit logs...");
    if (refreshAuditButton) {
      refreshAuditButton.disabled = true;
    }

    const session = await getAdminSession();
    const response = await fetch("/admin/api/audit-logs", {
      headers: {
        "Authorization": `Bearer ${session.access_token}`,
      },
    });
    const result = await response.json();

    if (!response.ok) {
      throw new Error(result.error || "Unable to load audit logs.");
    }

    auditLogs = Array.isArray(result.logs) ? result.logs : [];
    auditPage = 1;
    if (auditCount) {
      auditCount.textContent = String(auditLogs.length);
    }
    renderAuditLogs();
    setAuditStatus(`${auditLogs.length} audit log${auditLogs.length === 1 ? "" : "s"} loaded.`);
  } catch (error) {
    auditLogs = [];
    renderAuditLogs();
    setAuditStatus(error instanceof Error ? error.message : "Unable to load audit logs.", true);
  } finally {
    if (refreshAuditButton) {
      refreshAuditButton.disabled = false;
    }
  }
}

auditSearchInput?.addEventListener("input", () => {
  auditPage = 1;
  renderAuditLogs();
});
actionFilter?.addEventListener("change", () => {
  auditPage = 1;
  renderAuditLogs();
});
refreshAuditButton?.addEventListener("click", loadAuditLogs);
auditPrevButton?.addEventListener("click", () => {
  auditPage -= 1;
  renderAuditLogs();
});
auditNextButton?.addEventListener("click", () => {
  auditPage += 1;
  renderAuditLogs();
});

window.addEventListener("DOMContentLoaded", () => {
  if (window.lucide) {
    window.lucide.createIcons();
  }

  loadAuditLogs();
});
