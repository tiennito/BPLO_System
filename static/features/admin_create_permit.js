const permitForm = document.querySelector("[data-permit-form]");
const permitStatus = document.querySelector("[data-permit-status]");
const autoSaveState = document.querySelector("[data-autosave-state]");
const autoSaveTime = document.querySelector("[data-autosave-time]");
const retryAutoSaveButton = document.querySelector("[data-autosave-retry]");
const createNewPermitButton = document.querySelector("[data-create-new-permit]");
const archiveDraftButton = document.querySelector("[data-archive-draft]");
const documentDialog = document.querySelector("[data-document-dialog]");
const documentForm = document.querySelector("[data-document-form]");
const documentDialogTitle = document.querySelector("[data-document-dialog-title]");
const permitSuccessModal = document.querySelector("[data-permit-success-modal]");
const permitSuccessTitle = document.querySelector("[data-permit-success-title]");
const permitSuccessMessage = document.querySelector("[data-permit-success-message]");
const closePermitSuccessButton = document.querySelector("[data-close-permit-success]");
const requiredOfficesContainer = document.querySelector("[data-required-offices]");

const SUPABASE_URL = window.APP_CONFIG?.supabaseUrl || "";
const SUPABASE_ANON_KEY =
  window.APP_CONFIG?.supabaseAnonKey || window.APP_CONFIG?.supabasePublishableKey || "";
const AUTOSAVE_DELAY_MS = 750;
const BACKUP_KEY_PREFIX = "admin-permit-draft-backup:";

let supabaseClient = null;
let currentDraftId = "";
let currentPermitStatus = "Draft";
let documents = [];
let offices = [];
let selectedOfficeIds = new Set();
let autoSaveTimer = null;
let saveInFlight = false;
let pendingSave = false;
let hasUnsavedChanges = false;
let initializing = true;
let lastSavedAt = "";

function initSupabase() {
  if (!window.supabase?.createClient || !SUPABASE_URL || !SUPABASE_ANON_KEY) {
    return null;
  }

  if (!supabaseClient) {
    supabaseClient = window.supabase.createClient(SUPABASE_URL, SUPABASE_ANON_KEY);
  }

  return supabaseClient;
}

function setPermitStatus(message, isError = false) {
  if (!permitStatus) {
    return;
  }

  permitStatus.textContent = message;
  permitStatus.style.color = isError ? "#b42318" : "#078d36";
}

function setAutoSaveStatus(state, message, savedAt = "") {
  if (autoSaveState) {
    autoSaveState.textContent = message;
    autoSaveState.dataset.state = state;
  }
  if (autoSaveTime) {
    autoSaveTime.textContent = savedAt ? `Last saved at ${formatLocalTime(savedAt)}` : "";
  }
  if (retryAutoSaveButton) {
    retryAutoSaveButton.hidden = state !== "failed";
  }
}

function formatLocalTime(value) {
  if (!value) {
    return "";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "";
  }
  return date.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

function showPermitSuccessModal({ title, message }) {
  if (!permitSuccessModal) {
    return;
  }

  if (permitSuccessTitle) {
    permitSuccessTitle.textContent = title;
  }
  if (permitSuccessMessage) {
    permitSuccessMessage.textContent = message;
  }

  permitSuccessModal.hidden = false;
  document.body.classList.add("modal-open");
  window.lucide?.createIcons();
}

function hidePermitSuccessModal() {
  if (!permitSuccessModal) {
    return;
  }

  permitSuccessModal.hidden = true;
  document.body.classList.remove("modal-open");
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function normalizeDocumentFromApi(doc) {
  return {
    id: doc.id || crypto.randomUUID(),
    name: doc.documentName || doc.name || "",
    description: doc.shortDescription || doc.description || "",
    fileTypes: doc.acceptedFileTypes || doc.fileTypes || "",
    maxSize: doc.maxFileSize || doc.maxSize || "",
    uploadRequired: doc.uploadRequired ?? true,
  };
}

function renderDocuments() {
  const body = document.querySelector("[data-document-body]");
  const count = document.querySelector("[data-doc-count]");
  if (!body) {
    return;
  }

  if (count) {
    count.textContent = String(documents.length);
  }

  if (!documents.length) {
    body.innerHTML = `
      <tr>
        <td colspan="6" class="permit-empty-row">No document requirements yet.</td>
      </tr>
    `;
    return;
  }

  body.innerHTML = documents
    .map(
      (doc) => `
        <tr>
          <td>${escapeHtml(doc.name)}</td>
          <td>${escapeHtml(doc.description)}</td>
          <td>${escapeHtml(doc.fileTypes)}</td>
          <td>${escapeHtml(doc.maxSize)}</td>
          <td><span class="upload-pill ${doc.uploadRequired ? "is-yes" : "is-no"}">${doc.uploadRequired ? "Yes" : "No"}</span></td>
          <td>
            <button class="icon-table-button" type="button" data-edit-document="${escapeHtml(doc.id)}" aria-label="Edit document">
              <i data-lucide="pencil" aria-hidden="true"></i>
            </button>
            <button class="icon-table-button is-danger" type="button" data-delete-document="${escapeHtml(doc.id)}" aria-label="Delete document">
              <i data-lucide="trash-2" aria-hidden="true"></i>
            </button>
          </td>
        </tr>
      `
    )
    .join("");
  window.lucide?.createIcons();
}

function renderOffices() {
  if (!requiredOfficesContainer) {
    return;
  }

  if (!offices.length) {
    requiredOfficesContainer.innerHTML = '<p class="permit-empty-row">No offices found. Add offices in Departments first.</p>';
    return;
  }

  requiredOfficesContainer.innerHTML = offices
    .map(
      (office) => `
        <label class="required-office-option">
          <input type="checkbox" name="requiredOfficeIds" value="${escapeHtml(office.id)}" ${selectedOfficeIds.has(office.id) ? "checked" : ""} />
          <span>
            <strong>${escapeHtml(office.name)}</strong>
            <small>${escapeHtml(office.description || "Required processing office")}</small>
          </span>
        </label>
      `
    )
    .join("");
}

function setFormValues(permit) {
  if (!permitForm) {
    return;
  }

  permitForm.elements.permitName.value = permit.permitName || "";
  permitForm.elements.permitCode.value = permit.permitCode || "";
  permitForm.elements.category.value = permit.category || "Business Permits";
  permitForm.elements.description.value = permit.description || "";
  permitForm.elements.processingFee.value = permit.processingFee ?? "";
  permitForm.elements.applicantNotes.value = permit.applicantNotes || "";
  currentPermitStatus = permit.status || "Draft";
  documents = (permit.documents || []).map(normalizeDocumentFromApi);
  selectedOfficeIds = new Set((permit.requiredOffices || []).map((office) => office.id).filter(Boolean));
  lastSavedAt = permit.lastSavedAt || permit.updatedAt || "";
  renderDocuments();
  renderOffices();
  setAutoSaveStatus("saved", "Saved automatically", lastSavedAt);
}

function applyBackupIfPresent() {
  if (!currentDraftId) {
    return;
  }
  const rawBackup = window.localStorage.getItem(`${BACKUP_KEY_PREFIX}${currentDraftId}`);
  if (!rawBackup) {
    return;
  }
  try {
    const backup = JSON.parse(rawBackup);
    permitForm.elements.permitName.value = backup.permitName || "";
    permitForm.elements.permitCode.value = backup.permitCode || "";
    permitForm.elements.category.value = backup.category || "Business Permits";
    permitForm.elements.description.value = backup.description || "";
    permitForm.elements.processingFee.value = backup.processingFee || "";
    permitForm.elements.applicantNotes.value = backup.applicantNotes || "";
    selectedOfficeIds = new Set(backup.requiredOfficeIds || []);
    documents = (backup.documents || []).map((doc) => ({
      id: doc.id || crypto.randomUUID(),
      name: doc.name || doc.documentName || "",
      description: doc.description || doc.shortDescription || "",
      fileTypes: doc.fileTypes || doc.acceptedFileTypes || "",
      maxSize: doc.maxSize || doc.maxFileSize || "",
      uploadRequired: doc.uploadRequired ?? true,
    }));
    renderOffices();
    renderDocuments();
    hasUnsavedChanges = true;
    pendingSave = true;
    setAutoSaveStatus("dirty", "Unsaved changes", lastSavedAt);
    window.clearTimeout(autoSaveTimer);
    autoSaveTimer = window.setTimeout(() => {
      void autoSaveDraft();
    }, AUTOSAVE_DELAY_MS);
  } catch (_error) {
    clearBackup();
  }
}

function openDocumentDialog(doc = null) {
  if (!documentDialog || !documentForm) {
    return;
  }

  documentDialogTitle.textContent = doc ? "Edit Document" : "Add Document";
  documentForm.elements.id.value = doc?.id || "";
  documentForm.elements.name.value = doc?.name || "";
  documentForm.elements.description.value = doc?.description || "";
  documentForm.elements.fileTypes.value = doc?.fileTypes || "";
  documentForm.elements.maxSize.value = doc?.maxSize || "";
  documentForm.elements.uploadRequired.value = (doc?.uploadRequired ?? true) ? "yes" : "no";
  documentDialog.showModal();
  window.lucide?.createIcons();
}

async function getAccessToken() {
  const client = initSupabase();
  if (!client) {
    throw new Error("Supabase is not configured.");
  }

  const { data, error } = await client.auth.getSession();
  if (error || !data.session?.access_token) {
    throw new Error("Please sign in as admin before editing a permit.");
  }

  return data.session.access_token;
}

async function adminApi(path, options = {}) {
  const accessToken = await getAccessToken();
  const response = await fetch(path, {
    ...options,
    headers: {
      Authorization: `Bearer ${accessToken}`,
      ...(options.body ? { "Content-Type": "application/json" } : {}),
      ...(options.headers || {}),
    },
  });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.error || "The request failed.");
  }
  return payload;
}

function getDraftIdFromUrl() {
  return new URLSearchParams(window.location.search).get("draftId") || "";
}

function setDraftIdInUrl(draftId) {
  const url = new URL(window.location.href);
  url.searchParams.set("draftId", draftId);
  window.history.replaceState({}, "", url);
}

async function createBlankDraft() {
  const payload = await adminApi("/admin/api/permits", {
    method: "POST",
    body: JSON.stringify({ createBlank: true, status: "Draft" }),
  });
  currentDraftId = payload.permit?.id || "";
  if (!currentDraftId) {
    throw new Error("Unable to create a draft permit.");
  }
  setDraftIdInUrl(currentDraftId);
  setFormValues(payload.permit);
  setPermitStatus("New blank draft created.");
}

async function loadDraft(draftId) {
  const payload = await adminApi(`/admin/api/permits/${encodeURIComponent(draftId)}`);
  currentDraftId = payload.permit?.id || draftId;
  setDraftIdInUrl(currentDraftId);
  setFormValues(payload.permit);
  applyBackupIfPresent();
  if (currentPermitStatus !== "Draft") {
    setPermitStatus("This permit is already published or archived and cannot be edited here.", true);
    permitForm?.querySelectorAll("input, select, textarea, button").forEach((field) => {
      if (!field.matches("[data-create-new-permit]")) {
        field.disabled = true;
      }
    });
  }
}

async function loadOffices() {
  if (!requiredOfficesContainer) {
    return;
  }

  try {
    const payload = await adminApi("/admin/api/departments");
    offices = (payload.departments || []).filter((office) => office.status !== "Inactive");
    renderOffices();
  } catch (error) {
    requiredOfficesContainer.innerHTML = `<p class="permit-empty-row">${escapeHtml(error.message || "Unable to load offices.")}</p>`;
  }
}

function buildPermitPayload(status = "Draft") {
  if (!permitForm) {
    return null;
  }

  const formData = new FormData(permitForm);
  return {
    status,
    permitName: (formData.get("permitName") || "").toString().trim(),
    permitCode: (formData.get("permitCode") || "").toString().trim(),
    category: (formData.get("category") || "Business Permits").toString(),
    description: (formData.get("description") || "").toString().trim(),
    processingFee: (formData.get("processingFee") || "").toString().trim(),
    applicantNotes: (formData.get("applicantNotes") || "").toString().trim(),
    requiredOfficeIds: [...selectedOfficeIds],
    documents: documents.map((doc) => ({
      ...doc,
      documentName: doc.name,
      shortDescription: doc.description,
      acceptedFileTypes: doc.fileTypes,
      maxFileSize: doc.maxSize,
      requirementType: doc.uploadRequired ? "Required" : "Optional",
    })),
  };
}

function validateDocumentInput(doc, existingId = "") {
  if (!doc.name) {
    throw new Error("Document name is required.");
  }
  const duplicate = documents.some(
    (item) => item.id !== existingId && item.name.trim().toLowerCase() === doc.name.trim().toLowerCase()
  );
  if (duplicate) {
    throw new Error("A document requirement with this name already exists.");
  }
  const fileTypes = doc.fileTypes
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
  if (!fileTypes.length || fileTypes.some((item) => !/^[a-z0-9]+$/i.test(item.replace(/^\./, "")))) {
    throw new Error("Accepted file types must be comma-separated values like PDF, JPG, PNG.");
  }
  if (doc.maxSize && !/^\d+(?:\.\d+)?\s*(KB|MB|GB)$/i.test(doc.maxSize)) {
    throw new Error("Max file size must look like 5 MB, 500 KB, or 1 GB.");
  }
}

function saveBackup() {
  if (!currentDraftId) {
    return;
  }
  window.localStorage.setItem(`${BACKUP_KEY_PREFIX}${currentDraftId}`, JSON.stringify(buildPermitPayload("Draft")));
}

function clearBackup() {
  if (currentDraftId) {
    window.localStorage.removeItem(`${BACKUP_KEY_PREFIX}${currentDraftId}`);
  }
}

function markDirty() {
  if (initializing || currentPermitStatus !== "Draft") {
    return;
  }
  hasUnsavedChanges = true;
  pendingSave = true;
  saveBackup();
  setAutoSaveStatus("dirty", "Unsaved changes", lastSavedAt);
  window.clearTimeout(autoSaveTimer);
  autoSaveTimer = window.setTimeout(() => {
    void autoSaveDraft();
  }, AUTOSAVE_DELAY_MS);
}

async function autoSaveDraft() {
  if (!currentDraftId || currentPermitStatus !== "Draft") {
    return;
  }
  if (saveInFlight) {
    pendingSave = true;
    return;
  }

  saveInFlight = true;
  pendingSave = false;
  setAutoSaveStatus("saving", "Saving...", lastSavedAt);
  try {
    const payload = buildPermitPayload("Draft");
    const responsePayload = await adminApi(`/admin/api/permits/${encodeURIComponent(currentDraftId)}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    });
    lastSavedAt = responsePayload.permit?.lastSavedAt || responsePayload.permit?.updatedAt || new Date().toISOString();
    hasUnsavedChanges = false;
    clearBackup();
    setAutoSaveStatus("saved", "Saved automatically", lastSavedAt);
    setPermitStatus("");
  } catch (error) {
    hasUnsavedChanges = true;
    saveBackup();
    setAutoSaveStatus("failed", "Auto-save failed — Retry", lastSavedAt);
    setPermitStatus(error.message || "Auto-save failed. Your changes are still on this page.", true);
  } finally {
    saveInFlight = false;
    if (pendingSave) {
      window.clearTimeout(autoSaveTimer);
      autoSaveTimer = window.setTimeout(() => {
        void autoSaveDraft();
      }, AUTOSAVE_DELAY_MS);
    }
  }
}

async function publishPermit() {
  if (!currentDraftId) {
    return;
  }

  if (hasUnsavedChanges || pendingSave) {
    await autoSaveDraft();
    if (hasUnsavedChanges) {
      return;
    }
  }

  const submitButton = permitForm?.querySelector('button[type="submit"]');
  try {
    submitButton.disabled = true;
    const responsePayload = await adminApi(`/admin/api/permits/${encodeURIComponent(currentDraftId)}`, {
      method: "PATCH",
      body: JSON.stringify({ ...buildPermitPayload("Published"), publish: true }),
    });
    currentPermitStatus = "Published";
    hasUnsavedChanges = false;
    pendingSave = false;
    setAutoSaveStatus("saved", "Saved automatically", responsePayload.permit?.lastSavedAt || responsePayload.permit?.updatedAt || "");
    showPermitSuccessModal({
      title: "Permit Published Successfully",
      message: "The permit has been published and is ready for applicant use.",
    });
  } catch (error) {
    setAutoSaveStatus("failed", "Auto-save failed — Retry", lastSavedAt);
    setPermitStatus(error.message || "Unable to publish permit.", true);
  } finally {
    submitButton.disabled = false;
  }
}

async function archiveOrDeleteDraft() {
  if (!currentDraftId) {
    return;
  }
  const confirmed = window.confirm("Archive or remove this draft permit?");
  if (!confirmed) {
    return;
  }
  try {
    await adminApi(`/admin/api/permits/${encodeURIComponent(currentDraftId)}`, { method: "DELETE" });
    hasUnsavedChanges = false;
    pendingSave = false;
    clearBackup();
    await createBlankDraft();
    showPermitSuccessModal({
      title: "Draft Archived Successfully",
      message: "The draft permit has been archived or removed. A new blank draft is ready.",
    });
  } catch (error) {
    setPermitStatus(error.message || "Unable to archive this draft.", true);
  }
}

document.querySelectorAll("[data-add-document]").forEach((button) => {
  button.addEventListener("click", () => {
    openDocumentDialog();
  });
});

document.addEventListener("click", (event) => {
  const target = event.target;
  if (!(target instanceof HTMLElement)) {
    return;
  }

  const editButton = target.closest("[data-edit-document]");
  if (editButton instanceof HTMLElement) {
    const doc = documents.find((item) => item.id === editButton.dataset.editDocument);
    openDocumentDialog(doc);
    return;
  }

  const deleteButton = target.closest("[data-delete-document]");
  if (deleteButton instanceof HTMLElement) {
    documents = documents.filter((item) => item.id !== deleteButton.dataset.deleteDocument);
    renderDocuments();
    markDirty();
    setPermitStatus("Document requirement removed.");
  }
});

document.querySelectorAll("[data-close-document-dialog]").forEach((button) => {
  button.addEventListener("click", () => documentDialog?.close());
});

documentForm?.addEventListener("submit", (event) => {
  event.preventDefault();
  try {
    const formData = new FormData(documentForm);
    const id = (formData.get("id") || "").toString() || crypto.randomUUID();
    const doc = {
      id,
      name: (formData.get("name") || "").toString().trim(),
      description: (formData.get("description") || "").toString().trim(),
      fileTypes: (formData.get("fileTypes") || "").toString().trim(),
      maxSize: (formData.get("maxSize") || "").toString().trim(),
      uploadRequired: formData.get("uploadRequired") === "yes",
    };

    validateDocumentInput(doc, id);
    const existingIndex = documents.findIndex((item) => item.id === id);
    if (existingIndex >= 0) {
      documents[existingIndex] = doc;
    } else {
      documents.push(doc);
    }

    renderDocuments();
    documentDialog?.close();
    markDirty();
    setPermitStatus("Document requirement updated.");
  } catch (error) {
    setPermitStatus(error.message || "Unable to save document requirement.", true);
  }
});

permitForm?.addEventListener("input", (event) => {
  if (event.target instanceof HTMLElement && event.target.closest("[data-document-form]")) {
    return;
  }
  markDirty();
});

permitForm?.addEventListener("change", (event) => {
  const target = event.target;
  if (target instanceof HTMLInputElement && target.name === "requiredOfficeIds") {
    if (target.checked) {
      selectedOfficeIds.add(target.value);
    } else {
      selectedOfficeIds.delete(target.value);
    }
  }
  markDirty();
});

permitForm?.addEventListener("submit", (event) => {
  event.preventDefault();
  void publishPermit();
});

retryAutoSaveButton?.addEventListener("click", () => {
  pendingSave = true;
  void autoSaveDraft();
});

createNewPermitButton?.addEventListener("click", async () => {
  if (hasUnsavedChanges) {
    await autoSaveDraft();
    if (hasUnsavedChanges) {
      return;
    }
  }
  await createBlankDraft();
});

archiveDraftButton?.addEventListener("click", () => {
  void archiveOrDeleteDraft();
});

closePermitSuccessButton?.addEventListener("click", async () => {
  hidePermitSuccessModal();
  await createBlankDraft();
});

permitSuccessModal?.addEventListener("click", (event) => {
  const clickedBackdrop =
    event.target instanceof HTMLElement && event.target.classList.contains("success-modal__backdrop");
  if (event.target === permitSuccessModal || clickedBackdrop) {
    hidePermitSuccessModal();
  }
});

window.addEventListener("beforeunload", (event) => {
  if (hasUnsavedChanges || saveInFlight || pendingSave) {
    event.preventDefault();
    event.returnValue = "";
  }
});

window.addEventListener("DOMContentLoaded", async () => {
  try {
    setAutoSaveStatus("saving", "Loading draft...");
    await loadOffices();
    const draftId = getDraftIdFromUrl();
    if (draftId) {
      await loadDraft(draftId);
    } else {
      await createBlankDraft();
    }
  } catch (error) {
    setAutoSaveStatus("failed", "Auto-save failed — Retry");
    setPermitStatus(error.message || "Unable to prepare the permit draft.", true);
  } finally {
    initializing = false;
    window.lucide?.createIcons();
  }
});
