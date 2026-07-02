const SUPABASE_URL = window.APP_CONFIG?.supabaseUrl || "";
const SUPABASE_ANON_KEY =
  window.APP_CONFIG?.supabaseAnonKey || window.APP_CONFIG?.supabasePublishableKey || "";

const searchInput = document.querySelector("[data-classification-search]");
const parentFilter = document.querySelector("[data-classification-parent]");
const statusFilter = document.querySelector("[data-classification-status-filter]");
const summary = document.querySelector("[data-classification-summary]");
const footer = document.querySelector("[data-classification-footer]");
const pageIndicator = document.querySelector("[data-classification-page]");
const prevPageButton = document.querySelector("[data-classification-prev]");
const nextPageButton = document.querySelector("[data-classification-next]");
const tableBody = document.querySelector("[data-classifications-body]");
const dialog = document.querySelector("[data-classification-dialog]");
const form = document.querySelector("[data-classification-form]");
const formStatus = document.querySelector("[data-classification-form-status]");
const openDialogButton = document.querySelector("[data-open-classification-dialog]");
const closeDialogButtons = document.querySelectorAll("[data-close-classification-dialog]");
const dialogTitle = document.querySelector("[data-classification-dialog-title]");
const parentCategorySelect = document.querySelector("[data-parent-category-select]");

const PARENT_CATEGORIES = [
  "",
  "Retailer",
  "Manufacturer",
  "Service Provider",
  "Wholesaler",
  "Wholesaler (Distributor)",
  "Contractor",
  "Lessor",
  "Broker / Agent",
  "Cooperative",
  "Jobber",
  "Dropshipper",
  "Government",
];

let supabaseClient = null;
let classifications = [];
let editingId = "";
let searchTimer = null;
let currentPage = 1;
let totalPages = 1;
const PAGE_SIZE = 50;

function initSupabase() {
  if (!window.supabase?.createClient) {
    return null;
  }
  if (!supabaseClient) {
    supabaseClient = window.supabase.createClient(SUPABASE_URL, SUPABASE_ANON_KEY);
  }
  return supabaseClient;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function setStatus(node, message, isError = false) {
  if (!node) {
    return;
  }
  node.textContent = message || "";
  node.style.color = isError ? "#b42318" : "#078d36";
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
  if (!data.session?.access_token) {
    throw new Error("Please log in as a BPLO administrator.");
  }
  return data.session;
}

function populateCategorySelects() {
  const options = PARENT_CATEGORIES.map((category) => {
    const label = category || "All Categories";
    return `<option value="${escapeHtml(category)}">${escapeHtml(label)}</option>`;
  }).join("");
  if (parentFilter) {
    parentFilter.innerHTML = options;
  }
  if (parentCategorySelect) {
    parentCategorySelect.innerHTML = PARENT_CATEGORIES.map((category) => {
      const label = category || "Unassigned";
      return `<option value="${escapeHtml(category)}">${escapeHtml(label)}</option>`;
    }).join("");
  }
}

function renderClassifications(pagination = { page: 1, limit: 20, total: 0 }) {
  if (!tableBody) {
    return;
  }

  if (!classifications.length) {
    tableBody.innerHTML = '<tr><td colspan="5" class="staff-empty-cell">No matching business classifications found.</td></tr>';
  } else {
    tableBody.innerHTML = classifications
      .map((classification) => {
        const status = classification.isActive ? "Active" : "Inactive";
        const usedBy = Number(classification.usageCount || 0);
        return `
          <tr>
            <td>${escapeHtml(classification.name)}</td>
            <td>${escapeHtml(classification.parentCategory || "-")}</td>
            <td><span class="status-pill status-pill--${classification.isActive ? "active" : "inactive"}">${status}</span></td>
            <td>${usedBy} application${usedBy === 1 ? "" : "s"}</td>
            <td>
              <div class="table-action-row">
                <button class="table-action" type="button" data-edit-classification="${escapeHtml(classification.id)}">Edit</button>
                <button class="table-action" type="button" data-toggle-classification="${escapeHtml(classification.id)}">
                  ${classification.isActive ? "Deactivate" : "Activate"}
                </button>
              </div>
            </td>
          </tr>
        `;
      })
      .join("");
  }

  const start = pagination.total ? (pagination.page - 1) * pagination.limit + 1 : 0;
  const end = Math.min(pagination.total, (pagination.page - 1) * pagination.limit + classifications.length);
  totalPages = Math.max(1, Math.ceil((pagination.total || 0) / (pagination.limit || PAGE_SIZE)));
  currentPage = Math.min(Math.max(1, pagination.page || 1), totalPages);
  setStatus(summary, `${pagination.total} classification${pagination.total === 1 ? "" : "s"} found.`);
  if (footer) {
    footer.textContent = `Showing ${start} to ${end} of ${pagination.total} entries`;
  }
  if (pageIndicator) {
    pageIndicator.textContent = String(currentPage);
  }
  if (prevPageButton) {
    prevPageButton.disabled = currentPage <= 1;
  }
  if (nextPageButton) {
    nextPageButton.disabled = currentPage >= totalPages;
  }
}

async function loadClassifications() {
  try {
    setStatus(summary, "Loading business classifications...");
    const session = await getAdminSession();
    const params = new URLSearchParams({
      page: String(currentPage),
      limit: String(PAGE_SIZE),
      sort: "name.asc",
    });
    if (searchInput?.value.trim()) {
      params.set("search", searchInput.value.trim());
    }
    if (parentFilter?.value) {
      params.set("parentCategory", parentFilter.value);
    }
    if (statusFilter?.value) {
      params.set("status", statusFilter.value);
    }

    const response = await fetch(`/admin/api/business-classifications?${params.toString()}`, {
      headers: { "Authorization": `Bearer ${session.access_token}` },
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || "Unable to load business classifications.");
    }
    classifications = Array.isArray(payload.classifications) ? payload.classifications : [];
    renderClassifications(payload.pagination || {});
  } catch (error) {
    classifications = [];
    renderClassifications({ page: 1, limit: PAGE_SIZE, total: 0 });
    setStatus(summary, error.message || "Unable to load business classifications.", true);
  }
}

function openEditor(classification = null) {
  editingId = classification?.id || "";
  if (dialogTitle) {
    dialogTitle.textContent = editingId ? "Edit Business Classification" : "Add Business Classification";
  }
  form?.reset();
  if (classification && form) {
    form.elements.name.value = classification.name || "";
    form.elements.parentCategory.value = classification.parentCategory || "";
    form.elements.isActive.value = classification.isActive ? "true" : "false";
    form.elements.description.value = classification.description || "";
  }
  setStatus(formStatus, "");
  dialog?.showModal();
}

async function saveClassification(event) {
  event.preventDefault();
  try {
    const session = await getAdminSession();
    const formData = new FormData(form);
    const payload = {
      name: String(formData.get("name") || "").trim(),
      parentCategory: String(formData.get("parentCategory") || "").trim(),
      isActive: String(formData.get("isActive")) === "true",
      description: String(formData.get("description") || "").trim(),
    };
    if (!payload.name) {
      throw new Error("Business classification name is required.");
    }

    setStatus(formStatus, "Saving...");
    const endpoint = editingId
      ? `/admin/api/business-classifications/${encodeURIComponent(editingId)}`
      : "/admin/api/business-classifications";
    const response = await fetch(endpoint, {
      method: editingId ? "PATCH" : "POST",
      headers: {
        "Authorization": `Bearer ${session.access_token}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    });
    const result = await response.json();
    if (!response.ok) {
      throw new Error(result.error || "Unable to save business classification.");
    }
    dialog?.close();
    await loadClassifications();
  } catch (error) {
    setStatus(formStatus, error.message || "Unable to save business classification.", true);
  }
}

async function toggleClassification(classificationId) {
  const classification = classifications.find((item) => item.id === classificationId);
  if (!classification) {
    return;
  }
  const nextActive = !classification.isActive;
  try {
    const session = await getAdminSession();
    const response = await fetch(`/admin/api/business-classifications/${encodeURIComponent(classificationId)}`, {
      method: "PATCH",
      headers: {
        "Authorization": `Bearer ${session.access_token}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        name: classification.name,
        parentCategory: classification.parentCategory,
        description: classification.description,
        isActive: nextActive,
      }),
    });
    const result = await response.json();
    if (!response.ok) {
      throw new Error(result.error || "Unable to update business classification.");
    }
    await loadClassifications();
  } catch (error) {
    setStatus(summary, error.message || "Unable to update business classification.", true);
  }
}

openDialogButton?.addEventListener("click", () => openEditor());
closeDialogButtons.forEach((button) => button.addEventListener("click", () => dialog?.close()));
form?.addEventListener("submit", saveClassification);

searchInput?.addEventListener("input", () => {
  window.clearTimeout(searchTimer);
  searchTimer = window.setTimeout(() => {
    currentPage = 1;
    void loadClassifications();
  }, 300);
});
parentFilter?.addEventListener("change", () => {
  currentPage = 1;
  void loadClassifications();
});
statusFilter?.addEventListener("change", () => {
  currentPage = 1;
  void loadClassifications();
});
prevPageButton?.addEventListener("click", () => {
  if (currentPage <= 1) {
    return;
  }
  currentPage -= 1;
  void loadClassifications();
});
nextPageButton?.addEventListener("click", () => {
  if (currentPage >= totalPages) {
    return;
  }
  currentPage += 1;
  void loadClassifications();
});

tableBody?.addEventListener("click", (event) => {
  const target = event.target;
  if (!(target instanceof HTMLElement)) {
    return;
  }
  const editButton = target.closest("[data-edit-classification]");
  if (editButton instanceof HTMLElement) {
    const classification = classifications.find((item) => item.id === editButton.dataset.editClassification);
    openEditor(classification);
    return;
  }
  const toggleButton = target.closest("[data-toggle-classification]");
  if (toggleButton instanceof HTMLElement) {
    void toggleClassification(toggleButton.dataset.toggleClassification || "");
  }
});

window.addEventListener("DOMContentLoaded", () => {
  populateCategorySelects();
  void loadClassifications();
});
