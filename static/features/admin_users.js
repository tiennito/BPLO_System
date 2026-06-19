const SUPABASE_URL = window.APP_CONFIG?.supabaseUrl || "";
const SUPABASE_ANON_KEY =
  window.APP_CONFIG?.supabaseAnonKey || window.APP_CONFIG?.supabasePublishableKey || "";
const ADMIN_EMAIL = (window.APP_CONFIG?.adminEmail || "").toLowerCase();

const usersBody = document.querySelector("[data-users-body]");
const usersStatus = document.querySelector("[data-users-status]");
const searchInput = document.querySelector("[data-user-search]");
const roleFilter = document.querySelector("[data-role-filter]");
const statusFilter = document.querySelector("[data-status-filter]");
const refreshButton = document.querySelector("[data-refresh-users]");
const selectTypeButton = document.querySelector("[data-select-user-type]");
const userTypeDialog = document.querySelector("[data-user-type-dialog]");
const userTypeButtons = Array.from(document.querySelectorAll("[data-user-type]"));

let supabaseClient = null;
let users = [];

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
  if (!usersStatus) {
    return;
  }

  usersStatus.textContent = message;
  usersStatus.style.color = isError ? "#b42318" : "#078d36";
}

async function getAdminSession() {
  const client = initSupabase();
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
  if (ADMIN_EMAIL && signedInEmail !== ADMIN_EMAIL) {
    throw new Error("Only the configured admin account can view users.");
  }

  return session;
}

function formatDate(value) {
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

function formatRole(value) {
  const roleLabels = {
    admin: "Admin",
    department: "Department User",
    client: "Client",
    employee: "Employee",
  };

  return roleLabels[value] || value || "Client";
}

function getFilteredUsers() {
  const searchTerm = (searchInput?.value || "").toLowerCase().trim();
  const selectedRole = roleFilter?.value || "";
  const selectedStatus = statusFilter?.value || "";

  return users.filter((user) => {
    const matchesSearch =
      !searchTerm ||
      (user.name || "").toLowerCase().includes(searchTerm) ||
      (user.email || "").toLowerCase().includes(searchTerm);
    const matchesRole = !selectedRole || user.role === selectedRole;
    const matchesStatus = !selectedStatus || user.status === selectedStatus;

    return matchesSearch && matchesRole && matchesStatus;
  });
}

function renderUsers() {
  if (!usersBody) {
    return;
  }

  const filteredUsers = getFilteredUsers();

  if (!users.length) {
    usersBody.innerHTML = `
      <tr>
        <td colspan="7">
          <div class="users-empty-state">
            <strong>No users found</strong>
            <p>Create an account first, then refresh this list.</p>
            <a href="/admin/create-user">Add new user</a>
          </div>
        </td>
      </tr>
    `;
    return;
  }

  if (!filteredUsers.length) {
    usersBody.innerHTML = `
      <tr>
        <td colspan="7">
          <div class="users-empty-state">
            <strong>No matching users</strong>
            <p>Try a different search, role, or status filter.</p>
          </div>
        </td>
      </tr>
    `;
    return;
  }

  usersBody.innerHTML = filteredUsers
    .map(
      (user) => `
        <tr>
          <td>${escapeHtml(user.name)}</td>
          <td>${escapeHtml(user.email)}</td>
          <td>${escapeHtml(formatRole(user.role))}</td>
          <td>${escapeHtml(user.department || "-")}</td>
          <td><span class="status-pill status-pill--${escapeHtml(user.status.toLowerCase())}">${escapeHtml(user.status)}</span></td>
          <td>${escapeHtml(formatDate(user.createdAt))}</td>
          <td><button class="table-action" type="button">View</button></td>
        </tr>
      `
    )
    .join("");
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

async function loadUsers() {
  try {
    setStatus("Loading users...");
    if (refreshButton) {
      refreshButton.disabled = true;
    }

    const session = await getAdminSession();
    const response = await fetch("/admin/api/users", {
      headers: {
        "Authorization": `Bearer ${session.access_token}`,
      },
    });
    const result = await response.json();

    if (!response.ok) {
      throw new Error(result.error || "Unable to load users.");
    }

    users = Array.isArray(result.users) ? result.users : [];
    renderUsers();
    setStatus(`${users.length} user${users.length === 1 ? "" : "s"} loaded.`);
  } catch (error) {
    users = [];
    renderUsers();
    setStatus(error instanceof Error ? error.message : "Unable to load users.", true);
  } finally {
    if (refreshButton) {
      refreshButton.disabled = false;
    }
  }
}

searchInput?.addEventListener("input", renderUsers);
roleFilter?.addEventListener("change", renderUsers);
statusFilter?.addEventListener("change", renderUsers);
refreshButton?.addEventListener("click", loadUsers);
selectTypeButton?.addEventListener("click", () => {
  userTypeDialog?.showModal();
});
userTypeDialog?.addEventListener("click", (event) => {
  if (event.target === userTypeDialog) {
    userTypeDialog.close();
  }
});
userTypeButtons.forEach((button) => {
  button.addEventListener("click", async () => {
    const selectedType = button.getAttribute("data-user-type") || "";

    if (roleFilter) {
      roleFilter.value = selectedType;
    }

    userTypeDialog?.close();

    if (!users.length) {
      await loadUsers();
      return;
    }

    renderUsers();
    setStatus(`Showing ${button.textContent.trim()} users.`);
  });
});

window.addEventListener("DOMContentLoaded", () => {
  if (window.lucide) {
    window.lucide.createIcons();
  }
});
