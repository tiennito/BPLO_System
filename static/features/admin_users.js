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
const userDetailsDialog = document.querySelector("[data-user-details-dialog]");
const userDetailsContent = document.querySelector("[data-user-details-content]");
const closeUserDetailsButton = document.querySelector("[data-close-user-details]");

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

function formatRole(value) {
  const roleLabels = {
    admin: "Admin",
    department: "Department User",
    treasury: "Treasury User",
    client: "Client",
    applicant: "Applicant",
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
          <td><button class="table-action" type="button" data-view-user="${escapeHtml(user.id)}">View</button></td>
        </tr>
      `
    )
    .join("");
}

function detailItem(label, value) {
  return `
    <div class="user-detail-item">
      <span>${escapeHtml(label)}</span>
      <strong>${escapeHtml(value || "-")}</strong>
    </div>
  `;
}

function getProviderLabel(user) {
  const appMetadata = user.appMetadata || {};
  const providers = Array.isArray(appMetadata.providers) ? appMetadata.providers : [];
  return providers.length ? providers.join(", ") : appMetadata.provider || "Email";
}

function showUserDetails(userId) {
  const user = users.find((item) => item.id === userId);
  if (!user || !userDetailsDialog || !userDetailsContent) {
    return;
  }

  userDetailsContent.innerHTML = `
    <section class="user-details-summary">
      <div class="user-avatar">${escapeHtml((user.name || user.email || "U").slice(0, 1).toUpperCase())}</div>
      <div>
        <h3>${escapeHtml(user.name || "Unnamed user")}</h3>
        <p>${escapeHtml(user.email || "-")}</p>
      </div>
      <span class="status-pill status-pill--${escapeHtml(user.status.toLowerCase())}">${escapeHtml(user.status)}</span>
    </section>
    <section class="user-details-grid">
      ${detailItem("User ID", user.id)}
      ${detailItem("Role", formatRole(user.role))}
      ${detailItem("Department", user.department)}
      ${detailItem("Provider", getProviderLabel(user))}
      ${detailItem("First Name", user.firstName)}
      ${detailItem("Middle Name", user.middleName)}
      ${detailItem("Last Name", user.lastName)}
      ${detailItem("Suffix", user.suffix)}
      ${detailItem("Contact Number", user.contactNumber)}
      ${detailItem("Created", formatDateTime(user.createdAt))}
      ${detailItem("Updated", formatDateTime(user.updatedAt))}
      ${detailItem("Last Sign In", formatDateTime(user.lastSignInAt))}
      ${detailItem("Email Confirmed", formatDateTime(user.emailConfirmedAt))}
      ${detailItem("Banned Until", formatDateTime(user.bannedUntil))}
    </section>
  `;
  userDetailsDialog.showModal();
  window.lucide?.createIcons();
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
usersBody?.addEventListener("click", (event) => {
  const target = event.target;
  if (!(target instanceof HTMLElement)) {
    return;
  }

  const button = target.closest("[data-view-user]");
  if (!(button instanceof HTMLElement)) {
    return;
  }

  showUserDetails(button.getAttribute("data-view-user") || "");
});
closeUserDetailsButton?.addEventListener("click", () => userDetailsDialog?.close());
userDetailsDialog?.addEventListener("click", (event) => {
  if (event.target === userDetailsDialog) {
    userDetailsDialog.close();
  }
});

window.addEventListener("DOMContentLoaded", () => {
  if (window.lucide) {
    window.lucide.createIcons();
  }
  void loadUsers();
});
