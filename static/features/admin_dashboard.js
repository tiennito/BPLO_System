const DASHBOARD_SUPABASE_URL = window.APP_CONFIG?.supabaseUrl || "";
const DASHBOARD_SUPABASE_KEY =
  window.APP_CONFIG?.supabaseAnonKey || window.APP_CONFIG?.supabasePublishableKey || "";
const DASHBOARD_ADMIN_EMAIL = (window.APP_CONFIG?.adminEmail || "").toLowerCase();

const dashboardStatus = document.querySelector("[data-dashboard-status]");
let dashboardClient = null;

function initDashboardSupabase() {
  if (!window.supabase?.createClient) {
    return null;
  }

  if (!dashboardClient) {
    dashboardClient = window.supabase.createClient(DASHBOARD_SUPABASE_URL, DASHBOARD_SUPABASE_KEY);
  }

  return dashboardClient;
}

function setDashboardStatus(message, isError = false) {
  if (!dashboardStatus) {
    return;
  }

  dashboardStatus.textContent = message;
  dashboardStatus.style.color = isError ? "#b42318" : "#078d36";
}

async function getDashboardAdminSession() {
  const client = initDashboardSupabase();
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
  if (DASHBOARD_ADMIN_EMAIL && signedInEmail !== DASHBOARD_ADMIN_EMAIL) {
    throw new Error("Only the configured admin account can view dashboard data.");
  }

  return session;
}

function setDashboardCount(key, value) {
  document.querySelectorAll(`[data-dashboard-count="${key}"]`).forEach((node) => {
    node.textContent = String(value);
  });
}

function renderDashboardCounts(users) {
  const activeUsers = users.filter((user) => user.status === "Active");
  const adminUsers = users.filter((user) => user.role === "admin");
  const departmentUsers = users.filter((user) => user.role === "department");
  const clientUsers = users.filter((user) => ["client", "applicant"].includes(user.role));

  setDashboardCount("totalUsers", activeUsers.length);
  setDashboardCount("adminUsers", adminUsers.length);
  setDashboardCount("departmentUsers", departmentUsers.length);
  setDashboardCount("clientUsers", clientUsers.length);
}

async function loadDashboardData() {
  try {
    setDashboardStatus("Loading dashboard data...");
    const session = await getDashboardAdminSession();
    const response = await fetch("/admin/api/users", {
      headers: {
        "Authorization": `Bearer ${session.access_token}`,
      },
    });
    const result = await response.json();

    if (!response.ok) {
      throw new Error(result.error || "Unable to load dashboard data.");
    }

    const users = Array.isArray(result.users) ? result.users : [];
    renderDashboardCounts(users);
    setDashboardStatus(`${users.length} user${users.length === 1 ? "" : "s"} counted.`);
  } catch (error) {
    setDashboardStatus(error instanceof Error ? error.message : "Unable to load dashboard data.", true);
  }
}

window.addEventListener("DOMContentLoaded", () => {
  window.lucide?.createIcons();
  void loadDashboardData();
});
