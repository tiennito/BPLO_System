const SUPABASE_URL = window.APP_CONFIG?.supabaseUrl || "";
const SUPABASE_ANON_KEY =
  window.APP_CONFIG?.supabaseAnonKey || window.APP_CONFIG?.supabasePublishableKey || "";

const form = document.getElementById("register-form");
const stages = Array.from(document.querySelectorAll(".stage"));
const indicators = Array.from(document.querySelectorAll("[data-step-indicator]"));
const confirmEmail = document.getElementById("confirm-email");
const otpInputs = Array.from(document.querySelectorAll(".code-boxes input"));
const otpConfirmButton = document.querySelector("[data-otp-confirm]");
const otpResendButton = document.querySelector("[data-otp-resend]");
const otpContinueButton = document.querySelector("[data-otp-continue]");
const otpChangeEmailButton = document.querySelector(".text-button");
const statusNode = document.querySelector(".register-card .auth-status");
const passwordInput = document.getElementById("password");
const passwordRuleNodes = {
  length: document.querySelector('[data-rule="length"]'),
  uppercase: document.querySelector('[data-rule="uppercase"]'),
  lowercase: document.querySelector('[data-rule="lowercase"]'),
  number: document.querySelector('[data-rule="number"]'),
};

let supabaseClient = null;
let registeredEmail = "";
let resendCountdownTimer = null;
let resendCountdownSeconds = 0;

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

  const { error } = await client.auth.signUp({
    email: values.email,
    password: values.password,
    options: {
      data: metadata,
    },
  });

  if (error) {
    throw error;
  }
}

async function resendVerificationCode() {
  const client = initSupabase();
  if (!client) {
    throw new Error("Supabase client is unavailable in this browser.");
  }

  if (!registeredEmail) {
    throw new Error("Register an email first.");
  }

  const { error } = await client.auth.resend({
    type: "signup",
    email: registeredEmail,
  });

  if (error) {
    throw error;
  }
}

async function verifyRegistrationOtp() {
  const client = initSupabase();
  if (!client) {
    throw new Error("Supabase client is unavailable in this browser.");
  }

  const token = otpInputs.map((input) => input.value.trim()).join("");
  if (token.length !== 6) {
    throw new Error("Enter the 6-digit verification code.");
  }

  const { error } = await client.auth.verifyOtp({
    email: registeredEmail,
    token,
    type: "email",
  });

  if (error) {
    throw error;
  }

  setStatus("Email verified successfully.");
  setStage("success");
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
  button.setAttribute(
    "aria-label",
    visible ? `Show ${targetId.replace("_", " ")}` : `Hide ${targetId.replace("_", " ")}`
  );
}

function clearOtpInputs() {
  otpInputs.forEach((input) => {
    input.value = "";
  });
  otpInputs[0]?.focus();
}

function setResendState(seconds) {
  resendCountdownSeconds = seconds;

  if (!otpResendButton) {
    return;
  }

  if (resendCountdownTimer) {
    window.clearInterval(resendCountdownTimer);
    resendCountdownTimer = null;
  }

  if (seconds <= 0) {
    otpResendButton.disabled = false;
    otpResendButton.textContent = "Resend";
    return;
  }

  otpResendButton.disabled = true;
  otpResendButton.textContent = `Resend in ${seconds}s`;

  resendCountdownTimer = window.setInterval(() => {
    resendCountdownSeconds -= 1;
    if (resendCountdownSeconds <= 0) {
      window.clearInterval(resendCountdownTimer);
      resendCountdownTimer = null;
      otpResendButton.disabled = false;
      otpResendButton.textContent = "Resend";
      return;
    }

    otpResendButton.textContent = `Resend in ${resendCountdownSeconds}s`;
  }, 1000);
}

function resetResendState() {
  setResendState(0);
}

document.querySelectorAll("[data-password-toggle]").forEach((button) => {
  button.addEventListener("click", () => {
    togglePasswordVisibility(button.getAttribute("data-password-toggle"), button);
  });
});

passwordInput?.addEventListener("input", syncPasswordRules);
syncPasswordRules();

otpInputs.forEach((input, index) => {
  input.addEventListener("input", () => {
    input.value = input.value.replace(/\D/g, "").slice(0, 1);
    if (input.value && index < otpInputs.length - 1) {
      otpInputs[index + 1]?.focus();
    }
  });

  input.addEventListener("keydown", (event) => {
    if (event.key === "Backspace" && !input.value && index > 0) {
      otpInputs[index - 1]?.focus();
    }
  });
});

document.querySelector("[data-next]")?.addEventListener("click", () => {
  setStage(2);
});

document.querySelector("[data-prev]")?.addEventListener("click", () => {
  setStage(1);
});

otpConfirmButton?.addEventListener("click", async () => {
  setStatus("Verifying code...");

  try {
    await verifyRegistrationOtp();
  } catch (error) {
    setStatus(error instanceof Error ? error.message : "Verification failed.", true);
  }
});

otpResendButton?.addEventListener("click", async () => {
  try {
    otpResendButton.disabled = true;
    setStatus("Resending code...");
    await resendVerificationCode();
    clearOtpInputs();
    setResendState(60);
    setStatus("Verification code resent.");
  } catch (error) {
    setStatus(error instanceof Error ? error.message : "Resend failed.", true);
    setResendState(Math.max(resendCountdownSeconds, 1));
  }
});

otpChangeEmailButton?.addEventListener("click", () => {
  setStage(2);
  setStatus("");
  resetResendState();
});

otpContinueButton?.addEventListener("click", () => {
  window.location.href = "/";
});

form?.addEventListener("submit", async (event) => {
  event.preventDefault();

  try {
    const values = getFormData();
    validateStep2(values);
    syncPasswordRules();
    registeredEmail = values.email;
    confirmEmail.textContent = values.email || "your email";
    setStatus("Sending verification code...");
    await registerWithSupabase(values);
    clearOtpInputs();
    setStage("confirm");
    setStatus("Enter the 6-digit code sent to your email.");
    setResendState(60);
  } catch (error) {
    setStatus(error instanceof Error ? error.message : "Registration failed.", true);
  }
});

setStage(1);
