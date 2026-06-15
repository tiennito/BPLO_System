const SUPABASE_URL = "https://rvbnresadttfmbqtcxlj.supabase.co";
const SUPABASE_ANON_KEY =
  "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InJ2Ym5yZXNhZHR0Zm1icXRjeGxqIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODE0OTAwMzQsImV4cCI6MjA5NzA2NjAzNH0.zbKSpNn-UaPP8lobXOJc8tM7DMQSO3rt9w0JNW97dRI";

const form = document.getElementById("register-form");
const stages = Array.from(document.querySelectorAll(".stage"));
const indicators = Array.from(document.querySelectorAll("[data-step-indicator]"));
const confirmEmail = document.getElementById("confirm-email");
const passwordInput = document.getElementById("password");
const confirmPasswordInput = document.getElementById("confirm_password");
const passwordRuleNodes = {
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

function setStage(stage) {
  stages.forEach((node) => node.classList.remove("stage--active"));

  const activeStage =
    stage === 1
      ? document.querySelector('[data-stage="1"]')
      : stage === 2
        ? document.querySelector('[data-stage="2"]')
        : document.querySelector(`[data-stage="${stage}"]`);

  if (activeStage) {
    activeStage.classList.add("stage--active");
  }

  indicators.forEach((indicator) => {
    const number = Number(indicator.getAttribute("data-step-indicator"));
    indicator.classList.toggle("step--active", number <= (stage === 1 ? 1 : 2));
  });
}

function getFormData() {
  const data = new FormData(form);
  const firstName = (data.get("first_name") || "").toString().trim();

  return {
    first_name_01: firstName ? `01 ${firstName}` : "",
    first_name_raw: firstName,
    last_name: (data.get("last_name") || "").toString().trim(),
    middle_name: (data.get("middle_name") || "").toString().trim(),
    suffix: (data.get("suffix") || "").toString().trim(),
    region: (data.get("region") || "").toString().trim(),
    province: (data.get("province") || "").toString().trim(),
    city: (data.get("city") || "").toString().trim(),
    barangay: (data.get("barangay") || "").toString().trim(),
    street: (data.get("street") || "").toString().trim(),
    postal_code: (data.get("postal_code") || "").toString().trim(),
    email: (data.get("email") || "").toString().trim(),
    contact_number: (data.get("contact_number") || "").toString().trim(),
    password: (data.get("password") || "").toString(),
    confirm_password: (data.get("confirm_password") || "").toString(),
  };
}

function validateStep2(values) {
  if (values.password !== values.confirm_password) {
    throw new Error("Password and confirmation do not match.");
  }

  if (values.password.length < 8) {
    throw new Error("Password must be at least 8 characters.");
  }
}

async function registerWithSupabase(values) {
  const client = initSupabase();
  if (!client) {
    throw new Error("Supabase client is unavailable in this browser.");
  }

  const metadata = {
    first_name: values.first_name_raw,
    first_name_01: values.first_name_01,
    last_name: values.last_name,
    middle_name: values.middle_name,
    suffix: values.suffix,
    contact_number: values.contact_number,
    address_region: values.region,
    address_province: values.province,
    address_city: values.city,
    address_barangay: values.barangay,
    address_street: values.street,
    postal_code: values.postal_code,
  };

  const { data, error } = await client.auth.signUp({
    email: values.email,
    password: values.password,
    options: {
      data: metadata,
    },
  });

  if (error) {
    throw error;
  }

  return data;
}

document.querySelector("[data-next]")?.addEventListener("click", () => {
  setStage(2);
});

document.querySelector("[data-prev]")?.addEventListener("click", () => {
  setStage(1);
});

function getPasswordStatus(value) {
  return {
    length: value.length >= 8,
    uppercase: /[A-Z]/.test(value),
    lowercase: /[a-z]/.test(value),
    number: /\d/.test(value),
  };
}

function syncPasswordRules() {
  if (!passwordInput) {
    return;
  }

  const status = getPasswordStatus(passwordInput.value);

  Object.entries(passwordRuleNodes).forEach(([key, node]) => {
    if (!node) {
      return;
    }

    const input = node.querySelector("input");
    const met = Boolean(status[key]);
    node.classList.toggle("is-met", met);
    if (input) {
      input.checked = met;
    }
  });
}

function togglePasswordVisibility(targetId, button) {
  const input = document.getElementById(targetId);
  if (!input || !(input instanceof HTMLInputElement)) {
    return;
  }

  const visible = input.type === "text";
  input.type = visible ? "password" : "text";
  button.textContent = visible ? "Show" : "Hide";
  button.setAttribute("aria-label", visible ? `Show ${targetId.replace("_", " ")}` : `Hide ${targetId.replace("_", " ")}`);
}

document.querySelectorAll("[data-password-toggle]").forEach((button) => {
  button.addEventListener("click", () => {
    togglePasswordVisibility(button.getAttribute("data-password-toggle"), button);
  });
});

passwordInput?.addEventListener("input", syncPasswordRules);
syncPasswordRules();

form?.addEventListener("submit", async (event) => {
  event.preventDefault();

  try {
    const values = getFormData();
    validateStep2(values);
    syncPasswordRules();
    confirmEmail.textContent = values.email || "your email";
    await registerWithSupabase(values);
    setStage("confirm");
  } catch (error) {
    window.alert(error instanceof Error ? error.message : "Registration failed.");
  }
});

setStage(1);
