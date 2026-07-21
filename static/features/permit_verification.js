const verifyMessage = document.querySelector("[data-verify-message]");
const verifyDetails = document.querySelector("[data-verify-details]");

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function tokenFromPath() {
  const parts = window.location.pathname.split("/").filter(Boolean);
  return decodeURIComponent(parts[parts.length - 1] || "");
}

async function loadVerification() {
  try {
    const response = await fetch(`/verify/api/permit/${encodeURIComponent(tokenFromPath())}`);
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(payload.error || "Permit verification failed.");
    }
    const permit = payload.permit || {};
    verifyMessage.textContent = payload.valid
      ? "This permit is valid and current."
      : "This permit record is not currently valid.";
    verifyMessage.className = payload.valid ? "is-valid" : "is-warning";
    verifyDetails.innerHTML = [
      ["Permit No.", permit.permitNumber],
      ["Business Name", permit.businessName],
      ["Owner", permit.ownerName],
      ["Status", permit.status],
      ["Released", permit.releaseDate],
      ["Valid Until", permit.expirationDate],
      ["Version", permit.version],
    ]
      .map(([label, value]) => `<div><dt>${escapeHtml(label)}</dt><dd>${escapeHtml(value || "-")}</dd></div>`)
      .join("");
  } catch (error) {
    verifyMessage.textContent = error.message || "Unable to verify permit.";
    verifyMessage.className = "is-warning";
    verifyDetails.innerHTML = "";
  }
  window.lucide?.createIcons();
}

window.addEventListener("DOMContentLoaded", loadVerification);
