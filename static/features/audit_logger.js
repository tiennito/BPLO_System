const auditConfig = {
  supabaseUrl: window.APP_CONFIG?.supabaseUrl || "",
  supabaseKey: window.APP_CONFIG?.supabaseAnonKey || window.APP_CONFIG?.supabasePublishableKey || "",
};

let auditSupabaseClient = null;

function getAuditClient() {
  if (!window.supabase?.createClient || !auditConfig.supabaseUrl || !auditConfig.supabaseKey) {
    return null;
  }

  if (!auditSupabaseClient) {
    auditSupabaseClient = window.supabase.createClient(
      auditConfig.supabaseUrl,
      auditConfig.supabaseKey
    );
  }

  return auditSupabaseClient;
}

async function getAuditSession() {
  const client = getAuditClient();
  if (!client) {
    return null;
  }

  const { data } = await client.auth.getSession();
  return data.session || null;
}

function setAuditBadgeCount(count) {
  document.querySelectorAll("[data-audit-count]").forEach((node) => {
    node.textContent = String(count);
  });
}

async function refreshAuditBadge(session) {
  const badges = document.querySelectorAll("[data-audit-count]");
  if (!badges.length || !session?.access_token || !window.location.pathname.startsWith("/admin")) {
    return;
  }

  try {
    const response = await fetch("/admin/api/audit-logs", {
      headers: {
        "Authorization": `Bearer ${session.access_token}`,
      },
    });
    const result = await response.json();
    if (!response.ok) {
      throw new Error(result.error || "Unable to load audit badge.");
    }

    setAuditBadgeCount(Array.isArray(result.logs) ? result.logs.length : 0);
  } catch (_error) {
    setAuditBadgeCount(0);
  }
}

window.BPLOAudit = {
  async record(action, details = {}, entityType = "", entityId = "") {
    try {
      const session = await getAuditSession();
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
    } catch (_error) {
      // Audit failures should never block the user workflow.
    }
  },
};

window.addEventListener("DOMContentLoaded", () => {
  void (async () => {
    const session = await getAuditSession();
    const role = session?.user?.app_metadata?.role || "";
    if (window.location.pathname.startsWith("/admin") && role === "department") {
      window.location.replace("/department/dashboard");
      return;
    }
    if (window.location.pathname.startsWith("/admin") && role === "treasury") {
      window.location.replace("/treasury/dashboard");
      return;
    }
    await window.BPLOAudit.record("page_view", {
      path: window.location.pathname,
      title: document.title,
    }, "page", window.location.pathname);
    await refreshAuditBadge(session);
  })();

  document.querySelectorAll("[data-audit-logout]").forEach((link) => {
    link.addEventListener("click", async (event) => {
      event.preventDefault();
      await window.BPLOAudit.record("logout", { path: window.location.pathname }, "session");

      const client = getAuditClient();
      if (client) {
        await client.auth.signOut();
      }

      window.location.href = link.getAttribute("href") || "/login";
    });
  });
});
