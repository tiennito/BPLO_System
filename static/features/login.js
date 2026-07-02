const SUPABASE_URL = window.APP_CONFIG?.supabaseUrl || "";
const SUPABASE_ANON_KEY =
  window.APP_CONFIG?.supabaseAnonKey || window.APP_CONFIG?.supabasePublishableKey || "";
const form = document.querySelector(".login-card");
const statusNode = document.querySelector("[data-login-status]");
const submitButton = form?.querySelector('button[type="submit"]');
let supabaseClient = null;

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
  statusNode.style.color = isError ? "#b42318" : "#0c8c36";
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

async function fetchCurrentProfile(session) {
  const response = await fetch("/api/me/profile", {
    headers: {
      "Authorization": `Bearer ${session.access_token}`,
    },
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload.error || "Login succeeded, but no user profile was found.");
  }
  return payload;
}

function getRedirectPath(profilePayload) {
  const profile = profilePayload.profile || {};
  const role = normalizeRole(profile.role);
  const status = String(profile.status || "").trim().toLowerCase();
  const redirectPath = profilePayload.redirectPath || {
    super_admin: "/admin/dashboard",
    bplo_admin: "/admin/staff-administrator",
    department_office: "/department/dashboard",
    treasury: "/treasury/dashboard",
    applicant: "/applicant/dashboard",
  }[role];

  console.debug("[auth] login session", {
    authUserId: profile.authUserId,
    email: profile.email,
    role,
    status,
    departmentId: profile.departmentId || "",
    redirectPath,
  });

  if (status !== "active") {
    throw new Error(`This account is ${status}. Please contact the administrator.`);
  }

  if (role === "department_office" && !profile.departmentId) {
    throw new Error("This department account is missing a department assignment. Please contact the administrator.");
  }

  if (!redirectPath) {
    throw new Error(`This account role (${role || "missing"}) is not allowed to access a dashboard.`);
  }

  return redirectPath;
}

async function recordAuditEvent(session, action, details = {}) {
  try {
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
        entityType: "session",
      }),
    });
  } catch {
    // Audit failures should not block login.
  }
}

form?.addEventListener("submit", async (event) => {
  event.preventDefault();
  setStatus("Signing in...");
  if (submitButton) {
    submitButton.disabled = true;
  }

  try {
    const client = initSupabase();
    if (!client) {
      throw new Error("Supabase client is unavailable in this browser.");
    }

    const formData = new FormData(form);
    const email = (formData.get("email") || "").toString().trim();
    const password = (formData.get("password") || "").toString();

    const { data, error } = await client.auth.signInWithPassword({
      email,
      password,
    });

    if (error) {
      throw error;
    }

    const session = data.session || (await client.auth.getSession()).data.session;
    if (!session) {
      throw new Error("Login succeeded, but no active session was saved. Please try again.");
    }

    const profilePayload = await fetchCurrentProfile(session);
    const redirectPath = getRedirectPath(profilePayload);

    setStatus("Signed in successfully. Redirecting...");
    console.debug("[auth] redirect path", redirectPath);
    await recordAuditEvent(session, "login", { redirectPath });
    window.location.assign(redirectPath);
  } catch (error) {
    setStatus(error instanceof Error ? error.message : "Login failed.", true);
    if (submitButton) {
      submitButton.disabled = false;
    }
  }
});
