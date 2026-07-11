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
const permitSummaryCard = document.querySelector(".permit-summary-card");
const permitTypeBadge = document.querySelector(".permit-summary-card header span");
const permitStartButton = document.querySelector(".start-application-button");
const businessFormShell = document.querySelector("[data-business-form-shell]");
const businessStepPanels = {
  form: document.querySelector('[data-business-step-panel="form"]'),
};
const businessContinueButton = document.querySelector("[data-business-continue]");
const finishApplicationButton = document.querySelector("[data-finish-application]");
const reviewStrip = document.querySelector("[data-review-strip]");
const profilePrefillStatus = document.querySelector("[data-profile-prefill-status]");
const recentPermitsTableBody = document.querySelector(".permits-table-wrap tbody");
const activePermitsGrid = document.querySelector("[data-active-permits]");
const dynamicDocumentGrid = document.querySelector("[data-dynamic-document-grid]");
const checklistPermitName = document.querySelector("[data-checklist-permit-name]");
const checklistPermitCode = document.querySelector("[data-checklist-permit-code]");
const requirementsNextButton = document.querySelector("[data-requirements-next]");
const requirementsStatus = document.querySelector("[data-requirements-status]");
const notificationMenu = document.querySelector("[data-notification-menu]");
const notificationToggle = document.querySelector("[data-notification-toggle]");
const notificationDropdown = document.querySelector("[data-notification-dropdown]");
const notificationList = document.querySelector("[data-notification-list]");
const notificationCount = document.querySelector("[data-notification-count]");
const markAllNotificationsReadButton = document.querySelector("[data-mark-all-notifications-read]");
const businessClassificationCombobox = document.querySelector("[data-business-classification-combobox]");
const businessClassificationSearch = document.querySelector("[data-business-classification-search]");
const businessClassificationResults = document.querySelector("[data-business-classification-results]");
const businessClassificationStatus = document.querySelector("[data-business-classification-status]");
const draftPanel = document.querySelector("[data-draft-panel]");
const draftList = document.querySelector("[data-draft-list]");
const progressPanel = document.querySelector("[data-progress-panel]");
const progressList = document.querySelector("[data-progress-list]");
const departmentProgressList = document.querySelector("[data-department-progress-list]");
const progressSummary = document.querySelector("[data-progress-summary]");
const autosaveStatus = document.querySelector("[data-autosave-status]");

const PERMIT_STORAGE_KEY = "bplo_recent_business_permits";
const SELECTED_PERMIT_KEY = "bplo_selected_permit_id";
const CURRENT_APPLICATION_KEY = "bplo_current_application_id";
const OCR_FIELDS_KEY = "bplo_current_ocr_fields";
const OCR_SKIP_KEY = "bplo_skip_ocr_fields";
const DRAFT_BACKUP_PREFIX = "bplo_draft_backup_";
const AUTOSAVE_DEBOUNCE_MS = 1500;
const OCR_FORM_FIELD_MAP = {
  business_name: '[name="business_name"]',
  trade_name: '[name="trade_name"]',
  tin: '[name="tin"]',
  business_address: '[name="business_address"]',
};
const OCR_METADATA_KEYS = new Set(["field_confidence", "fieldConfidence", "confidence", "confidence_score", "parser_version"]);
const BUSINESS_REQUIRED_FIELDS = [
  ["applicationDate", "Date of Application"],
  ["registrationNumber", "DTI/SEC/CDA Registration No."],
  ["modeOfPayment", "Mode of Payment"],
  ["lastName", "Last Name"],
  ["firstName", "First Name"],
  ["middleName", "Middle Name"],
  ["email", "Registered Email Address"],
  ["contactNumber", "Registered Contact Number"],
  ["homeAddress", "Home Address"],
  ["businessName", "Business Name"],
  ["businessTypes", "Type of Business"],
  ["businessClassification", "Business Classification"],
  ["businessAddress", "Business Address"],
  ["businessBarangay", "Business Barangay"],
  ["businessPremise", "Business Premise"],
  ["businessMobile", "Business Mobile Number"],
  ["businessEmail", "Business Email"],
  ["ownerContactNumber", "Owner/Proprietor Contact Number"],
];

let supabaseClient = null;
let currentUser = null;
let currentAccessProfile = null;
let currentApplicantProfile = null;
let applicantProfileLoadError = "";
let activePermitCache = [];
let checklistDocuments = [];
let uploadedDocumentNames = new Map();
let uploadedDocumentOcrStatus = new Map();
let uploadedDocumentPreviewUrls = new Map();
let applicantNotifications = [];
let autosaveTimer = null;
let isRestoringDraft = false;
let isApplyingBusinessDefaults = false;
const editedBusinessFields = new Set();
const businessClassificationState = {
  activeIndex: -1,
  options: [],
  selected: null,
  searchTimer: null,
};

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

function ensureApplicationSuccessModal() {
  let modal = document.querySelector("[data-application-success-modal]");
  if (modal) {
    return modal;
  }

  modal = document.createElement("section");
  modal.className = "application-success-modal";
  modal.dataset.applicationSuccessModal = "";
  modal.hidden = true;
  modal.innerHTML = `
    <div class="application-success-modal__backdrop" data-application-success-close></div>
    <article class="application-success-modal__card" role="dialog" aria-modal="true" aria-labelledby="application-success-title" aria-describedby="application-success-message">
      <div class="application-success-modal__badge" aria-hidden="true">
        <i data-lucide="check" aria-hidden="true"></i>
      </div>
      <h2 id="application-success-title">Application Submitted</h2>
      <p id="application-success-message" data-application-success-message>Your application has been submitted successfully.</p>
      <button class="application-success-modal__action" type="button" data-application-success-close>
        <span>OK</span>
        <i data-lucide="arrow-right" aria-hidden="true"></i>
      </button>
    </article>
  `;
  document.body.appendChild(modal);
  window.lucide?.createIcons();
  return modal;
}

function showApplicationSuccessModal(message = "Application submitted successfully.") {
  const modal = ensureApplicationSuccessModal();
  const messageNode = modal.querySelector("[data-application-success-message]");
  const closeButton = modal.querySelector(".application-success-modal__action");

  if (messageNode) {
    messageNode.textContent = message;
  }

  modal.hidden = false;
  document.body.classList.add("application-success-modal-open");
  closeButton?.focus();

  return new Promise((resolve) => {
    let resolved = false;

    const close = () => {
      if (resolved) {
        return;
      }
      resolved = true;
      modal.hidden = true;
      document.body.classList.remove("application-success-modal-open");
      modal.removeEventListener("click", handleClick);
      document.removeEventListener("keydown", handleKeydown);
      resolve();
    };

    const handleClick = (event) => {
      if (event.target instanceof HTMLElement && event.target.closest("[data-application-success-close]")) {
        close();
      }
    };

    const handleKeydown = (event) => {
      if (event.key === "Escape" || event.key === "Enter") {
        event.preventDefault();
        close();
      }
    };

    modal.addEventListener("click", handleClick);
    document.addEventListener("keydown", handleKeydown);
  });
}

async function getApplicantAccessToken() {
  const client = initSupabase();
  if (!client) {
    throw new Error("Supabase is not configured.");
  }

  const { data, error } = await client.auth.getSession();
  if (error || !data.session?.access_token) {
    throw new Error("Please sign in before continuing.");
  }

  return data.session.access_token;
}

async function applicantApi(path, options = {}) {
  const accessToken = await getApplicantAccessToken();
  const response = await fetch(path, {
    ...options,
    headers: {
      Authorization: `Bearer ${accessToken}`,
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
  });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.error || "Unable to complete request.");
  }
  return payload;
}

function setBusinessClassificationStatus(message, isError = false) {
  if (!businessClassificationStatus) {
    return;
  }
  businessClassificationStatus.textContent = message || "";
  businessClassificationStatus.classList.toggle("is-error", Boolean(isError));
}

function setBusinessClassificationExpanded(expanded) {
  if (businessClassificationSearch) {
    businessClassificationSearch.setAttribute("aria-expanded", expanded ? "true" : "false");
  }
  if (businessClassificationResults) {
    businessClassificationResults.hidden = !expanded;
  }
}

function highlightMatch(value, query) {
  const text = String(value || "");
  const search = String(query || "").trim();
  if (!search) {
    return escapeHtml(text);
  }
  const index = text.toLowerCase().indexOf(search.toLowerCase());
  if (index < 0) {
    return escapeHtml(text);
  }
  return `${escapeHtml(text.slice(0, index))}<mark>${escapeHtml(text.slice(index, index + search.length))}</mark>${escapeHtml(text.slice(index + search.length))}`;
}

function syncBusinessClassificationHiddenFields(classification) {
  const idInput = businessFormShell?.querySelector('[data-business-field="business_classification_id"]');
  const nameInput = businessFormShell?.querySelector('[data-business-field="business_classification"]');
  if (idInput instanceof HTMLInputElement) {
    idInput.value = classification?.id || "";
  }
  if (nameInput instanceof HTMLInputElement) {
    nameInput.value = classification?.name || "";
  }
}

function renderBusinessClassificationOptions(query = "") {
  if (!businessClassificationResults) {
    return;
  }

  if (!businessClassificationState.options.length) {
    businessClassificationResults.innerHTML =
      '<div class="business-classification-empty">No matching business classification found.</div>';
    setBusinessClassificationExpanded(true);
    return;
  }

  businessClassificationResults.innerHTML = businessClassificationState.options
    .map((classification, index) => {
      const activeClass = index === businessClassificationState.activeIndex ? " is-active" : "";
      const category = classification.parentCategory ? `<small>${escapeHtml(classification.parentCategory)}</small>` : "";
      return `
        <button class="business-classification-option${activeClass}" type="button" role="option" data-classification-index="${index}">
          ${highlightMatch(classification.name, query)}
          ${category}
        </button>
      `;
    })
    .join("");
  setBusinessClassificationExpanded(true);
}

async function loadBusinessClassifications(query = "") {
  if (!businessClassificationResults) {
    return;
  }

  setBusinessClassificationStatus("Loading classifications...");
  businessClassificationResults.innerHTML = '<div class="business-classification-empty">Loading...</div>';
  setBusinessClassificationExpanded(true);

  try {
    const params = new URLSearchParams({
      limit: "20",
      sort: "name.asc",
    });
    if (query.trim()) {
      params.set("search", query.trim());
    }
    const payload = await applicantApi(`/api/business-classifications?${params.toString()}`);
    businessClassificationState.options = Array.isArray(payload.data) ? payload.data : [];
    businessClassificationState.activeIndex = businessClassificationState.options.length ? 0 : -1;
    renderBusinessClassificationOptions(query);
    setBusinessClassificationStatus(
      businessClassificationState.options.length
        ? `${businessClassificationState.options.length} result${businessClassificationState.options.length === 1 ? "" : "s"} shown.`
        : ""
    );
  } catch (error) {
    businessClassificationState.options = [];
    businessClassificationState.activeIndex = -1;
    businessClassificationResults.innerHTML =
      '<div class="business-classification-empty">Unable to load business classifications.</div>';
    setBusinessClassificationExpanded(true);
    setBusinessClassificationStatus(error.message || "Unable to load business classifications.", true);
  }
}

function selectBusinessClassification(classification) {
  if (!classification) {
    return;
  }
  businessClassificationState.selected = classification;
  if (businessClassificationSearch) {
    businessClassificationSearch.value = classification.name || "";
  }
  syncBusinessClassificationHiddenFields(classification);
  setBusinessClassificationExpanded(false);
  setBusinessClassificationStatus("");
  if (businessClassificationSearch instanceof HTMLElement) {
    markBusinessFieldTouched(businessClassificationSearch);
  }
}

function queueBusinessClassificationSearch() {
  window.clearTimeout(businessClassificationState.searchTimer);
  businessClassificationState.searchTimer = window.setTimeout(() => {
    void loadBusinessClassifications(businessClassificationSearch?.value || "");
  }, 300);
}

function handleBusinessClassificationKeydown(event) {
  if (!businessClassificationResults || businessClassificationResults.hidden) {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      void loadBusinessClassifications(businessClassificationSearch?.value || "");
    }
    return;
  }

  if (event.key === "ArrowDown") {
    event.preventDefault();
    businessClassificationState.activeIndex = Math.min(
      businessClassificationState.options.length - 1,
      businessClassificationState.activeIndex + 1
    );
    renderBusinessClassificationOptions(businessClassificationSearch?.value || "");
  } else if (event.key === "ArrowUp") {
    event.preventDefault();
    businessClassificationState.activeIndex = Math.max(0, businessClassificationState.activeIndex - 1);
    renderBusinessClassificationOptions(businessClassificationSearch?.value || "");
  } else if (event.key === "Enter") {
    event.preventDefault();
    selectBusinessClassification(businessClassificationState.options[businessClassificationState.activeIndex]);
  } else if (event.key === "Escape") {
    setBusinessClassificationExpanded(false);
  }
}

function initializeBusinessClassificationCombobox() {
  if (!businessClassificationCombobox || !businessClassificationSearch || !businessClassificationResults) {
    return;
  }

  businessClassificationSearch.addEventListener("focus", () => {
    void loadBusinessClassifications(businessClassificationSearch.value || "");
  });

  businessClassificationSearch.addEventListener("input", () => {
    businessClassificationState.selected = null;
    syncBusinessClassificationHiddenFields(null);
    queueBusinessClassificationSearch();
  });

  businessClassificationSearch.addEventListener("keydown", handleBusinessClassificationKeydown);

  businessClassificationResults.addEventListener("click", (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) {
      return;
    }
    const option = target.closest("[data-classification-index]");
    if (!(option instanceof HTMLElement)) {
      return;
    }
    const index = Number(option.getAttribute("data-classification-index"));
    selectBusinessClassification(businessClassificationState.options[index]);
  });

  document.addEventListener("click", (event) => {
    const target = event.target;
    if (target instanceof Node && !businessClassificationCombobox.contains(target)) {
      setBusinessClassificationExpanded(false);
    }
  });
}

function formatNotificationTime(value) {
  if (!value) {
    return "";
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "";
  }

  return new Intl.DateTimeFormat("en-US", {
    month: "long",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(date);
}

function updateNotificationBadge(unreadCount = 0) {
  if (!notificationCount) {
    return;
  }

  notificationCount.hidden = unreadCount <= 0;
  notificationCount.textContent = unreadCount > 99 ? "99+" : String(unreadCount);
}

function renderNotifications(notifications = applicantNotifications) {
  if (!notificationList) {
    return;
  }

  if (!notifications.length) {
    notificationList.innerHTML = '<p class="notification-empty">No notifications yet.</p>';
    updateNotificationBadge(0);
    return;
  }

  notificationList.innerHTML = notifications
    .map((notification) => {
      const stateClass = notification.isRead ? "is-read" : "is-unread";
      return `
        <button class="notification-item ${stateClass}" type="button" data-notification-id="${escapeHtml(notification.id)}">
          <span class="notification-item-title">
            <span>${escapeHtml(notification.title)}</span>
            <span class="notification-dot" aria-hidden="true"></span>
          </span>
          <p>${escapeHtml(notification.message)}</p>
          <span class="notification-time">${escapeHtml(formatNotificationTime(notification.createdAt))}</span>
        </button>
      `;
    })
    .join("");

  updateNotificationBadge(notifications.filter((notification) => !notification.isRead).length);
}

async function loadApplicantNotifications() {
  if (!notificationMenu) {
    return;
  }

  try {
    const payload = await applicantApi("/applicant/api/notifications");
    applicantNotifications = payload.notifications || [];
    renderNotifications(applicantNotifications);
    updateNotificationBadge(payload.unreadCount || 0);
  } catch {
    renderNotifications([]);
  }
}

async function markNotificationRead(notificationId) {
  if (!notificationId) {
    return;
  }

  const notification = applicantNotifications.find((item) => item.id === notificationId);
  if (notification?.isRead) {
    return;
  }

  applicantNotifications = applicantNotifications.map((item) =>
    item.id === notificationId ? { ...item, isRead: true, readAt: new Date().toISOString() } : item
  );
  renderNotifications(applicantNotifications);

  try {
    await applicantApi(`/applicant/api/notifications/${encodeURIComponent(notificationId)}/read`, {
      method: "PATCH",
      body: JSON.stringify({}),
    });
    await loadApplicantNotifications();
  } catch {
    // Keep the local read state; the next refresh will reconcile with the server.
  }
}

async function markAllNotificationsRead() {
  if (!applicantNotifications.length) {
    return;
  }

  applicantNotifications = applicantNotifications.map((notification) => ({
    ...notification,
    isRead: true,
    readAt: notification.readAt || new Date().toISOString(),
  }));
  renderNotifications(applicantNotifications);

  try {
    await applicantApi("/applicant/api/notifications/mark-all-read", {
      method: "PATCH",
      body: JSON.stringify({}),
    });
    await loadApplicantNotifications();
  } catch {
    // Keep the local read state; the next refresh will reconcile with the server.
  }
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

function firstPresentValue(...values) {
  for (const value of values) {
    if (value !== undefined && value !== null && String(value).trim() !== "") {
      return String(value).trim();
    }
  }

  return "";
}

function normalizeGender(value) {
  const normalized = String(value || "").trim().toUpperCase();
  if (["M", "MALE"].includes(normalized)) {
    return "MALE";
  }
  if (["F", "FEMALE"].includes(normalized)) {
    return "FEMALE";
  }
  if (["OTHER", "OTHERS", "NON-BINARY", "NONBINARY"].includes(normalized)) {
    return "OTHER";
  }
  return normalized;
}

function getTodayDateInputValue() {
  const today = new Date();
  const timezoneOffsetMs = today.getTimezoneOffset() * 60000;
  return new Date(today.getTime() - timezoneOffsetMs).toISOString().slice(0, 10);
}

function applyTodayApplicationDate() {
  setBusinessFieldValue("application_date", getTodayDateInputValue(), { className: "is-profile-filled" });
}

function setProfilePrefillStatus(message, state = "") {
  if (!profilePrefillStatus) {
    return;
  }

  profilePrefillStatus.textContent = message;
  profilePrefillStatus.classList.toggle("is-ready", state === "ready");
  profilePrefillStatus.classList.toggle("is-warning", state === "warning");
  profilePrefillStatus.classList.toggle("is-error", state === "error");
}

function collectProfileBusinessDefaults(applicantProfile = currentApplicantProfile, accessProfile = currentAccessProfile, user = currentUser) {
  const metadata = user?.user_metadata || {};
  const address = formatAddress(applicantProfile, user);
  const governmentId = firstPresentValue(
    applicantProfile?.government_id,
    applicantProfile?.government_id_number,
    applicantProfile?.id_number,
    applicantProfile?.valid_id,
    metadata.government_id,
    metadata.government_id_number,
    metadata.id_number,
    metadata.valid_id
  );

  return {
    last_name: firstPresentValue(applicantProfile?.last_name, accessProfile?.lastName, metadata.last_name),
    first_name: firstPresentValue(applicantProfile?.first_name_raw, applicantProfile?.first_name, accessProfile?.firstName, metadata.first_name),
    middle_name: firstPresentValue(applicantProfile?.middle_name, accessProfile?.middleName, metadata.middle_name),
    suffix: firstPresentValue(applicantProfile?.suffix, accessProfile?.suffix, metadata.suffix),
    email: firstPresentValue(applicantProfile?.email, accessProfile?.email, user?.email),
    contact_number: firstPresentValue(applicantProfile?.contact_number, accessProfile?.contactNumber, metadata.contact_number),
    owner_contact_number: firstPresentValue(applicantProfile?.contact_number, accessProfile?.contactNumber, metadata.contact_number),
    home_address: address,
    gender: normalizeGender(firstPresentValue(applicantProfile?.gender, applicantProfile?.sex, metadata.gender, metadata.sex)),
    government_id: governmentId,
  };
}

function syncBusinessPermitType() {
  if (!permitSummaryCard) {
    return;
  }

  const params = new URLSearchParams(window.location.search);
  const applicationType = params.get("type");

  if (!applicationType) {
    return;
  }

  const isRenewal = applicationType === "renewal";

  if (permitTypeBadge) {
    permitTypeBadge.textContent = isRenewal ? "Renewal" : "New";
  }

  if (permitStartButton) {
    permitStartButton.querySelector("span").textContent = isRenewal ? "Start Renewal" : "Start Application";
  }
}

function enforceBusinessPermitTypeSelection() {
  if (!permitSummaryCard) {
    return false;
  }

  const params = new URLSearchParams(window.location.search);
  if (params.get("type")) {
    return false;
  }

  window.location.replace("/applicant/application-type");
  return true;
}

function renderActivePermits(permits) {
  if (!activePermitsGrid) {
    return;
  }

  if (!permits.length) {
    activePermitsGrid.innerHTML = `
      <article class="permit-summary-card permit-summary-card--empty">
        <h2>No active permits yet</h2>
        <p>Ask the admin to create and activate a permit first.</p>
      </article>
    `;
    return;
  }

  activePermitsGrid.innerHTML = permits
    .map(
      (permit, index) => `
        <section class="permit-summary-card" aria-labelledby="permit-${escapeHtml(permit.id)}">
          <header>
            <h2 id="permit-${escapeHtml(permit.id)}">${escapeHtml(permit.permitName)}</h2>
            <span>${escapeHtml(permit.category || "Permit")}</span>
          </header>
          <p>${escapeHtml(permit.description || "No description provided.")}</p>
          <dl>
            <dt>Code:</dt>
            <dd>${escapeHtml(permit.permitCode)}</dd>
          </dl>
          <button class="start-application-button" type="button" data-start-permit="${escapeHtml(permit.id)}">
            <span>Start Application</span>
            <i data-lucide="arrow-right" aria-hidden="true"></i>
          </button>
        </section>
      `
    )
    .join("");

  window.sessionStorage.setItem(SELECTED_PERMIT_KEY, permits[0].id);
  window.lucide?.createIcons();
}

async function loadActivePermits() {
  if (!activePermitsGrid) {
    return;
  }

  try {
    const payload = await applicantApi("/applicant/api/permits");
    activePermitCache = payload.permits || [];
    renderActivePermits(activePermitCache);
  } catch (error) {
    activePermitsGrid.innerHTML = `
      <article class="permit-summary-card permit-summary-card--empty">
        <h2>Unable to load permits</h2>
        <p>${escapeHtml(error.message)}</p>
      </article>
    `;
  }
}

async function startPermitApplication(permitId) {
  const button = document.querySelector(`[data-start-permit="${CSS.escape(permitId)}"]`);
  try {
    if (button) {
      button.disabled = true;
    }
    const payload = await applicantApi("/applicant/api/applications", {
      method: "POST",
      body: JSON.stringify({ permitId }),
    });
    window.sessionStorage.setItem(SELECTED_PERMIT_KEY, permitId);
    setCurrentApplicationId(payload.application?.id || "");
    window.location.href = "/applicant/new-application";
  } catch (error) {
    if (button) {
      button.disabled = false;
    }
    alert(error.message || "Unable to start application.");
  }
}

function readStoredPermits() {
  try {
    const raw = window.localStorage.getItem(PERMIT_STORAGE_KEY);
    const permits = raw ? JSON.parse(raw) : [];
    return Array.isArray(permits) ? permits : [];
  } catch {
    return [];
  }
}

function writeStoredPermits(permits) {
  try {
    window.localStorage.setItem(PERMIT_STORAGE_KEY, JSON.stringify(permits));
  } catch {
    // Ignore storage failures in restricted browser modes.
  }
}

function getCurrentApplicationId() {
  try {
    return window.sessionStorage.getItem(CURRENT_APPLICATION_KEY) || window.localStorage.getItem(CURRENT_APPLICATION_KEY) || "";
  } catch {
    return window.sessionStorage.getItem(CURRENT_APPLICATION_KEY) || "";
  }
}

function setCurrentApplicationId(applicationId) {
  if (!applicationId) {
    return;
  }

  window.sessionStorage.setItem(CURRENT_APPLICATION_KEY, applicationId);
  try {
    window.localStorage.setItem(CURRENT_APPLICATION_KEY, applicationId);
  } catch {
    // Session storage is enough for the active application flow.
  }
}

function getDraftBackupKey(applicationId) {
  return `${DRAFT_BACKUP_PREFIX}${applicationId}`;
}

function formatApplicantTime(value) {
  if (!value) {
    return "";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "";
  }
  return date.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

function setAutosaveStatus(message, state = "idle") {
  if (!autosaveStatus) {
    return;
  }
  autosaveStatus.textContent = message;
  autosaveStatus.dataset.state = state;
}

function readDraftBackup(applicationId) {
  try {
    return JSON.parse(window.localStorage.getItem(getDraftBackupKey(applicationId)) || "null");
  } catch {
    return null;
  }
}

function writeDraftBackup(applicationId, businessInfo) {
  try {
    window.localStorage.setItem(
      getDraftBackupKey(applicationId),
      JSON.stringify({ businessInfo, savedAt: new Date().toISOString() })
    );
  } catch {
    // The database remains the primary draft store.
  }
}

function clearDraftBackup(applicationId) {
  try {
    window.localStorage.removeItem(getDraftBackupKey(applicationId));
  } catch {
    // Nothing else is needed if local storage is unavailable.
  }
}

function continueDraftApplication(applicationId, permitId = "") {
  if (permitId) {
    window.sessionStorage.setItem(SELECTED_PERMIT_KEY, permitId);
  }
  setCurrentApplicationId(applicationId);
  window.location.href = `/applicant/business-information?applicationId=${encodeURIComponent(applicationId)}`;
}

async function loadApplicantDrafts() {
  if (!draftPanel || !draftList) {
    return;
  }

  try {
    const payload = await applicantApi("/applicant/api/drafts");
    const drafts = payload.drafts || [];
    if (!drafts.length) {
      draftPanel.hidden = true;
      draftList.innerHTML = "";
      return;
    }

    draftPanel.hidden = false;
    draftList.innerHTML = drafts
      .map((draft) => {
        const savedTime = formatApplicantTime(draft.updatedAt || draft.createdAt);
        const businessName = draft.businessName || "Business Permit Application";
        return `
          <article class="draft-card">
            <div>
              <strong>${escapeHtml(businessName)}</strong>
              <span>${escapeHtml(draft.permitName || "Business Permit")} ${savedTime ? `- last saved ${escapeHtml(savedTime)}` : ""}</span>
            </div>
            <button type="button" data-continue-draft="${escapeHtml(draft.id)}" data-draft-permit="${escapeHtml(draft.permitId || "")}">
              Continue Application
            </button>
          </article>
        `;
      })
      .join("");
    window.lucide?.createIcons();
  } catch (error) {
    draftPanel.hidden = false;
    draftList.innerHTML = `<p class="notification-empty">${escapeHtml(error.message || "Unable to load saved drafts.")}</p>`;
  }
}

function renderApplicantProgress(payload) {
  if (!progressPanel || !progressList) {
    return;
  }

  const steps = payload.steps || [];
  if (!steps.length) {
    progressPanel.hidden = true;
    return;
  }

  progressPanel.hidden = false;
  const application = payload.application || {};
  if (progressSummary) {
    progressSummary.textContent = `${application.businessName || "Your application"} is currently marked as ${payload.status || "In Progress"}.`;
  }

  progressList.innerHTML = steps
    .map((step) => {
      const stateClass = String(step.state || "").toLowerCase().replace(/[^a-z0-9]+/g, "-");
      const completedAt = formatApplicantTime(step.completedAt);
      return `
        <article class="applicant-progress-item applicant-progress-item--${escapeHtml(stateClass)}">
          <span>${escapeHtml(step.label)}</span>
          <strong>${escapeHtml(step.state || "Pending")}</strong>
          ${completedAt ? `<small>Completed ${escapeHtml(completedAt)}</small>` : ""}
          ${step.remarks ? `<p>${escapeHtml(step.remarks)}</p>` : ""}
        </article>
      `;
    })
    .join("");

  const departments = payload.departments || [];
  if (departmentProgressList) {
    departmentProgressList.innerHTML = departments.length
      ? `
        <h3>Department Review</h3>
        ${departments
          .map((department) => `
            <article class="department-progress-item">
              <span>${escapeHtml(department.departmentName || "Department")}</span>
              <strong>${escapeHtml(department.state || "Pending")}</strong>
              ${department.remarks ? `<p>${escapeHtml(department.remarks)}</p>` : ""}
            </article>
          `)
          .join("")}
      `
      : "";
  }
}

async function loadApplicantProgressForDashboard(applications = []) {
  const submittedApplications = applications.filter((application) => (application.status || "") !== "Draft");
  if (!submittedApplications.length) {
    if (progressPanel) {
      progressPanel.hidden = true;
    }
    return;
  }

  try {
    const applicationId = submittedApplications[0].id;
    const payload = await applicantApi(`/applicant/api/applications/${encodeURIComponent(applicationId)}/progress`);
    renderApplicantProgress(payload);
  } catch (error) {
    if (progressPanel && progressList) {
      progressPanel.hidden = false;
      progressList.innerHTML = `<p class="notification-empty">${escapeHtml(error.message || "Unable to load progress.")}</p>`;
    }
  }
}

function readStoredOcrFields() {
  try {
    return JSON.parse(window.sessionStorage.getItem(OCR_FIELDS_KEY) || "{}");
  } catch {
    return {};
  }
}

function writeStoredOcrFields(fields) {
  const current = readStoredOcrFields();
  const merged = { ...current, ...normalizeOcrFieldsForBusinessForm(fields) };
  window.sessionStorage.setItem(OCR_FIELDS_KEY, JSON.stringify(merged));
}

function clearStoredOcrFields() {
  window.sessionStorage.removeItem(OCR_FIELDS_KEY);
}

function updateRequirementsNextState() {
  if (!requirementsNextButton) {
    return;
  }

  const missingRequired = checklistDocuments.filter(
    (doc) => doc.requirementType === "Required" && !uploadedDocumentNames.get(doc.id)
  );
  const requiredWaitingForOcr = checklistDocuments.filter((doc) => {
    if (doc.requirementType !== "Required" || !uploadedDocumentNames.get(doc.id)) {
      return false;
    }

    const status = uploadedDocumentOcrStatus.get(doc.id);
    return status !== "Completed";
  });
  const requiredOcrFailed = requiredWaitingForOcr.filter((doc) => uploadedDocumentOcrStatus.get(doc.id) === "Failed");

  requirementsNextButton.disabled = missingRequired.length > 0 || requiredWaitingForOcr.length > 0;

  if (requirementsStatus) {
    if (missingRequired.length) {
      requirementsStatus.textContent = `${missingRequired.length} required document(s) still missing.`;
    } else if (requiredOcrFailed.length) {
      requirementsStatus.textContent = `${requiredOcrFailed.length} required document(s) failed OCR. Please re-upload a clearer file.`;
    } else if (requiredWaitingForOcr.length) {
      requirementsStatus.textContent = `Waiting for OCR to complete on ${requiredWaitingForOcr.length} required document(s).`;
    } else {
      requirementsStatus.textContent = "All required documents uploaded and OCR completed. You may continue.";
    }
    requirementsStatus.classList.toggle(
      "is-ready",
      missingRequired.length === 0 && requiredWaitingForOcr.length === 0
    );
  }
}

function redirectToBusinessInformationForm() {
  const applicationId = getCurrentApplicationId();
  const query = applicationId ? `?applicationId=${encodeURIComponent(applicationId)}` : "";
  window.location.href = `/applicant/business-information${query}`;
}

function renderChecklistDocuments(documents) {
  if (!dynamicDocumentGrid) {
    return;
  }

  checklistDocuments = documents || [];
  uploadedDocumentNames = new Map();
  uploadedDocumentOcrStatus = new Map();

  if (!checklistDocuments.length) {
    dynamicDocumentGrid.innerHTML = `
      <article class="document-card">
        <p>No document requirements configured for this permit.</p>
      </article>
    `;
    updateRequirementsNextState();
    return;
  }

  dynamicDocumentGrid.innerHTML = checklistDocuments
    .map((doc, index) => {
      const isRequired = doc.requirementType === "Required";
      return `
        <article class="document-card" data-document-card="${escapeHtml(doc.id)}">
          <header>
            <h3>${index + 1}. ${escapeHtml(doc.documentName)}</h3>
            <span class="doc-badge ${isRequired ? "doc-badge--required" : "doc-badge--optional"}">
              ${isRequired ? "Required" : "Optional"}
            </span>
          </header>
          <p class="document-card-description">${escapeHtml(doc.shortDescription || doc.notes || "")}</p>
          <input class="visually-hidden-file" type="file" data-file-input="${escapeHtml(doc.id)}" />
          <button class="upload-slot" type="button" data-upload-trigger="${escapeHtml(doc.id)}">
            <i data-lucide="file-up" aria-hidden="true"></i>
            <span>Upload Document</span>
            <small>${escapeHtml(doc.acceptedFileTypes || "PDF, JPG, PNG")} ${doc.maxFileSize ? ` / ${escapeHtml(doc.maxFileSize)}` : ""}</small>
          </button>
          <div class="upload-result" data-upload-result="${escapeHtml(doc.id)}">No file uploaded</div>
          <button class="remove-upload-button" type="button" data-remove-upload="${escapeHtml(doc.id)}" hidden>Remove file</button>
        </article>
      `;
    })
    .join("");
  window.lucide?.createIcons();
  updateRequirementsNextState();
}

function sanitizeStorageName(fileName) {
  return fileName.replace(/[^a-zA-Z0-9._-]/g, "_");
}

async function uploadApplicationFile(permitDocumentId, file) {
  const client = initSupabase();
  const applicationId = getCurrentApplicationId();
  if (!client || !currentUser?.id || !applicationId) {
    throw new Error("Application session is not ready. Please start the application again.");
  }

  const storagePath = `${currentUser.id}/${applicationId}/${permitDocumentId}/${Date.now()}-${sanitizeStorageName(file.name)}`;
  const { error } = await client.storage.from("application-documents").upload(storagePath, file, {
    cacheControl: "3600",
    upsert: false,
  });
  if (error) {
    throw new Error(error.message || "Unable to upload file.");
  }

  return storagePath;
}

async function persistApplicationDocument(permitDocumentId, fileName, uploadStatus, fileUrl = "") {
  const applicationId = getCurrentApplicationId();
  if (!applicationId) {
    return;
  }

  await applicantApi("/applicant/api/application-documents", {
    method: "POST",
    body: JSON.stringify({
      applicationId,
      permitDocumentId,
      fileName,
      fileUrl,
      uploadStatus,
    }),
  });
}

function structuredOcrFieldsToFlatFields(structuredFields = {}) {
  const flat = {};
  const confidence = {};
  Object.entries(structuredFields || {}).forEach(([fieldName, meta]) => {
    if (!meta || typeof meta !== "object") {
      return;
    }
    const value = meta.corrected_value || meta.value || "";
    const applicationField = meta.application_field || fieldName;
    const score = Number(meta.confidence || 0);
    if (!value || score < 70) {
      return;
    }
    flat[applicationField] = value;
    confidence[applicationField] = score;
  });
  if (Object.keys(confidence).length) {
    flat.field_confidence = confidence;
  }
  return flat;
}

function hasUsableOcrFormField(fields = {}) {
  return Object.entries(fields || {}).some(([key, value]) =>
    value !== undefined &&
    value !== null &&
    value !== "" &&
    !key.endsWith("_confidence") &&
    !OCR_METADATA_KEYS.has(key)
  );
}

function getExtractedFieldsFromOcrPayload(payload = {}) {
  const directFields = payload.extractedFields || payload.extracted_fields || {};
  if (hasUsableOcrFormField(directFields)) {
    return directFields;
  }
  return structuredOcrFieldsToFlatFields(payload.structuredFields || {});
}

function completeUploadedDocumentOcr(permitDocumentId, fileName, payload = {}) {
  const extractedFields = getExtractedFieldsFromOcrPayload(payload);
  writeStoredOcrFields(extractedFields);
  setSkipOcrAutoFill(false);
  applyOcrFieldsToBusinessForm(extractedFields);
  uploadedDocumentOcrStatus.set(permitDocumentId, "Completed");
  updateRequirementsNextState();

  const result = document.querySelector(`[data-upload-result="${CSS.escape(permitDocumentId)}"]`);
  if (result) {
    result.textContent = `${fileName} - OCR completed. Click Next Step to continue.`;
    result.classList.add("is-uploaded");
  }
}

async function runOcrForUploadedDocument(permitDocumentId, fileName, fileUrl) {
  const applicationId = getCurrentApplicationId();
  const documentConfig = checklistDocuments.find((doc) => doc.id === permitDocumentId);

  const result = document.querySelector(`[data-upload-result="${CSS.escape(permitDocumentId)}"]`);

  if (result) {
    result.textContent = `${fileName} - Reading document...`;
  }
  uploadedDocumentOcrStatus.set(permitDocumentId, "Processing");
  updateRequirementsNextState();

  try {
    const payload = await applicantApi("/applicant/api/ocr-extract", {
      method: "POST",
      body: JSON.stringify({
        applicationId,
        permitDocumentId,
        fileName,
        fileUrl,
        documentType: documentConfig?.documentName || "",
      }),
    });

    completeUploadedDocumentOcr(permitDocumentId, fileName, payload);
  } catch (error) {
    uploadedDocumentOcrStatus.set(permitDocumentId, "Failed");
    if (result) {
      result.textContent = `${fileName} - Uploaded, but OCR failed`;
      result.classList.add("is-uploaded");
    }
    updateRequirementsNextState();

    console.error("OCR error:", error);
  }
}

async function handleChecklistFileSelected(input) {
  const permitDocumentId = input.dataset.fileInput || "";
  const file = input.files?.[0];
  if (!permitDocumentId || !file) {
    return;
  }

  const result = document.querySelector(`[data-upload-result="${CSS.escape(permitDocumentId)}"]`);
  const removeButton = document.querySelector(`[data-remove-upload="${CSS.escape(permitDocumentId)}"]`);
  if (result) {
    result.textContent = "Uploading...";
    result.classList.remove("is-uploaded");
  }
  try {
    const previousPreviewUrl = uploadedDocumentPreviewUrls.get(permitDocumentId);
    if (previousPreviewUrl) {
      URL.revokeObjectURL(previousPreviewUrl);
    }
    uploadedDocumentPreviewUrls.set(permitDocumentId, URL.createObjectURL(file));
    const fileUrl = await uploadApplicationFile(permitDocumentId, file);
    uploadedDocumentNames.set(permitDocumentId, file.name);
    uploadedDocumentOcrStatus.set(permitDocumentId, "Pending");
    if (result) {
      result.textContent = file.name;
      result.classList.add("is-uploaded");
    }
    if (removeButton) {
      removeButton.hidden = false;
    }
    updateRequirementsNextState();
    await persistApplicationDocument(permitDocumentId, file.name, "Uploaded", fileUrl);
    await runOcrForUploadedDocument(permitDocumentId, file.name, fileUrl);
  } catch (error) {
    uploadedDocumentNames.delete(permitDocumentId);
    uploadedDocumentOcrStatus.delete(permitDocumentId);
    if (result) {
      result.textContent = error.message || "Unable to upload file.";
      result.classList.remove("is-uploaded");
    }
    if (removeButton) {
      removeButton.hidden = true;
    }
    if (requirementsStatus) {
      requirementsStatus.textContent = error.message || "Unable to upload file.";
      requirementsStatus.classList.remove("is-ready");
    }
    updateRequirementsNextState();
  }
}

async function removeChecklistUpload(permitDocumentId) {
  uploadedDocumentNames.delete(permitDocumentId);
  uploadedDocumentOcrStatus.delete(permitDocumentId);
  const previousPreviewUrl = uploadedDocumentPreviewUrls.get(permitDocumentId);
  if (previousPreviewUrl) {
    URL.revokeObjectURL(previousPreviewUrl);
    uploadedDocumentPreviewUrls.delete(permitDocumentId);
  }
  const result = document.querySelector(`[data-upload-result="${CSS.escape(permitDocumentId)}"]`);
  const removeButton = document.querySelector(`[data-remove-upload="${CSS.escape(permitDocumentId)}"]`);
  const input = document.querySelector(`[data-file-input="${CSS.escape(permitDocumentId)}"]`);
  if (input) {
    input.value = "";
  }
  if (result) {
    result.textContent = "No file uploaded";
    result.classList.remove("is-uploaded");
  }
  if (removeButton) {
    removeButton.hidden = true;
  }
  updateRequirementsNextState();
  try {
    await persistApplicationDocument(permitDocumentId, "", "Removed");
  } catch {
    // Keep the local UI responsive; the applicant can reselect the file.
  }
}

async function loadRequirementsChecklist() {
  if (!dynamicDocumentGrid) {
    return;
  }

  const permitId = window.sessionStorage.getItem(SELECTED_PERMIT_KEY);
  if (!permitId) {
    dynamicDocumentGrid.innerHTML = `
      <article class="document-card">
        <p>No permit selected. Please start from the permit page.</p>
      </article>
    `;
    return;
  }

  try {
    const payload = await applicantApi(`/applicant/api/permits/${encodeURIComponent(permitId)}`);
    const permit = payload.permit;
    if (checklistPermitName) {
      checklistPermitName.textContent = permit.permitName || "Permit";
    }
    if (checklistPermitCode) {
      checklistPermitCode.textContent = permit.permitCode || "Code";
    }
    renderChecklistDocuments(permit.documents || []);
  } catch (error) {
    dynamicDocumentGrid.innerHTML = `
      <article class="document-card">
        <p>${escapeHtml(error.message || "Unable to load requirements.")}</p>
      </article>
    `;
  }
}

function normalizeOcrFieldsForBusinessForm(fields = {}) {
  const aliases = {
    date_of_application: "application_date",
    dti_registration_no: "registration_number",
    dti_registration_number: "registration_number",
    registration_no: "registration_number",
    certificate_no: "registration_number",
    owner_first_name: "first_name",
    owner_middle_name: "middle_name",
    owner_last_name: "last_name",
    registered_email: "email",
    registered_contact_number: "contact_number",
    business_type: "type_of_business",
    business_types: "type_of_business",
    capital_investment: "capitalization",
    ownerName: "owner_name",
    businessName: "business_name",
    businessAddress: "business_address",
    dateIssued: "date_issued",
    grossSales: "goods_value",
    gross_sales: "goods_value",
  };
  const normalized = {};

  Object.entries(fields || {}).forEach(([key, value]) => {
    if (value === undefined || value === null || value === "") {
      return;
    }

    if (key.endsWith("_confidence") || OCR_METADATA_KEYS.has(key)) {
      normalized[key] = value;
      return;
    }

    if (typeof value === "object" && !Array.isArray(value) && "value" in value) {
      normalized[aliases[key] || key] = value.value;
      normalized.field_confidence = {
        ...(normalized.field_confidence || {}),
        [aliases[key] || key]: value.confidence,
      };
      return;
    }

    normalized[aliases[key] || key] = value;
  });

  if (normalized.owner_name && (!normalized.first_name || !normalized.last_name)) {
    const nameParts = String(normalized.owner_name).trim().split(/\s+/).filter(Boolean);
    if (nameParts.length >= 2) {
      normalized.first_name ||= nameParts[0];
      normalized.last_name ||= nameParts.at(-1);
      normalized.middle_name ||= nameParts.slice(1, -1).join(" ");
    } else if (nameParts.length === 1) {
      normalized.first_name ||= nameParts[0];
    }
  }

  if (typeof normalized.type_of_business === "string") {
    normalized.type_of_business = normalized.type_of_business
      .toUpperCase()
      .replace("SOLE PROPRIETORSHIP", "SINGLE");
  }

  return normalized;
}

function isValidBusinessName(value) {
  if (!value) {
    return false;
  }

  const badWords = [
    "no.",
    "number",
    "registration",
    "issued",
    "issue",
    "philippines",
    "secretary",
    "certificate",
    "department",
    "trade and industry",
    "this is to certify",
    "pursuant",
    "valid",
  ];
  const normalizedValue = String(value).trim();
  const lowerValue = normalizedValue.toLowerCase();

  if (normalizedValue.length < 3 || normalizedValue.length > 80) {
    return false;
  }

  if (!/[a-z]/i.test(normalizedValue)) {
    return false;
  }

  if (/\b(?:no|number)\.?\s*\d/i.test(normalizedValue)) {
    return false;
  }

  if (/^(?:no\.?\s*)?[a-z0-9-]{4,}$/i.test(normalizedValue) && (normalizedValue.match(/[a-z]/gi) || []).length <= 2) {
    return false;
  }

  return !badWords.some((word) => lowerValue.includes(word));
}

function containsLabelText(value) {
  if (!value) {
    return false;
  }

  const labels = [
    "business name",
    "trade name",
    "tradename",
    "tin",
    "business address",
    "business location",
  ];
  const lowerValue = String(value).toLowerCase();
  return labels.some((label) => lowerValue.includes(label));
}

function isValidBusinessAddress(value) {
  if (!value) {
    return false;
  }

  const normalizedValue = String(value).trim();
  if (normalizedValue.length > 250) {
    return false;
  }

  if (containsLabelText(normalizedValue)) {
    return false;
  }

  return true;
}

function shouldSkipOcrAutoFill(applicationId = getCurrentApplicationId()) {
  return window.sessionStorage.getItem(`${OCR_SKIP_KEY}:${applicationId}`) === "1";
}

function setSkipOcrAutoFill(skip, applicationId = getCurrentApplicationId()) {
  if (!applicationId) {
    return;
  }

  const key = `${OCR_SKIP_KEY}:${applicationId}`;
  if (skip) {
    window.sessionStorage.setItem(key, "1");
  } else {
    window.sessionStorage.removeItem(key);
  }
}

function notifyBusinessFieldChanged(control) {
  control.dispatchEvent(new Event("input", { bubbles: true }));
  control.dispatchEvent(new Event("change", { bubbles: true }));
}

function hasExistingBusinessFieldValue(controls) {
  return [...controls].some((control) => {
    if (control instanceof HTMLInputElement) {
      if (control.type === "radio" || control.type === "checkbox") {
        return control.checked;
      }
      return control.value.trim() !== "";
    }

    if (control instanceof HTMLTextAreaElement || control instanceof HTMLSelectElement) {
      return control.value.trim() !== "" && !control.value.startsWith("Select ");
    }

    return false;
  });
}

function hasReplaceableOcrFieldValue(controls) {
  const controlsWithValues = [...controls].filter((control) => {
    if (control instanceof HTMLInputElement) {
      if (control.type === "radio" || control.type === "checkbox") {
        return control.checked;
      }
      return control.value.trim() !== "";
    }

    if (control instanceof HTMLTextAreaElement || control instanceof HTMLSelectElement) {
      return control.value.trim() !== "" && !control.value.startsWith("Select ");
    }

    return false;
  });

  return controlsWithValues.length > 0 && controlsWithValues.every((control) =>
    control.classList.contains("is-ocr-filled") || control.classList.contains("is-ocr-review")
  );
}

function isOwnerNameValue(value) {
  if (!businessFormShell || !value) {
    return false;
  }

  const ownerName = [
    getBusinessFieldValue("first_name"),
    getBusinessFieldValue("middle_name"),
    getBusinessFieldValue("last_name"),
    getBusinessFieldValue("suffix"),
  ]
    .filter(Boolean)
    .join(" ")
    .replace(/\s+/g, " ")
    .trim()
    .toUpperCase();

  return ownerName && String(value).replace(/\s+/g, " ").trim().toUpperCase() === ownerName;
}

function markBusinessFieldTouched(target) {
  if (isApplyingBusinessDefaults || !(target instanceof HTMLElement)) {
    return;
  }

  const control = target.closest("[data-business-field]");
  if (control instanceof HTMLElement) {
    const fieldName = control.dataset.businessField || "";
    if (fieldName) {
      editedBusinessFields.add(fieldName);
    }
  }
}

function setBusinessFieldValue(name, value, options = {}) {
  if (!businessFormShell || value === undefined || value === null || value === "") {
    return;
  }

  if (name === "business_name" && (!isValidBusinessName(value) || isOwnerNameValue(value))) {
    console.warn("Rejected invalid business name from OCR:", value);
    return;
  }

  if (name === "business_address" && !isValidBusinessAddress(value)) {
    console.warn("Rejected invalid business address from OCR:", value);
    return;
  }

  const selector = OCR_FORM_FIELD_MAP[name] || `[data-business-field="${CSS.escape(name)}"]`;
  const controls = businessFormShell.querySelectorAll(selector);
  if (!controls.length) {
    return;
  }

  const hasExistingValue = hasExistingBusinessFieldValue(controls);
  const canReplaceOcrValue = options.allowOcrReplace && hasReplaceableOcrFieldValue(controls);
  if (!options.force && (editedBusinessFields.has(name) || (hasExistingValue && !canReplaceOcrValue))) {
    return;
  }

  const filledClassName = options.className || "is-ocr-filled";

  isApplyingBusinessDefaults = true;
  controls.forEach((control) => {
    control.classList.remove("is-ocr-filled", "is-ocr-review");
    if (control instanceof HTMLInputElement) {
      if (control.type === "radio") {
        control.checked = control.value === value;
        if (control.checked) {
          control.classList.add(filledClassName);
          notifyBusinessFieldChanged(control);
        }
        return;
      }

      if (control.type === "checkbox") {
        const values = Array.isArray(value) ? value : String(value).split(",").map((item) => item.trim().toUpperCase());
        control.checked = Array.isArray(value)
          ? value.includes(control.value)
          : values.includes(control.value);
        if (control.checked) {
          control.classList.add(filledClassName);
          notifyBusinessFieldChanged(control);
        }
        return;
      }

      control.value = value;
      control.classList.add(filledClassName);
      notifyBusinessFieldChanged(control);
      return;
    }

    if (control instanceof HTMLTextAreaElement || control instanceof HTMLSelectElement) {
      control.value = value;
      control.classList.add(filledClassName);
      notifyBusinessFieldChanged(control);
    }
  });
  isApplyingBusinessDefaults = false;
}

function normalizeOcrConfidenceLevel(confidence) {
  if (typeof confidence === "number") {
    if (confidence <= 1) {
      if (confidence >= 0.8) return "high";
      if (confidence >= 0.6) return "medium";
      return "low";
    }
    if (confidence >= 90) return "high";
    if (confidence >= 70) return "medium";
    return "low";
  }

  const normalized = String(confidence || "").trim().toLowerCase();
  if (["high", "medium", "low"].includes(normalized)) {
    return normalized;
  }

  return "high";
}

function getOcrFieldConfidence(fields, fieldName) {
  const confidenceMap = fields.field_confidence || fields.fieldConfidence || fields.confidence || {};
  const aliases = {
    business_name: ["business_name", "businessName"],
    trade_name: ["trade_name", "tradeName"],
    tin: ["tin"],
    business_address: ["business_address", "businessAddress"],
    goods_value: ["goods_value", "gross_sales", "grossSales"],
    date_issued: ["date_issued", "dateIssued"],
    owner_name: ["owner_name", "ownerName"],
  };
  const confidenceKeys = aliases[fieldName] || [fieldName];

  for (const key of confidenceKeys) {
    if (confidenceMap[key] !== undefined && confidenceMap[key] !== null) {
      return normalizeOcrConfidenceLevel(confidenceMap[key]);
    }
  }

  const directConfidence = fields[`${fieldName}_confidence`];
  return normalizeOcrConfidenceLevel(directConfidence);
}

function applyOcrFieldsToBusinessForm(fields = readStoredOcrFields()) {
  if (!businessFormShell || shouldSkipOcrAutoFill()) {
    return;
  }

  const extractedFields = normalizeOcrFieldsForBusinessForm(fields);

  Object.entries(extractedFields).forEach(([fieldName, fieldValue]) => {
    if (fieldName.endsWith("_confidence") || OCR_METADATA_KEYS.has(fieldName)) {
      return;
    }

    const confidenceLevel = getOcrFieldConfidence(extractedFields, fieldName);
    if (confidenceLevel === "low") {
      console.warn("Skipped low-confidence OCR field:", fieldName, fieldValue);
      return;
    }

    if (fieldName === "business_address" && confidenceLevel !== "high") {
      console.warn("Skipped uncertain business address from OCR:", fieldValue);
      return;
    }

    setBusinessFieldValue(fieldName, fieldValue, {
      className: confidenceLevel === "medium" ? "is-ocr-review" : "is-ocr-filled",
      allowOcrReplace: confidenceLevel === "high",
    });
  });
}

async function loadOcrFieldsIntoBusinessForm(applicationId) {
  if (!businessFormShell || !applicationId || shouldSkipOcrAutoFill(applicationId)) {
    return;
  }

  try {
    const result = await applicantApi(`/applicant/api/application/${encodeURIComponent(applicationId)}/ocr-fields`);
    if (!result.success) {
      console.warn("No OCR fields found:", result.error);
      return;
    }

    const fields = normalizeOcrFieldsForBusinessForm(result.fields || result.extracted_fields || result.extractedFields || {});
    writeStoredOcrFields(fields);
    applyOcrFieldsToBusinessForm(fields);

    const hasSavedOcr = Number(result.ocrResultCount || 0) > 0;
    if (hasSavedOcr && !Object.keys(fields).length) {
      alert("OCR was completed, but no readable business details were found. Please fill out the form manually.");
    }
  } catch (error) {
    console.error("Failed to load OCR fields:", error);
  }
}

function applyApplicantProfileToBusinessForm() {
  if (!businessFormShell || !currentUser) {
    return 0;
  }

  const defaults = collectProfileBusinessDefaults();
  let appliedCount = 0;

  Object.entries(defaults).forEach(([fieldName, fieldValue]) => {
    if (!fieldValue) {
      return;
    }

    const beforeValues = [...businessFormShell.querySelectorAll(`[data-business-field="${CSS.escape(fieldName)}"]`)].map(
      (control) => {
        if (control instanceof HTMLInputElement && (control.type === "radio" || control.type === "checkbox")) {
          return control.checked;
        }
        return control instanceof HTMLInputElement || control instanceof HTMLTextAreaElement || control instanceof HTMLSelectElement
          ? control.value
          : "";
      }
    );
    setBusinessFieldValue(fieldName, fieldValue, { className: "is-profile-filled" });
    const afterValues = [...businessFormShell.querySelectorAll(`[data-business-field="${CSS.escape(fieldName)}"]`)].map(
      (control) => {
        if (control instanceof HTMLInputElement && (control.type === "radio" || control.type === "checkbox")) {
          return control.checked;
        }
        return control instanceof HTMLInputElement || control instanceof HTMLTextAreaElement || control instanceof HTMLSelectElement
          ? control.value
          : "";
      }
    );

    if (JSON.stringify(beforeValues) !== JSON.stringify(afterValues)) {
      appliedCount += 1;
    }
  });

  return appliedCount;
}

async function loadApplicantProfileIntoBusinessForm() {
  if (!businessFormShell || !currentUser) {
    return;
  }

  setProfilePrefillStatus("Loading saved applicant information...", "warning");

  try {
    const appliedCount = applyApplicantProfileToBusinessForm();
    const hasAnySavedProfileValue = Object.values(collectProfileBusinessDefaults()).some(Boolean);

    if (applicantProfileLoadError && !hasAnySavedProfileValue) {
      setProfilePrefillStatus("Saved applicant information could not be loaded. Please complete these fields manually.", "error");
      return;
    }

    if (applicantProfileLoadError) {
      setProfilePrefillStatus("Some saved applicant information was loaded. Please review and complete any missing fields.", "warning");
      return;
    }

    if (appliedCount > 0) {
      setProfilePrefillStatus("Saved applicant information has been filled in. You can still edit it before submitting.", "ready");
      return;
    }

    if (hasAnySavedProfileValue) {
      setProfilePrefillStatus("Saved applicant information is already present in the form.", "ready");
      return;
    }

    setProfilePrefillStatus("No saved applicant details were found. Please complete this section manually.", "warning");
  } catch (error) {
    console.error("Failed to auto-fill applicant profile:", error);
    setProfilePrefillStatus("Saved applicant information could not be loaded. Please complete these fields manually.", "error");
  }
}

function getBusinessFieldValue(name) {
  if (!businessFormShell) {
    return "";
  }

  const control = businessFormShell.querySelector(`[data-business-field="${name}"]`);
  if (!control) {
    return "";
  }

  if (control instanceof HTMLInputElement) {
    if (control.type === "checkbox") {
      return control.checked ? control.value : "";
    }

    if (control.type === "radio") {
      const selected = businessFormShell.querySelector(
        `[data-business-field="${name}"]:checked`
      );
      return selected instanceof HTMLInputElement ? selected.value : "";
    }

    return control.value.trim();
  }

  if (control instanceof HTMLTextAreaElement || control instanceof HTMLSelectElement) {
    return control.value.trim();
  }

  return "";
}

function normalizeReviewValue(value) {
  if (Array.isArray(value)) {
    return value.filter(Boolean).join(", ");
  }

  const text = String(value || "").trim();
  return text.startsWith("Select ") ? "" : text;
}

function formatReviewValue(value, fallback = "Not filled in yet") {
  return normalizeReviewValue(value) || fallback;
}

function setReviewValue(name, value, fallback = "Not filled in yet") {
  document.querySelectorAll(`[data-review-value="${name}"]`).forEach((target) => {
    const formattedValue = formatReviewValue(value, fallback);
    target.textContent = formattedValue;
    target.classList.toggle("is-missing", formattedValue === fallback || formattedValue === "Missing information");
  });
}

function formatOwnerName(application) {
  return [application.firstName, application.middleName, application.lastName, application.suffix].filter(Boolean).join(" ");
}

function getMissingBusinessFields(application) {
  return BUSINESS_REQUIRED_FIELDS.filter(([key]) => {
    const value = application[key];
    if (Array.isArray(value)) {
      return value.length === 0;
    }
    return !normalizeReviewValue(value);
  }).map(([, label]) => label);
}

function updateReviewValidation(missingFields = []) {
  const summary = document.querySelector("[data-review-validation-summary]");
  const list = document.querySelector("[data-review-validation-list]");

  if (summary) {
    summary.textContent = missingFields.length
      ? `${missingFields.length} required field(s) need attention before submission.`
      : "All required business information is complete. You may submit the application.";
    summary.classList.toggle("is-ready", missingFields.length === 0);
    summary.classList.toggle("is-warning", missingFields.length > 0);
  }

  if (!list) {
    return;
  }

  list.hidden = missingFields.length === 0;
  list.innerHTML = missingFields.map((field) => `<li>${escapeHtml(field)}</li>`).join("");
}

function collectBusinessApplication() {
  const checkedBusinessTypes = businessFormShell
    ? [...businessFormShell.querySelectorAll('[data-business-field="type_of_business"]:checked')].map(
        (input) => input.value
      )
    : [];

  return {
    applicationDate: getBusinessFieldValue("application_date"),
    registrationNumber: getBusinessFieldValue("registration_number"),
    modeOfPayment: getBusinessFieldValue("mode_of_payment"),
    lastName: getBusinessFieldValue("last_name"),
    firstName: getBusinessFieldValue("first_name"),
    middleName: getBusinessFieldValue("middle_name"),
    suffix: getBusinessFieldValue("suffix"),
    email: getBusinessFieldValue("email"),
    contactNumber: getBusinessFieldValue("contact_number"),
    gender: getBusinessFieldValue("gender"),
    governmentId: getBusinessFieldValue("government_id"),
    homeAddress: getBusinessFieldValue("home_address"),
    businessName: getBusinessFieldValue("business_name"),
    tradeName: getBusinessFieldValue("trade_name"),
    businessTypes: checkedBusinessTypes,
    businessClassificationId: getBusinessFieldValue("business_classification_id"),
    businessClassification: getBusinessFieldValue("business_classification"),
    tin: getBusinessFieldValue("tin"),
    businessAddress: getBusinessFieldValue("business_address"),
    locationDetail: getBusinessFieldValue("location_detail"),
    businessBarangay: getBusinessFieldValue("business_barangay"),
    businessPremise: getBusinessFieldValue("business_premise"),
    businessTelephone: getBusinessFieldValue("business_telephone"),
    businessMobile: getBusinessFieldValue("business_mobile"),
    businessEmail: getBusinessFieldValue("business_email"),
    ownerContactNumber: getBusinessFieldValue("owner_contact_number"),
    emergencyContactPerson: getBusinessFieldValue("emergency_contact_person"),
    emergencyContact: getBusinessFieldValue("emergency_contact"),
    businessArea: getBusinessFieldValue("business_area"),
    employeesTotal: getBusinessFieldValue("employees_total"),
    employeesLgu: getBusinessFieldValue("employees_lgu"),
    businessActivity: getBusinessFieldValue("business_activity"),
    capitalization: getBusinessFieldValue("capitalization"),
    goodsValue: getBusinessFieldValue("goods_value"),
    grossSales: getBusinessFieldValue("goods_value"),
    dateIssued: getBusinessFieldValue("date_issued"),
    taxIncentive: getBusinessFieldValue("tax_incentive"),
    taxIncentiveEntity: getBusinessFieldValue("tax_incentive_entity"),
  };
}

function updateReviewCopy(application) {
  const missingFields = getMissingBusinessFields(application);

  setReviewValue("business_name", application.businessName);
  setReviewValue("business_name_detail", application.businessName);
  setReviewValue("business_address", application.businessAddress || application.homeAddress);
  setReviewValue("business_address_detail", application.businessAddress);
  setReviewValue("owner_name", formatOwnerName(application));
  setReviewValue("business_mobile", application.businessMobile || application.contactNumber);
  setReviewValue("business_mobile_detail", application.businessMobile);
  setReviewValue("business_email", application.businessEmail || application.email);
  setReviewValue("business_email_detail", application.businessEmail);
  setReviewValue("mode_of_payment", application.modeOfPayment, "Not selected");
  setReviewValue("mode_of_payment_detail", application.modeOfPayment, "Not selected");
  setReviewValue("application_date", application.applicationDate);
  setReviewValue("registration_number", application.registrationNumber);
  setReviewValue("last_name", application.lastName);
  setReviewValue("first_name", application.firstName);
  setReviewValue("middle_name", application.middleName);
  setReviewValue("suffix", application.suffix);
  setReviewValue("email", application.email);
  setReviewValue("contact_number", application.contactNumber);
  setReviewValue("gender", application.gender);
  setReviewValue("government_id", application.governmentId);
  setReviewValue("home_address", application.homeAddress);
  setReviewValue("trade_name", application.tradeName);
  setReviewValue("business_types", application.businessTypes);
  setReviewValue("business_classification", application.businessClassification);
  setReviewValue("tin", application.tin);
  setReviewValue("location_detail", application.locationDetail);
  setReviewValue("business_barangay", application.businessBarangay);
  setReviewValue("business_premise", application.businessPremise);
  setReviewValue("business_telephone", application.businessTelephone);
  setReviewValue("owner_contact_number", application.ownerContactNumber);
  setReviewValue("emergency_contact_person", application.emergencyContactPerson);
  setReviewValue("emergency_contact", application.emergencyContact);
  setReviewValue("business_area", application.businessArea);
  setReviewValue("employees_total", application.employeesTotal);
  setReviewValue("employees_lgu", application.employeesLgu);
  setReviewValue("business_activity", application.businessActivity);
  setReviewValue("capitalization", application.capitalization);
  setReviewValue("goods_value", application.goodsValue);
  setReviewValue("date_issued", application.dateIssued);
  setReviewValue("tax_incentive", application.taxIncentive);
  setReviewValue("tax_incentive_entity", application.taxIncentiveEntity);
  updateReviewValidation(missingFields);
}

function setBusinessStep(step) {
  if (!businessStepPanels.form) {
    return;
  }

  const isReview = step === "review";
  businessStepPanels.form.classList.toggle("is-hidden", isReview);
  reviewStrip?.classList.toggle("is-hidden", !isReview);

  const stepperSteps = document.querySelectorAll(".progress-stepper--business .progress-step");
  const firstStep = stepperSteps[0];
  const secondStep = stepperSteps[1];
  const thirdStep = stepperSteps[2];

  firstStep?.classList.add("progress-step--done");
  firstStep?.classList.remove("progress-step--current");
  secondStep?.classList.toggle("progress-step--current", !isReview);
  secondStep?.classList.toggle("progress-step--done", isReview);
  thirdStep?.classList.toggle("progress-step--current", isReview);
  thirdStep?.classList.toggle("progress-step--done", false);

  if (isReview) {
    reviewStrip?.scrollIntoView({ behavior: "smooth", block: "start" });
  }
}

function isBusinessReviewStepVisible() {
  return Boolean(reviewStrip && !reviewStrip.classList.contains("is-hidden"));
}

function handleHistoryBack(event) {
  const target = event.currentTarget;
  if (!(target instanceof HTMLAnchorElement)) {
    return;
  }

  if (isBusinessReviewStepVisible()) {
    event.preventDefault();
    setBusinessStep("form");
    businessFormShell?.scrollIntoView({ behavior: "smooth", block: "start" });
    return;
  }

  try {
    if (window.history.length > 1 && document.referrer && new URL(document.referrer).origin === window.location.origin) {
      event.preventDefault();
      window.history.back();
    }
  } catch {
    // Keep the anchor href as the fallback destination.
  }
}

function createPermitRecord(application, userId = "") {
  const createdAt = new Date();
  const permitSuffix = `${createdAt.getTime()}`.slice(-6);
  const submittedSuffix = `${createdAt.getTime()}`.slice(-8);

  return {
    user_id: userId,
    permit_id: `BPLO-${permitSuffix}`,
    business_name: application.businessName || "Untitled Business",
    status: "Submitted",
    progress: "Review complete",
    submitted_id: submittedSuffix,
    application_type: "New Application",
    application_payload: application,
    created_at: createdAt.toISOString(),
  };
}

function createBusinessInfoPayload(application) {
  return {
    application_date: application.applicationDate,
    registration_number: application.registrationNumber,
    mode_of_payment: application.modeOfPayment,
    last_name: application.lastName,
    first_name: application.firstName,
    middle_name: application.middleName,
    suffix: application.suffix,
    owner_name: [application.firstName, application.middleName, application.lastName, application.suffix].filter(Boolean).join(" "),
    email: application.email,
    contact_number: application.contactNumber,
    gender: application.gender,
    government_id: application.governmentId,
    home_address: application.homeAddress,
    business_name: application.businessName,
    trade_name: application.tradeName,
    business_types: application.businessTypes,
    business_classification_id: application.businessClassificationId,
    business_classification: application.businessClassification,
    tin: application.tin,
    business_address: application.businessAddress,
    location_detail: application.locationDetail,
    business_barangay: application.businessBarangay,
    business_premise: application.businessPremise,
    business_telephone: application.businessTelephone,
    business_mobile: application.businessMobile,
    business_email: application.businessEmail,
    owner_contact_number: application.ownerContactNumber,
    emergency_contact_person: application.emergencyContactPerson,
    emergency_contact: application.emergencyContact,
    business_area: application.businessArea,
    employees_total: application.employeesTotal,
    employees_lgu: application.employeesLgu,
    business_activity: application.businessActivity,
    capitalization: application.capitalization,
    goods_value: application.goodsValue,
    gross_sales: application.grossSales,
    date_issued: application.dateIssued,
    tax_incentive: application.taxIncentive,
    tax_incentive_entity: application.taxIncentiveEntity,
  };
}

const BUSINESS_INFO_TO_FIELD_MAP = {
  application_date: "application_date",
  registration_number: "registration_number",
  mode_of_payment: "mode_of_payment",
  last_name: "last_name",
  first_name: "first_name",
  middle_name: "middle_name",
  suffix: "suffix",
  email: "email",
  contact_number: "contact_number",
  gender: "gender",
  government_id: "government_id",
  home_address: "home_address",
  business_name: "business_name",
  trade_name: "trade_name",
  business_types: "type_of_business",
  business_classification_id: "business_classification_id",
  business_classification: "business_classification",
  tin: "tin",
  business_address: "business_address",
  location_detail: "location_detail",
  business_barangay: "business_barangay",
  business_premise: "business_premise",
  business_telephone: "business_telephone",
  business_mobile: "business_mobile",
  business_email: "business_email",
  owner_contact_number: "owner_contact_number",
  emergency_contact_person: "emergency_contact_person",
  emergency_contact: "emergency_contact",
  business_area: "business_area",
  employees_total: "employees_total",
  employees_lgu: "employees_lgu",
  business_activity: "business_activity",
  capitalization: "capitalization",
  goods_value: "goods_value",
  gross_sales: "goods_value",
  date_issued: "date_issued",
  tax_incentive: "tax_incentive",
  tax_incentive_entity: "tax_incentive_entity",
};

function applyBusinessInfoToForm(businessInfo = {}) {
  if (!businessFormShell || !businessInfo || typeof businessInfo !== "object") {
    return;
  }

  isRestoringDraft = true;
  Object.entries(BUSINESS_INFO_TO_FIELD_MAP).forEach(([sourceKey, fieldName]) => {
    if (!Object.prototype.hasOwnProperty.call(businessInfo, sourceKey)) {
      return;
    }
    setBusinessFieldValue(fieldName, businessInfo[sourceKey], { force: true, className: "is-draft-filled" });
  });
  if (businessClassificationSearch && businessInfo.business_classification) {
    businessClassificationSearch.value = businessInfo.business_classification;
  }
  isRestoringDraft = false;
}

function restoreDraftDocuments(documents = []) {
  documents.forEach((documentRecord) => {
    const documentId = documentRecord.permitDocumentId;
    if (!documentId) {
      return;
    }
    const result = document.querySelector(`[data-upload-result="${CSS.escape(documentId)}"]`);
    const removeButton = document.querySelector(`[data-remove-upload="${CSS.escape(documentId)}"]`);
    if (documentRecord.fileName) {
      uploadedDocumentNames.set(documentId, documentRecord.fileName);
      uploadedDocumentOcrStatus.set(documentId, documentRecord.ocrStatus || "Completed");
      if (result) {
        result.textContent = `${documentRecord.fileName} - already uploaded`;
        result.classList.add("is-uploaded");
      }
      if (removeButton) {
        removeButton.hidden = false;
      }
    }
  });
  updateRequirementsNextState();
}

async function loadDraftIntoBusinessForm() {
  if (!businessFormShell && !dynamicDocumentGrid) {
    return;
  }

  const params = new URLSearchParams(window.location.search);
  const applicationId = params.get("applicationId") || getCurrentApplicationId();
  if (!applicationId) {
    setAutosaveStatus("Start an application first so your draft can be saved.", "error");
    return;
  }

  setCurrentApplicationId(applicationId);
  try {
    const payload = await applicantApi(`/applicant/api/applications/${encodeURIComponent(applicationId)}/draft`);
    if (payload.draft?.permitId) {
      window.sessionStorage.setItem(SELECTED_PERMIT_KEY, payload.draft.permitId);
    }
    if (businessFormShell) {
      applyBusinessInfoToForm(payload.businessInfo || {});
    }
    restoreDraftDocuments(payload.documents || []);
    const localBackup = readDraftBackup(applicationId);
    if (businessFormShell && localBackup?.businessInfo) {
      applyBusinessInfoToForm(localBackup.businessInfo);
      setAutosaveStatus(`Restored a local backup from ${formatApplicantTime(localBackup.savedAt)}. Auto-save will retry.`, "warning");
      return;
    }
    const savedTime = formatApplicantTime(payload.draft?.updatedAt);
    setAutosaveStatus(savedTime ? `Last saved at ${savedTime}` : "Draft loaded. Auto-save is ready.", "saved");
  } catch (error) {
    const localBackup = readDraftBackup(applicationId);
    if (businessFormShell && localBackup?.businessInfo) {
      applyBusinessInfoToForm(localBackup.businessInfo);
      setAutosaveStatus("Loaded your temporary local backup. Please check your connection.", "warning");
      return;
    }
    setAutosaveStatus(error.message || "Unable to load saved draft.", "error");
  }
}

function scheduleBusinessDraftAutosave() {
  if (!businessFormShell || isRestoringDraft) {
    return;
  }
  const applicationId = getCurrentApplicationId();
  if (!applicationId) {
    return;
  }
  window.clearTimeout(autosaveTimer);
  setAutosaveStatus("Saving...", "saving");
  autosaveTimer = window.setTimeout(() => {
    void saveBusinessDraft();
  }, AUTOSAVE_DEBOUNCE_MS);
}

async function saveBusinessDraft() {
  const applicationId = getCurrentApplicationId();
  if (!businessFormShell || !applicationId) {
    return;
  }

  const businessInfo = createBusinessInfoPayload(collectBusinessApplication());
  try {
    const payload = await applicantApi(`/applicant/api/applications/${encodeURIComponent(applicationId)}/draft`, {
      method: "PATCH",
      body: JSON.stringify({
        businessInfo,
        currentStep: isBusinessReviewStepVisible() ? "Review Application" : "Business Information",
      }),
    });
    clearDraftBackup(applicationId);
    setAutosaveStatus(`Auto-saved at ${formatApplicantTime(payload.savedAt || new Date().toISOString())}`, "saved");
  } catch (error) {
    writeDraftBackup(applicationId, businessInfo);
    setAutosaveStatus("Unable to auto-save. A temporary backup is stored on this device.", "error");
  }
}

async function renderRecentPermits() {
  if (!recentPermitsTableBody) {
    return;
  }

  const client = initSupabase();
  let permits = [];

  if (client && currentUser) {
    try {
      const { data, error } = await client
        .from("applications")
        .select("id,status,progress,submitted_at,created_at,business_info,permit_snapshot")
        .eq("applicant_id", currentUser.id)
        .order("created_at", { ascending: false })
        .limit(10);

      if (!error && Array.isArray(data) && data.length) {
        permits = data;
      }
    } catch {
      permits = [];
    }
  }

  if (!permits.length) {
    permits = readStoredPermits();
  }

  recentPermitsTableBody.innerHTML = "";

  if (!permits.length) {
    recentPermitsTableBody.innerHTML =
      '<tr><td colspan="6" class="empty-state">No recent business permits yet.</td></tr>';
    return;
  }

  permits.forEach((permit) => {
    const businessInfo = permit.business_info || permit.application_payload || {};
    const permitSnapshot = permit.permit_snapshot || {};
    const referenceNumber = permit.permit_id || permit.permitId || permitSnapshot.permitCode || permitSnapshot.permit_code || permit.id || "-";
    const submittedId = permit.submitted_id || permit.submittedId || (permit.id ? permit.id.slice(0, 8) : "-");
    const status = permit.status || "Draft";
    const pickupOnlyStatuses = ["Permit Ready for Release", "For Pickup", "Released"];
    const actionMarkup = status === "Draft"
      ? `<button class="table-link-button" type="button" data-continue-draft="${escapeHtml(permit.id || "")}" data-draft-permit="${escapeHtml(permit.permit_id || permit.permitId || "")}">Continue</button>`
      : pickupOnlyStatuses.includes(status)
      ? '<span style="color: var(--green); font-weight: 700;">Claim at BPLO Office</span>'
      : `<button class="table-link-button" type="button" data-view-progress="${escapeHtml(permit.id || "")}">View Status</button>`;
    const row = document.createElement("tr");
    row.innerHTML = `
      <td>${referenceNumber}</td>
      <td>${businessInfo.business_name || businessInfo.businessName || permit.business_name || permit.businessName || "-"}</td>
      <td>${status}</td>
      <td>${permit.progress || "Draft"}</td>
      <td>${submittedId}</td>
      <td>${actionMarkup}</td>
    `;
    recentPermitsTableBody.appendChild(row);
  });

  await loadApplicantProgressForDashboard(permits);
}

async function recordApplicantAudit(action, details = {}, entityType = "", entityId = "") {
  try {
    const client = initSupabase();
    const { data } = await client.auth.getSession();
    const session = data.session;

    if (!session?.access_token) {
      return;
    }

    await fetch("/api/audit-logs", {
      method: "POST",
      headers: {
        "Authorization": `Bearer ${session.access_token}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        action,
        details,
        entityType,
        entityId,
      }),
    });
  } catch {
    // Audit failures should not block applicant workflows.
  }
}

function handleBusinessContinue() {
  if (!businessFormShell) {
    return;
  }

  const application = collectBusinessApplication();
  if (!application.businessClassificationId) {
    setBusinessClassificationStatus("Please select a valid business classification.", true);
  }
  updateReviewCopy(application);
  setBusinessStep("review");
}

async function handleFinishApplication() {
  const application = collectBusinessApplication();
  const businessInfo = createBusinessInfoPayload(application);
  const missingFields = getMissingBusinessFields(application);
  const currentApplicationId = getCurrentApplicationId();

  updateReviewCopy(application);

  if (!currentApplicationId) {
    alert("Application session is missing. Please start the application again.");
    return;
  }

  if (missingFields.length) {
    if (!application.businessClassificationId) {
      setBusinessClassificationStatus("Please select a valid business classification.", true);
    }
    setBusinessStep("review");
    alert(`Please complete the required information before submitting:\n\n${missingFields.join("\n")}`);
    return;
  }

  if (!application.businessClassificationId) {
    setBusinessClassificationStatus("Please select a valid business classification.", true);
    alert("Please select a valid business classification.");
    return;
  }

  try {
    const result = await applicantApi("/applicant/api/submit-application", {
      method: "POST",
      body: JSON.stringify({
        application_id: currentApplicationId,
        business_info: businessInfo,
      }),
    });

    const permits = readStoredPermits();
    const record = createPermitRecord(application, currentUser?.id || "");
    permits.unshift(record);
    writeStoredPermits(permits.slice(0, 10));

    await recordApplicantAudit(
      "business_permit_submitted",
      { applicationId: currentApplicationId, businessName: businessInfo.business_name },
      "application",
      currentApplicationId
    );
    clearDraftBackup(currentApplicationId);
    await showApplicationSuccessModal(result.message || "Application submitted successfully.");
    window.location.href = "/applicant/dashboard";
  } catch (error) {
    alert(error.message || "Failed to submit application.");
  }
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

  const profilePayload = await applicantApi("/api/me/profile");
  const accessProfile = profilePayload.profile || {};
  currentAccessProfile = accessProfile;
  if (accessProfile.status !== "active") {
    alert(`This account is ${accessProfile.status}. Please contact the administrator.`);
    await client.auth.signOut();
    window.location.href = "/login";
    return;
  }
  if (accessProfile.role !== "applicant") {
    alert("This dashboard is only for applicant accounts.");
    window.location.href = profilePayload.redirectPath || "/login";
    return;
  }

  currentUser = user;

  const { data: profile, error: applicantProfileError } = await client
    .from("applicants")
    .select("*")
    .eq("user_id", user.id)
    .maybeSingle();

  currentApplicantProfile = profile || null;
  applicantProfileLoadError = applicantProfileError?.message || "";

  const fullName = formatFullName(profile, user) || "Applicant";
  setField("fullName", fullName);
  setField("email", profile?.email || user.email || "");
  setField("contact", profile?.contact_number || user.user_metadata?.contact_number || "");
  setField("address", formatAddress(profile, user));

  if (profileName) {
    profileName.textContent = fullName;
  }

  await renderRecentPermits();
  await recordApplicantAudit(
    "page_view",
    { path: window.location.pathname, title: document.title },
    "page",
    window.location.pathname
  );
}

profileToggle?.addEventListener("click", () => {
  profileDropdown?.classList.toggle("is-open");
  notificationDropdown?.classList.remove("is-open");
});

notificationToggle?.addEventListener("click", () => {
  notificationDropdown?.classList.toggle("is-open");
  profileDropdown?.classList.remove("is-open");
  void loadApplicantNotifications();
});

markAllNotificationsReadButton?.addEventListener("click", (event) => {
  event.stopPropagation();
  void markAllNotificationsRead();
});

document.addEventListener("click", (event) => {
  const clickedElement = event.target instanceof HTMLElement ? event.target : null;

  const startPermitButton = clickedElement?.closest("[data-start-permit]");
  if (startPermitButton instanceof HTMLElement) {
    const permitId = startPermitButton.dataset.startPermit || "";
    void startPermitApplication(permitId);
    return;
  }

  const continueDraftButton = clickedElement?.closest("[data-continue-draft]");
  if (continueDraftButton instanceof HTMLElement) {
    continueDraftApplication(continueDraftButton.dataset.continueDraft || "", continueDraftButton.dataset.draftPermit || "");
    return;
  }

  const viewProgressButton = clickedElement?.closest("[data-view-progress]");
  if (viewProgressButton instanceof HTMLElement) {
    const applicationId = viewProgressButton.dataset.viewProgress || "";
    if (applicationId) {
      void applicantApi(`/applicant/api/applications/${encodeURIComponent(applicationId)}/progress`)
        .then(renderApplicantProgress)
        .then(() => progressPanel?.scrollIntoView({ behavior: "smooth", block: "start" }))
        .catch((error) => alert(error.message || "Unable to load application status."));
    }
    return;
  }

  const uploadTrigger = clickedElement?.closest("[data-upload-trigger]");
  if (uploadTrigger instanceof HTMLElement) {
    const documentId = uploadTrigger.dataset.uploadTrigger || "";
    const input = document.querySelector(`[data-file-input="${CSS.escape(documentId)}"]`);
    input?.click();
    return;
  }

  const removeUploadButton = clickedElement?.closest("[data-remove-upload]");
  if (removeUploadButton instanceof HTMLElement) {
    void removeChecklistUpload(removeUploadButton.dataset.removeUpload || "");
    return;
  }

  const notificationItem = clickedElement?.closest("[data-notification-id]");
  if (notificationItem instanceof HTMLElement) {
    void markNotificationRead(notificationItem.dataset.notificationId || "");
    return;
  }

  const target = event.target;
  if (target instanceof Node) {
    if (profileDropdown?.classList.contains("is-open") && !profileDropdown.contains(target) && !profileToggle?.contains(target)) {
      profileDropdown.classList.remove("is-open");
    }

    if (
      notificationDropdown?.classList.contains("is-open") &&
      !notificationDropdown.contains(target) &&
      !notificationToggle?.contains(target)
    ) {
      notificationDropdown.classList.remove("is-open");
    }
  }
});

document.addEventListener("change", (event) => {
  const target = event.target;
  if (target instanceof HTMLInputElement && target.matches("[data-file-input]")) {
    void handleChecklistFileSelected(target);
  }
});

logoutButton?.addEventListener("click", async () => {
  const confirmed = window.BPLOLogoutModal?.confirm
    ? await window.BPLOLogoutModal.confirm()
    : true;
  if (!confirmed) {
    return;
  }

  const client = initSupabase();
  await recordApplicantAudit("logout", { path: window.location.pathname }, "session");
  await client?.auth.signOut();
  window.location.href = "/login";
});

businessContinueButton?.addEventListener("click", handleBusinessContinue);
finishApplicationButton?.addEventListener("click", () => {
  void handleFinishApplication();
});
document.querySelectorAll("[data-history-back]").forEach((link) => {
  link.addEventListener("click", handleHistoryBack);
});

businessFormShell?.addEventListener("input", (event) => {
  markBusinessFieldTouched(event.target);
  scheduleBusinessDraftAutosave();
});

businessFormShell?.addEventListener("change", (event) => {
  markBusinessFieldTouched(event.target);
  scheduleBusinessDraftAutosave();
});

requirementsNextButton?.addEventListener("click", () => {
  updateRequirementsNextState();
  if (!requirementsNextButton.disabled) {
    redirectToBusinessInformationForm();
  }
});

window.addEventListener("DOMContentLoaded", () => {
  window.lucide?.createIcons();
  if (enforceBusinessPermitTypeSelection()) {
    return;
  }
  syncBusinessPermitType();
  initializeBusinessClassificationCombobox();

  loadApplicantDashboard().then(async () => {
    void loadActivePermits();
    await loadRequirementsChecklist();
    await loadApplicantDrafts();
    void loadApplicantNotifications();
    if (notificationMenu) {
      window.setInterval(() => {
        void loadApplicantNotifications();
      }, 60000);
    }
    applyTodayApplicationDate();
    await loadApplicantProfileIntoBusinessForm();
    applyOcrFieldsToBusinessForm();
    await loadOcrFieldsIntoBusinessForm(getCurrentApplicationId());
    await loadDraftIntoBusinessForm();
  });
});
