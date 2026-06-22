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
const ruleNodes = {
  length: document.querySelector('[data-rule="length"]'),
  uppercase: document.querySelector('[data-rule="uppercase"]'),
  lowercase: document.querySelector('[data-rule="lowercase"]'),
  number: document.querySelector('[data-rule="number"]'),
};

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
  if (ADMIN_EMAIL && signedInEmail !== ADMIN_EMAIL) {
    throw new Error("Only the configured admin account can create users.");
  }

  return session;
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
    const payload = {
      firstName: (formData.get("firstName") || "").toString().trim(),
      lastName: (formData.get("lastName") || "").toString().trim(),
      middleName: (formData.get("middleName") || "").toString().trim(),
      suffix: (formData.get("suffix") || "").toString().trim(),
      email: (formData.get("email") || "").toString().trim(),
      contactNumber: (formData.get("contactNumber") || "").toString().trim(),
      role: (formData.get("role") || "").toString().trim(),
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
    setStatus("");
  }, 0);
});

passwordInput?.addEventListener("input", syncPasswordRules);
syncPasswordRules();

window.addEventListener("DOMContentLoaded", () => {
  if (window.lucide) {
    window.lucide.createIcons();
  }
});
