const permitForm = document.querySelector("[data-permit-form]");
const permitStatus = document.querySelector("[data-permit-status]");
const documentDialog = document.querySelector("[data-document-dialog]");
const documentForm = document.querySelector("[data-document-form]");
const documentDialogTitle = document.querySelector("[data-document-dialog-title]");
const draftButton = document.querySelector("[data-save-draft]");
const requiredOfficesContainer = document.querySelector("[data-required-offices]");

const SUPABASE_URL = window.APP_CONFIG?.supabaseUrl || "";
const SUPABASE_ANON_KEY =
  window.APP_CONFIG?.supabaseAnonKey || window.APP_CONFIG?.supabasePublishableKey || "";
let supabaseClient = null;
let existingPermits = [];
const documents = {
  required: [
    {
      id: crypto.randomUUID(),
      name: "DTI/SEC Registration",
      description: "Business registration certificate",
      fileTypes: "PDF",
      maxSize: "10 MB",
      uploadRequired: true,
    },
    {
      id: crypto.randomUUID(),
      name: "Barangay Clearance",
      description: "Clearance from barangay",
      fileTypes: "PDF",
      maxSize: "5 MB",
      uploadRequired: true,
    },
    {
      id: crypto.randomUUID(),
      name: "Valid ID",
      description: "Government-issued ID",
      fileTypes: "PDF, JPG, PNG",
      maxSize: "5 MB",
      uploadRequired: true,
    },
    {
      id: crypto.randomUUID(),
      name: "Lease Contract",
      description: "Proof of business address",
      fileTypes: "PDF",
      maxSize: "10 MB",
      uploadRequired: true,
    },
  ],
  optional: [
    {
      id: crypto.randomUUID(),
      name: "Authorization Letter",
      description: "Authorization from owner if applicable",
      fileTypes: "PDF",
      maxSize: "5 MB",
      uploadRequired: false,
    },
    {
      id: crypto.randomUUID(),
      name: "Previous Permit",
      description: "Copy of previous business permit",
      fileTypes: "PDF",
      maxSize: "10 MB",
      uploadRequired: false,
    },
    {
      id: crypto.randomUUID(),
      name: "Supporting Document",
      description: "Other supporting documents",
      fileTypes: "PDF, JPG, PNG",
      maxSize: "10 MB",
      uploadRequired: false,
    },
  ],
};
let offices = [];

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

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function renderDocuments(group) {
  const body = document.querySelector(`[data-document-body="${group}"]`);
  const count = document.querySelector(`[data-doc-count="${group}"]`);
  if (!body) {
    return;
  }

  const rows = documents[group] || [];
  if (count) {
    count.textContent = String(rows.length);
  }

  if (!rows.length) {
    body.innerHTML = `
      <tr>
        <td colspan="6" class="permit-empty-row">No ${escapeHtml(group)} documents yet.</td>
      </tr>
    `;
    return;
  }

  body.innerHTML = rows
    .map(
      (doc) => `
        <tr>
          <td>${escapeHtml(doc.name)}</td>
          <td>${escapeHtml(doc.description)}</td>
          <td>${escapeHtml(doc.fileTypes)}</td>
          <td>${escapeHtml(doc.maxSize)}</td>
          <td><span class="upload-pill ${doc.uploadRequired ? "is-yes" : "is-no"}">${doc.uploadRequired ? "Yes" : "No"}</span></td>
          <td>
            <button class="icon-table-button" type="button" data-edit-document="${escapeHtml(doc.id)}" data-group="${escapeHtml(group)}" aria-label="Edit document">
              <i data-lucide="pencil" aria-hidden="true"></i>
            </button>
            <button class="icon-table-button is-danger" type="button" data-delete-document="${escapeHtml(doc.id)}" data-group="${escapeHtml(group)}" aria-label="Delete document">
              <i data-lucide="trash-2" aria-hidden="true"></i>
            </button>
          </td>
        </tr>
      `
    )
    .join("");
  window.lucide?.createIcons();
}

function renderAllDocuments() {
  renderDocuments("required");
  renderDocuments("optional");
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
          <input type="checkbox" name="requiredOfficeIds" value="${escapeHtml(office.id)}" />
          <span>
            <strong>${escapeHtml(office.name)}</strong>
            <small>${escapeHtml(office.description || "Required processing office")}</small>
          </span>
        </label>
      `
    )
    .join("");
}

function openDocumentDialog(group, doc = null) {
  if (!documentDialog || !documentForm) {
    return;
  }

  documentDialogTitle.textContent = doc ? "Edit Document" : "Add Document";
  documentForm.elements.id.value = doc?.id || "";
  documentForm.elements.group.value = group;
  documentForm.elements.name.value = doc?.name || "";
  documentForm.elements.description.value = doc?.description || "";
  documentForm.elements.fileTypes.value = doc?.fileTypes || "";
  documentForm.elements.maxSize.value = doc?.maxSize || "";
  documentForm.elements.uploadRequired.checked = doc?.uploadRequired ?? group === "required";
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
    throw new Error("Please sign in as admin before saving a permit.");
  }

  return data.session.access_token;
}

async function loadOffices() {
  if (!requiredOfficesContainer) {
    return;
  }

  try {
    const accessToken = await getAccessToken();
    const response = await fetch("/admin/api/departments", {
      headers: { Authorization: `Bearer ${accessToken}` },
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || "Unable to load offices.");
    }
    offices = (payload.departments || []).filter((office) => office.status !== "Inactive");
    renderOffices();
  } catch (error) {
    requiredOfficesContainer.innerHTML = `<p class="permit-empty-row">${escapeHtml(error.message || "Unable to load offices.")}</p>`;
  }
}

function getPermitCodeInput() {
  return permitForm?.querySelector('input[name="permitCode"]') || null;
}

function getNextPermitCode() {
  const usedNumbers = existingPermits
    .map((permit) => permit.permitCode || "")
    .map((code) => /^BP-(\d+)$/i.exec(code.trim()))
    .filter(Boolean)
    .map((match) => Number(match[1]))
    .filter((value) => Number.isFinite(value));
  const nextNumber = usedNumbers.length ? Math.max(...usedNumbers) + 1 : 1;
  return `BP-${String(nextNumber).padStart(3, "0")}`;
}

async function loadExistingPermits() {
  try {
    const accessToken = await getAccessToken();
    const response = await fetch("/admin/api/permits", {
      headers: { Authorization: `Bearer ${accessToken}` },
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || "Unable to load permits.");
    }

    existingPermits = payload.permits || [];
    const codeInput = getPermitCodeInput();
    if (codeInput && (!codeInput.value.trim() || codeInput.value.trim() === "BP-001")) {
      const nextCode = getNextPermitCode();
      codeInput.value = nextCode;
      if (nextCode !== "BP-001") {
        setPermitStatus(`Permit code ${nextCode} is ready for the next permit.`);
      }
    }
  } catch (_error) {
    existingPermits = [];
  }
}

async function ensureUniquePermitCodeBeforeCreate(payload) {
  await loadExistingPermits();
  const currentCode = payload.permitCode.trim().toLowerCase();
  const isDuplicate = existingPermits.some(
    (permit) => (permit.permitCode || "").trim().toLowerCase() === currentCode
  );

  if (!isDuplicate) {
    return payload;
  }

  const nextCode = getNextPermitCode();
  const codeInput = getPermitCodeInput();
  if (codeInput) {
    codeInput.value = nextCode;
  }

  return { ...payload, permitCode: nextCode };
}

function buildPermitPayload(status) {
  if (!permitForm) {
    return null;
  }

  const formData = new FormData(permitForm);
  const selectedOfficeIds = [...permitForm.querySelectorAll('input[name="requiredOfficeIds"]:checked')].map(
    (input) => input.value
  );

  return {
    status,
    permitName: formData.get("permitName").toString().trim(),
    permitCode: formData.get("permitCode").toString().trim(),
    category: formData.get("category").toString(),
    description: formData.get("description").toString().trim(),
    processingFee: formData.get("processingFee").toString().trim(),
    applicantNotes: formData.get("applicantNotes").toString().trim(),
    requiredOfficeIds: selectedOfficeIds,
    documents: [
      ...documents.required.map((doc) => ({ ...doc, requirementType: "Required" })),
      ...documents.optional.map((doc) => ({ ...doc, requirementType: "Optional" })),
    ],
  };
}

async function savePermitRecord(status) {
  let payload = buildPermitPayload(status);
  if (!payload) {
    return null;
  }

  payload = await ensureUniquePermitCodeBeforeCreate(payload);
  const accessToken = await getAccessToken();
  const response = await fetch("/admin/api/permits", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${accessToken}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });
  const responsePayload = await response.json();
  if (!response.ok) {
    throw new Error(responsePayload.error || "Unable to save permit.");
  }
  return responsePayload.permit;
}

document.querySelectorAll("[data-add-document]").forEach((button) => {
  button.addEventListener("click", () => {
    openDocumentDialog(button.getAttribute("data-add-document") || "required");
  });
});

document.addEventListener("click", (event) => {
  const target = event.target;
  if (!(target instanceof HTMLElement)) {
    return;
  }

  const editButton = target.closest("[data-edit-document]");
  if (editButton instanceof HTMLElement) {
    const group = editButton.dataset.group || "required";
    const doc = documents[group].find((item) => item.id === editButton.dataset.editDocument);
    openDocumentDialog(group, doc);
    return;
  }

  const deleteButton = target.closest("[data-delete-document]");
  if (deleteButton instanceof HTMLElement) {
    const group = deleteButton.dataset.group || "required";
    documents[group] = documents[group].filter((item) => item.id !== deleteButton.dataset.deleteDocument);
    renderDocuments(group);
    setPermitStatus("Document removed.");
  }
});

document.querySelectorAll("[data-close-document-dialog]").forEach((button) => {
  button.addEventListener("click", () => documentDialog?.close());
});

documentForm?.addEventListener("submit", (event) => {
  event.preventDefault();
  const formData = new FormData(documentForm);
  const group = formData.get("group").toString() || "required";
  const id = formData.get("id").toString() || crypto.randomUUID();
  const doc = {
    id,
    name: formData.get("name").toString().trim(),
    description: formData.get("description").toString().trim(),
    fileTypes: formData.get("fileTypes").toString().trim(),
    maxSize: formData.get("maxSize").toString().trim(),
    uploadRequired: Boolean(formData.get("uploadRequired")),
  };

  const existingIndex = documents[group].findIndex((item) => item.id === id);
  if (existingIndex >= 0) {
    documents[group][existingIndex] = doc;
  } else {
    documents[group].push(doc);
  }

  renderDocuments(group);
  documentDialog?.close();
  setPermitStatus("Document requirement saved.");
});

draftButton?.addEventListener("click", async () => {
  try {
    draftButton.disabled = true;
    const permit = await savePermitRecord("Draft");
    setPermitStatus(`Permit saved as draft${permit?.permitCode ? ` with code ${permit.permitCode}` : ""}.`);
  } catch (error) {
    setPermitStatus(error.message || "Unable to save permit draft.", true);
  } finally {
    draftButton.disabled = false;
  }
});

permitForm?.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!documents.required.length) {
    setPermitStatus("Add at least one required document before creating a permit.", true);
    return;
  }

  const submitButton = permitForm.querySelector('button[type="submit"]');
  try {
    submitButton.disabled = true;
    const formData = new FormData(permitForm);
    const status = formData.get("status") ? "Active" : "Inactive";
    const permit = await savePermitRecord(status);
    setPermitStatus(`Permit created successfully${permit?.permitCode ? ` with code ${permit.permitCode}` : ""}.`);
  } catch (error) {
    setPermitStatus(error.message || "Unable to create permit.", true);
  } finally {
    submitButton.disabled = false;
  }
});

window.addEventListener("DOMContentLoaded", () => {
  renderAllDocuments();
  void loadOffices();
  void loadExistingPermits();
  window.lucide?.createIcons();
});
