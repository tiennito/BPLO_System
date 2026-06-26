const SUPABASE_URL = window.APP_CONFIG?.supabaseUrl || "";
const SUPABASE_ANON_KEY =
  window.APP_CONFIG?.supabaseAnonKey || window.APP_CONFIG?.supabasePublishableKey || "";
const ADMIN_EMAIL = (window.APP_CONFIG?.adminEmail || "").toLowerCase();

const form = document.getElementById("admin-create-user-form");
const statusNode = document.querySelector("[data-create-user-status]");
const successModal = document.querySelector("[data-create-user-success-modal]");
const submitButton = form?.querySelector('button[type="submit"]');
const passwordInput = form?.querySelector('input[name="password"]');
const confirmPasswordInput = form?.querySelector('input[name="confirmPassword"]');
const roleSelect = form?.querySelector('select[name="role"]');
const departmentField = document.querySelector("[data-department-field]");
const departmentSelect = document.querySelector("[data-department-select]");
const ruleNodes = {
  length: document.querySelector('[data-rule="length"]'),
  uppercase: document.querySelector('[data-rule="uppercase"]'),
  lowercase: document.querySelector('[data-rule="lowercase"]'),
  number: document.querySelector('[data-rule="number"]'),
};

let supabaseClient = null;
let departmentOptions = [];

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
  if (!statusNode) {
    return;
  }

  statusNode.textContent = message;
  statusNode.style.color = isError ? "#b42318" : "#078d36";
}

function showSuccessModal() {
  if (!successModal) {
    return;
  }

  successModal.hidden = false;
  document.body.classList.add("modal-open");
  window.lucide?.createIcons();
}

function getPasswordStatus(value) {
  return {
    length: value.length >= 8,
    uppercase: /[A-Z]/.test(value),
    lowercase: /[a-z]/.test(value),
    number: /\d/.test(value),
  };
}

function syncPasswordRules() {
  const status = getPasswordStatus(passwordInput?.value || "");

  Object.entries(ruleNodes).forEach(([rule, node]) => {
    node?.classList.toggle("is-met", Boolean(status[rule]));
  });
}

function validatePassword() {
  const password = passwordInput?.value || "";
  const confirmPassword = confirmPasswordInput?.value || "";
  const passwordStatus = getPasswordStatus(password);
  const passwordIsValid = Object.values(passwordStatus).every(Boolean);

  if (!passwordIsValid) {
    throw new Error("Password must meet all requirements.");
  }

  if (password !== confirmPassword) {
    throw new Error("Password and confirmation do not match.");
  }
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
    throw new Error("Only the configured admin account can create users.");
  }

  return session;
}

function normalizeRole(value) {
  const role = String(value || "").trim().toLowerCase().replace(/[-\s]+/g, "_");
  const aliases = {
    admin: "bplo_admin",
    administrator: "bplo_admin",
    department: "department_office",
    department_user: "department_office",
    department_office_user: "department_office",
    client: "applicant",
  };
  return aliases[role] || role;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function slugifyKey(value) {
  return String(value || "")
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
}

function departmentKeyFromName(name) {
  let key = slugifyKey(name).replace(/_(office|department)$/g, "");
  const aliases = {
    health_sanitary: "health",
    zoning_mpdc: "zoning",
    engineering: "engineering",
    fire: "fire",
  };
  return aliases[key] || key;
}

function selectedDepartment() {
  return departmentOptions.find((department) => department.id === departmentSelect?.value) || null;
}

function syncDepartmentField() {
  const isDepartment = normalizeRole(roleSelect?.value) === "department_office";
  if (departmentField) {
    departmentField.hidden = !isDepartment;
  }
  if (departmentSelect) {
    departmentSelect.required = isDepartment;
    if (!isDepartment) {
      departmentSelect.value = "";
    }
  }
}

function renderDepartmentOptions() {
  if (!departmentSelect) {
    return;
  }

  departmentSelect.innerHTML = '<option value="">--Select Department--</option>' + departmentOptions
    .filter((department) => department.status === "Active")
    .map((department) => `<option value="${escapeHtml(department.id)}">${escapeHtml(department.name)}</option>`)
    .join("");
}

async function loadDepartments(session) {
  if (!departmentSelect) {
    return;
  }

  try {
    const response = await fetch("/admin/api/departments", {
      headers: {
        "Authorization": `Bearer ${session.access_token}`,
      },
    });
    const result = await response.json();
    if (!response.ok) {
      throw new Error(result.error || "Unable to load departments.");
    }
    departmentOptions = Array.isArray(result.departments) ? result.departments : [];
    renderDepartmentOptions();
  } catch (error) {
    departmentOptions = [];
    renderDepartmentOptions();
    setStatus(error instanceof Error ? error.message : "Unable to load departments.", true);
  }
}

form?.addEventListener("submit", async (event) => {
  event.preventDefault();
  setStatus("");

  try {
    validatePassword();

    if (submitButton) {
      submitButton.disabled = true;
    }

    const session = await getAdminSession();
    const formData = new FormData(form);
    const role = normalizeRole(formData.get("role"));
    const department = role === "department_office" ? selectedDepartment() : null;

    if (role === "department_office" && !department) {
      throw new Error("Select an active department for this user.");
    }

    const payload = {
      firstName: (formData.get("firstName") || "").toString().trim(),
      lastName: (formData.get("lastName") || "").toString().trim(),
      middleName: (formData.get("middleName") || "").toString().trim(),
      suffix: (formData.get("suffix") || "").toString().trim(),
      email: (formData.get("email") || "").toString().trim(),
      contactNumber: (formData.get("contactNumber") || "").toString().trim(),
      role,
      departmentId: department?.id || "",
      departmentName: department?.name || "",
      departmentKey: department ? departmentKeyFromName(department.name) : "",
      password: (formData.get("password") || "").toString(),
    };

    setStatus("Creating user account...");
    const response = await fetch("/admin/api/users", {
      method: "POST",
      headers: {
        "Authorization": `Bearer ${session.access_token}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    });
    const result = await response.json();

    if (!response.ok) {
      throw new Error(result.error || "Unable to create user account.");
    }

    form.reset();
    syncPasswordRules();
    setStatus("");
    showSuccessModal();
  } catch (error) {
    setStatus(error instanceof Error ? error.message : "Unable to create user account.", true);
  } finally {
    if (submitButton) {
      submitButton.disabled = false;
    }
  }
});

form?.addEventListener("reset", () => {
  window.setTimeout(() => {
    syncPasswordRules();
    syncDepartmentField();
    setStatus("");
  }, 0);
});

passwordInput?.addEventListener("input", syncPasswordRules);
roleSelect?.addEventListener("change", syncDepartmentField);
syncPasswordRules();
syncDepartmentField();

window.addEventListener("DOMContentLoaded", () => {
  if (window.lucide) {
    window.lucide.createIcons();
  }
  getAdminSession()
    .then(loadDepartments)
    .catch((error) => setStatus(error instanceof Error ? error.message : "Unable to prepare user creation.", true));
});
