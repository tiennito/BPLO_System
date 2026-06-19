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

    setStatus("Signed in successfully. Redirecting...");
    window.location.assign("/applicant/dashboard");
  } catch (error) {
    setStatus(error instanceof Error ? error.message : "Login failed.", true);
    if (submitButton) {
      submitButton.disabled = false;
    }
  }
});
