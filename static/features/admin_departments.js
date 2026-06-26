const SUPABASE_URL = window.APP_CONFIG?.supabaseUrl || "";
const SUPABASE_ANON_KEY =
  window.APP_CONFIG?.supabaseAnonKey || window.APP_CONFIG?.supabasePublishableKey || "";
const ADMIN_EMAIL = (window.APP_CONFIG?.adminEmail || "").toLowerCase();

const departmentsBody = document.querySelector("[data-departments-body]");
const departmentsStatus = document.querySelector("[data-departments-status]");
const searchInput = document.querySelector("[data-department-search]");
const statusFilter = document.querySelector("[data-department-status]");
const openDialogButton = document.querySelector("[data-open-department-dialog]");
const closeDialogButton = document.querySelector("[data-close-department-dialog]");
const dialog = document.querySelector("[data-department-dialog]");
const form = document.querySelector("[data-department-form]");
const formStatus = document.querySelector("[data-department-form-status]");
const submitButton = form?.querySelector('button[type="submit"]');
const dialogTitle = document.querySelector("[data-department-dialog-title]");
const dialogCopy = document.querySelector("[data-department-dialog-copy]");

let supabaseClient = null;
let departments = [];
let editingDepartmentId = "";

function initSupabase() {
  if (!window.supabase?.createClient) {
    return null;
  }

  if (!supabaseClient) {
    supabaseClient = window.supabase.createClient(SUPABASE_URL, SUPABASE_ANON_KEY);
  }

  return supabaseClient;
}

function setStatus(node, message, isError = false) {
  if (!node) {
    return;
  }

  node.textContent = message;
  node.style.color = isError ? "#b42318" : "#078d36";
}

function normalizeRole(value) {
  const role = String(value || "").trim().toLowerCase().replace(/[-\s]+/g, "_");
  return { admin: "bplo_admin", administrator: "bplo_admin" }[role] || role;
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
  const profileResponse = await fetch("/api/me/profile", {
    headers: { "Authorization": `Bearer ${session.access_token}` },
  });
  const profilePayload = await profileResponse.json().catch(() => ({}));
  const role = normalizeRole(profilePayload.profile?.role || session.user?.app_metadata?.role);
  if (!profileResponse.ok || profilePayload.profile?.status !== "active") {
    throw new Error(profilePayload.error || "Your admin profile is not active.");
  }
  if (ADMIN_EMAIL && signedInEmail !== ADMIN_EMAIL && !["super_admin", "bplo_admin"].includes(role)) {
    throw new Error("Only the configured admin account can manage departments.");
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

function getFilteredDepartments() {
  const searchTerm = (searchInput?.value || "").toLowerCase().trim();
  const selectedStatus = statusFilter?.value || "";

  return departments.filter((department) => {
    const matchesSearch =
      !searchTerm ||
      (department.name || "").toLowerCase().includes(searchTerm) ||
      (department.description || "").toLowerCase().includes(searchTerm);
    const matchesStatus = !selectedStatus || department.status === selectedStatus;

    return matchesSearch && matchesStatus;
  });
}

function renderDepartments() {
  if (!departmentsBody) {
    return;
  }

  const filteredDepartments = getFilteredDepartments();

  if (!departments.length) {
    departmentsBody.innerHTML = `
      <tr>
        <td colspan="5">
          <div class="users-empty-state departments-empty-state">
            <strong>No departments yet</strong>
            <p>Create a department to start organizing system users.</p>
          </div>
        </td>
      </tr>
    `;
    return;
  }

  if (!filteredDepartments.length) {
    departmentsBody.innerHTML = `
      <tr>
        <td colspan="5">
          <div class="users-empty-state departments-empty-state">
            <strong>No matching departments</strong>
            <p>Try another search or status filter.</p>
          </div>
        </td>
      </tr>
    `;
    return;
  }

  departmentsBody.innerHTML = filteredDepartments
    .map(
      (department) => `
        <tr>
          <td>${escapeHtml(department.name)}</td>
          <td>${escapeHtml(department.description || "-")}</td>
          <td><span class="status-pill status-pill--${escapeHtml(department.status.toLowerCase())}">${escapeHtml(department.status)}</span></td>
          <td>${escapeHtml(formatDate(department.createdAt))}</td>
          <td>
            <div class="table-action-row">
              <button class="table-action" type="button" data-edit-department="${escapeHtml(department.id)}">Edit</button>
              <button class="table-action table-action--danger" type="button" data-delete-department="${escapeHtml(department.id)}">Delete</button>
            </div>
          </td>
        </tr>
      `
    )
    .join("");
}

async function loadDepartments() {
  try {
    setStatus(departmentsStatus, "Loading departments...");
    const session = await getAdminSession();
    const response = await fetch("/admin/api/departments", {
      headers: {
        "Authorization": `Bearer ${session.access_token}`,
      },
    });
    const result = await response.json();

    if (!response.ok) {
      throw new Error(result.error || "Unable to load departments.");
    }

    departments = Array.isArray(result.departments) ? result.departments : [];
    renderDepartments();
    setStatus(
      departmentsStatus,
      `${departments.length} department${departments.length === 1 ? "" : "s"} loaded.`
    );
  } catch (error) {
    departments = [];
    renderDepartments();
    setStatus(
      departmentsStatus,
      error instanceof Error ? error.message : "Unable to load departments.",
      true
    );
  }
}

function setDialogMode(mode, department = null) {
  editingDepartmentId = mode === "edit" && department ? department.id : "";

  if (dialogTitle) {
    dialogTitle.textContent = mode === "edit" ? "Edit Department" : "Add Department";
  }

  if (dialogCopy) {
    dialogCopy.textContent =
      mode === "edit"
        ? "Update this department record."
        : "Create a department record for system users.";
  }

  if (submitButton) {
    submitButton.textContent = mode === "edit" ? "Update Department" : "Create Department";
  }

  if (form && department) {
    form.elements.name.value = department.name || "";
    form.elements.description.value = department.description || "";
    form.elements.status.value = department.status || "Active";
  }
}

async function saveDepartment(event) {
  event.preventDefault();

  try {
    if (submitButton) {
      submitButton.disabled = true;
    }

    const formData = new FormData(form);
    const payload = {
      name: (formData.get("name") || "").toString().trim(),
      description: (formData.get("description") || "").toString().trim(),
      status: (formData.get("status") || "Active").toString(),
    };

    if (!payload.name) {
      throw new Error("Department name is required.");
    }

    setStatus(formStatus, editingDepartmentId ? "Updating department..." : "Creating department...");
    const session = await getAdminSession();
    const endpoint = editingDepartmentId
      ? `/admin/api/departments/${encodeURIComponent(editingDepartmentId)}`
      : "/admin/api/departments";
    const response = await fetch(endpoint, {
      method: editingDepartmentId ? "PATCH" : "POST",
      headers: {
        "Authorization": `Bearer ${session.access_token}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    });
    const result = await response.json();

    if (!response.ok) {
      throw new Error(result.error || "Unable to save department.");
    }

    form.reset();
    editingDepartmentId = "";
    dialog?.close();
    await loadDepartments();
  } catch (error) {
    setStatus(
      formStatus,
      error instanceof Error ? error.message : "Unable to save department.",
      true
    );
  } finally {
    if (submitButton) {
      submitButton.disabled = false;
    }
  }
}

async function deleteDepartment(departmentId) {
  const department = departments.find((item) => item.id === departmentId);
  const label = department?.name || "this department";

  if (!window.confirm(`Delete ${label}? This cannot be undone.`)) {
    return;
  }

  try {
    setStatus(departmentsStatus, "Deleting department...");
    const session = await getAdminSession();
    const response = await fetch(`/admin/api/departments/${encodeURIComponent(departmentId)}`, {
      method: "DELETE",
      headers: {
        "Authorization": `Bearer ${session.access_token}`,
      },
    });
    const result = await response.json();

    if (!response.ok) {
      throw new Error(result.error || "Unable to delete department.");
    }

    await loadDepartments();
  } catch (error) {
    setStatus(
      departmentsStatus,
      error instanceof Error ? error.message : "Unable to delete department.",
      true
    );
  }
}

openDialogButton?.addEventListener("click", () => {
  form?.reset();
  setDialogMode("create");
  setStatus(formStatus, "");
  dialog?.showModal();
});

closeDialogButton?.addEventListener("click", () => {
  editingDepartmentId = "";
  dialog?.close();
});

departmentsBody?.addEventListener("click", (event) => {
  const target = event.target;
  if (!(target instanceof HTMLElement)) {
    return;
  }

  const editButton = target.closest("[data-edit-department]");
  if (editButton instanceof HTMLElement) {
    const departmentId = editButton.getAttribute("data-edit-department") || "";
    const department = departments.find((item) => item.id === departmentId);

    if (department) {
      setStatus(formStatus, "");
      setDialogMode("edit", department);
      dialog?.showModal();
    }
    return;
  }

  const deleteButton = target.closest("[data-delete-department]");
  if (deleteButton instanceof HTMLElement) {
    const departmentId = deleteButton.getAttribute("data-delete-department") || "";
    if (departmentId) {
      void deleteDepartment(departmentId);
    }
  }
});

form?.addEventListener("submit", saveDepartment);
searchInput?.addEventListener("input", renderDepartments);
statusFilter?.addEventListener("change", renderDepartments);

window.addEventListener("DOMContentLoaded", () => {
  if (window.lucide) {
    window.lucide.createIcons();
  }

  loadDepartments();
});
