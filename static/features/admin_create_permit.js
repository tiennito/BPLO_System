const permitForm = document.querySelector("[data-permit-form]");
const permitStatus = document.querySelector("[data-permit-status]");
const documentDialog = document.querySelector("[data-document-dialog]");
const documentForm = document.querySelector("[data-document-form]");
const documentDialogTitle = document.querySelector("[data-document-dialog-title]");
const draftButton = document.querySelector("[data-save-draft]");

const PERMIT_STORAGE_KEY = "bplo_admin_permits";
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

function readSavedPermits() {
  try {
    const raw = window.localStorage.getItem(PERMIT_STORAGE_KEY);
    const parsed = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? parsed : [];
  } catch (_error) {
    return [];
  }
}

function savePermitRecord(status) {
  if (!permitForm) {
    return null;
  }

  const formData = new FormData(permitForm);
  const record = {
    id: crypto.randomUUID(),
    status,
    permitName: formData.get("permitName").toString().trim(),
    permitCode: formData.get("permitCode").toString().trim(),
    category: formData.get("category").toString(),
    isActive: Boolean(formData.get("status")),
    description: formData.get("description").toString().trim(),
    processingFee: formData.get("processingFee").toString().trim(),
    applicantNotes: formData.get("applicantNotes").toString().trim(),
    documents: {
      required: documents.required,
      optional: documents.optional,
    },
    savedAt: new Date().toISOString(),
  };

  const permits = readSavedPermits();
  permits.unshift(record);
  window.localStorage.setItem(PERMIT_STORAGE_KEY, JSON.stringify(permits.slice(0, 50)));
  return record;
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

draftButton?.addEventListener("click", () => {
  savePermitRecord("Draft");
  setPermitStatus("Permit saved as draft on this browser.");
});

permitForm?.addEventListener("submit", (event) => {
  event.preventDefault();
  if (!documents.required.length) {
    setPermitStatus("Add at least one required document before creating a permit.", true);
    return;
  }

  savePermitRecord("Created");
  setPermitStatus("Permit created on this browser.");
});

window.addEventListener("DOMContentLoaded", () => {
  renderAllDocuments();
  window.lucide?.createIcons();
});
