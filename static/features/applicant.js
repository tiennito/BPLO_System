const SUPABASE_URL = window.APP_CONFIG?.supabaseUrl || "";
const SUPABASE_ANON_KEY =
  window.APP_CONFIG?.supabaseAnonKey || window.APP_CONFIG?.supabasePublishableKey || "";

const fields = {
  fullName: document.querySelector('[data-field="fullName"]'),
  email: document.querySelector('[data-field="email"]'),
  contact: document.querySelector('[data-field="contact"]'),
  address: document.querySelector('[data-field="address"]'),
};
const profileName = document.querySelector("[data-profile-name]");
const profileToggle = document.querySelector("[data-profile-toggle]");
const profileDropdown = document.querySelector("[data-profile-dropdown]");
const logoutButton = document.querySelector("[data-logout]");

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

function setField(name, value) {
  if (fields[name]) {
    fields[name].value = value || "";
  }
}

function formatFullName(profile, user) {
  const metadata = user?.user_metadata || {};
  const firstName = profile?.first_name_raw || metadata.first_name || "";
  const middleName = profile?.middle_name || metadata.middle_name || "";
  const lastName = profile?.last_name || metadata.last_name || "";
  const suffix = profile?.suffix || metadata.suffix || "";

  return [firstName, middleName, lastName, suffix].filter(Boolean).join(" ");
}

function formatAddress(profile, user) {
  const metadata = user?.user_metadata || {};
  const parts = [
    profile?.address_street || metadata.address_street,
    profile?.address_barangay || metadata.address_barangay,
    profile?.address_city || metadata.address_city,
    profile?.address_province || metadata.address_province,
    profile?.postal_code || metadata.postal_code,
  ];

  return parts.filter(Boolean).join(", ");
}

async function loadApplicantDashboard() {
  const client = initSupabase();
  if (!client) {
    window.location.href = "/login";
    return;
  }

  const {
    data: { user },
    error: userError,
  } = await client.auth.getUser();

  if (userError || !user) {
    window.location.href = "/login";
    return;
  }

  const { data: profile } = await client
    .from("applicants")
    .select("*")
    .eq("user_id", user.id)
    .maybeSingle();

  const fullName = formatFullName(profile, user) || "Applicant";
  setField("fullName", fullName);
  setField("email", profile?.email || user.email || "");
  setField("contact", profile?.contact_number || user.user_metadata?.contact_number || "");
  setField("address", formatAddress(profile, user));

  if (profileName) {
    profileName.textContent = fullName;
  }
}

profileToggle?.addEventListener("click", () => {
  profileDropdown?.classList.toggle("is-open");
});

document.addEventListener("click", (event) => {
  if (!profileDropdown?.classList.contains("is-open")) {
    return;
  }

  const target = event.target;
  if (target instanceof Node && !profileDropdown.contains(target) && !profileToggle?.contains(target)) {
    profileDropdown.classList.remove("is-open");
  }
});

logoutButton?.addEventListener("click", async () => {
  const client = initSupabase();
  await client?.auth.signOut();
  window.location.href = "/login";
});

window.addEventListener("DOMContentLoaded", () => {
  window.lucide?.createIcons();
  loadApplicantDashboard();
});
