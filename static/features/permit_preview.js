const PREVIEW_SUPABASE_URL = window.APP_CONFIG?.supabaseUrl || "";
const PREVIEW_SUPABASE_KEY =
  window.APP_CONFIG?.supabaseAnonKey || window.APP_CONFIG?.supabasePublishableKey || "";

const permitMessage = document.querySelector("[data-permit-message]");
const permitPage = document.querySelector("[data-permit-page]");
const permitNumber = document.querySelector("[data-permit-number]");
const permitStatus = document.querySelector("[data-permit-status]");
const eligibilityList = document.querySelector("[data-permit-eligibility]");
const releaseButton = document.querySelector("[data-release-permit-preview]");
let previewClient = null;
let previewSession = null;

function previewApplicationId() {
  const parts = window.location.pathname.split("/").filter(Boolean);
  return decodeURIComponent(parts[parts.length - 2] || "");
}

function setPermitMessage(message, isError = false) {
  if (!permitMessage) {
    return;
  }
  permitMessage.textContent = message || "";
  permitMessage.style.color = isError ? "#b42318" : "#516159";
}

function previewSupabaseClient() {
  if (!previewClient && window.supabase?.createClient) {
    previewClient = window.supabase.createClient(PREVIEW_SUPABASE_URL, PREVIEW_SUPABASE_KEY);
  }
  return previewClient;
}

async function session() {
  if (previewSession?.access_token) {
    return previewSession;
  }
  const api = previewSupabaseClient();
  if (!api) {
    throw new Error("Supabase is not available in this browser.");
  }
  const { data, error } = await api.auth.getSession();
  if (error) {
    throw error;
  }
  if (!data.session?.access_token) {
    throw new Error("Please log in as a BPLO staff administrator.");
  }
  previewSession = data.session;
  return previewSession;
}

async function apiFetch(path, options = {}) {
  const activeSession = await session();
  const response = await fetch(path, {
    ...options,
    headers: {
      "Authorization": `Bearer ${activeSession.access_token}`,
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload.error || "The request could not be completed.");
  }
  return payload;
}

function renderEligibility(eligibility) {
  const missing = eligibility?.missingRequirements || [];
  const warnings = eligibility?.warnings || [];
  if (!eligibilityList) {
    return;
  }
  if (!missing.length && !warnings.length) {
    eligibilityList.innerHTML = '<li class="is-ready"><i data-lucide="check" aria-hidden="true"></i>All release checks are satisfied.</li>';
    return;
  }
  eligibilityList.innerHTML = [...missing, ...warnings]
    .map((item) => `<li><i data-lucide="alert-circle" aria-hidden="true"></i>${String(item)}</li>`)
    .join("");
}

async function loadPermitPreview() {
  const applicationId = previewApplicationId();
  document.querySelector("[data-back-to-review]")?.setAttribute("href", `/admin/staff-administrator/applications/${encodeURIComponent(applicationId)}`);
  try {
    setPermitMessage("Loading official permit preview...");
    const payload = await apiFetch(`/admin/api/applications/${encodeURIComponent(applicationId)}/permit-preview`);
    if (!payload.permit || !payload.svg) {
      throw new Error("Generate the official business permit before opening the preview.");
    }
    permitPage.innerHTML = payload.svg;
    permitNumber.textContent = payload.permit.permit_number || "Official Business Permit";
    permitStatus.textContent = payload.permit.status || "Generated";
    releaseButton.hidden = payload.permit.status === "Released";
    renderEligibility(payload.eligibility || {});
    setPermitMessage("Permit preview loaded.");
    window.lucide?.createIcons();
    if (new URLSearchParams(window.location.search).get("print") === "1") {
      await recordPrintEvent();
      window.print();
    }
  } catch (error) {
    setPermitMessage(error.message || "Unable to load permit preview.", true);
    if (permitPage) {
      permitPage.innerHTML = '<div class="review-empty-box"><strong>Permit preview unavailable</strong><span>Return to the application review and complete the release requirements.</span></div>';
    }
  }
}

async function recordPrintEvent() {
  const applicationId = previewApplicationId();
  await apiFetch(`/admin/api/applications/${encodeURIComponent(applicationId)}/permit-print`, {
    method: "POST",
    body: "{}",
  });
}

document.querySelector("[data-print-permit-preview]")?.addEventListener("click", async () => {
  try {
    await recordPrintEvent();
  } catch (_error) {
    // Printing should still be available if audit logging is temporarily unavailable.
  }
  window.print();
});

document.querySelector("[data-download-permit-preview]")?.addEventListener("click", async () => {
  try {
    const activeSession = await session();
    const applicationId = previewApplicationId();
    const response = await fetch(`/admin/api/applications/${encodeURIComponent(applicationId)}/permit-pdf`, {
      headers: { "Authorization": `Bearer ${activeSession.access_token}` },
    });
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      throw new Error(payload.error || "Unable to download permit PDF.");
    }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `${permitNumber?.textContent || "business-permit"}.pdf`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  } catch (error) {
    setPermitMessage(error.message || "Unable to download permit PDF.", true);
  }
});

releaseButton?.addEventListener("click", async () => {
  if (!window.confirm("Release this official permit and notify the applicant for pickup?")) {
    return;
  }
  try {
    releaseButton.disabled = true;
    setPermitMessage("Releasing official permit...");
    const applicationId = previewApplicationId();
    const payload = await apiFetch(`/admin/api/applications/${encodeURIComponent(applicationId)}/release-permit`, {
      method: "POST",
      body: "{}",
    });
    setPermitMessage(payload.message || "Official permit released.");
    await loadPermitPreview();
  } catch (error) {
    releaseButton.disabled = false;
    setPermitMessage(error.message || "Unable to release permit.", true);
  }
});

window.addEventListener("DOMContentLoaded", () => {
  window.lucide?.createIcons();
  void loadPermitPreview();
});
