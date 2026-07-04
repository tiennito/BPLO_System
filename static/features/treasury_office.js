const SUPABASE_URL = window.APP_CONFIG?.supabaseUrl || "";
const SUPABASE_ANON_KEY =
  window.APP_CONFIG?.supabaseAnonKey || window.APP_CONFIG?.supabasePublishableKey || "";

let supabaseClient = null;
let session = null;
let recordCache = [];
let selectedRecordId = "";
let paymentDetailsRecordId = "";
let receiptModalRecordId = "";
let printConfirmationRecordId = "";

function initSupabase() {
  if (!window.supabase?.createClient) return null;
  if (!supabaseClient) supabaseClient = window.supabase.createClient(SUPABASE_URL, SUPABASE_ANON_KEY);
  return supabaseClient;
}

function setStatus(message, isError = false) {
  const node = document.querySelector("[data-status]");
  if (!node) return;
  node.textContent = message;
  node.style.color = isError ? "#b42318" : "#667085";
}

function normalizeRole(value) {
  const role = String(value || "").trim().toLowerCase().replace(/[-\s]+/g, "_");
  return { treasury_office: "treasury", treasury_user: "treasury" }[role] || role;
}

function escapeHtml(value) {
  return String(value ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&#039;");
}

function money(value) {
  return `₱ ${Number(value || 0).toLocaleString("en-PH", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function moneyAscii(value) {
  return `PHP ${Number(value || 0).toLocaleString("en-PH", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function statusClass(value) {
  return `status-${String(value || "pending").toLowerCase().replace(/[^a-z0-9]+/g, "-")}`;
}

async function apiFetch(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {
      "Authorization": `Bearer ${session.access_token}`,
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
  });
  const result = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(result.error || "Request failed.");
  return result;
}

async function requireTreasurySession() {
  const client = initSupabase();
  if (!client) throw new Error("Supabase client is unavailable.");
  const { data } = await client.auth.getSession();
  session = data.session;
  if (!session) {
    window.location.assign("/login");
    return false;
  }
  const profilePayload = await apiFetch("/api/me/profile");
  const accessProfile = profilePayload.profile || {};
  const role = normalizeRole(accessProfile.role);
  if (accessProfile.status !== "active") {
    setStatus(`This account is ${accessProfile.status} and cannot access the dashboard.`, true);
    return false;
  }
  if (role !== "treasury") {
    setStatus("This account is signed in, but it is not a Treasury account.", true);
    console.debug("[auth] treasury guard rejected", {
      authUserId: accessProfile.authUserId,
      role,
    });
    return false;
  }
  const profile = await apiFetch("/treasury/api/me");
  console.debug("[auth] treasury profile", profile.user);
  document.querySelectorAll("[data-user-name]").forEach((node) => {
    node.textContent = profile.user?.name || "Treasury Staff";
  });
  return true;
}

function renderCounts(counts) {
  const values = {
    totalCollections: money(counts.totalCollections || 0),
    assessmentReview: counts.assessmentReview || 0,
    readyForPayment: counts.readyForPayment || 0,
    receiptsIssued: counts.receiptsIssued || 0,
  };
  Object.entries(values).forEach(([key, value]) => {
    document.querySelectorAll(`[data-count="${key}"]`).forEach((node) => {
      node.textContent = value;
    });
  });
  renderProcessingAmounts();
}

function renderRows() {
  const payments = document.querySelector("[data-payment-table]");
  const processing = document.querySelector("[data-processing-table]");
  if (!payments || !processing) return;
  const rows = recordCache.slice(0, 5);
  payments.innerHTML = rows.length ? rows.map((record) => `
    <tr>
      <td>${escapeHtml(record.orNo || "-")}</td>
      <td>${escapeHtml(record.applicant)}</td>
      <td>${escapeHtml(record.businessName)}</td>
      <td>${money(record.amount)}</td>
      <td><span class="step-pill">${escapeHtml(record.step)}</span></td>
      <td><span class="status-pill ${statusClass(record.status)}">${escapeHtml(record.status)}</span></td>
      <td>${escapeHtml(record.transactionDate || "-")}</td>
    </tr>
  `).join("") : '<tr><td colspan="7">No payment records yet.</td></tr>';

  processing.innerHTML = rows.length ? rows.map((record) => `
    <tr>
      <td>${escapeHtml(record.applicationNo)}</td>
      <td>${escapeHtml(record.applicant)}</td>
      <td>${escapeHtml(record.businessName)}</td>
      <td>${money(record.amount)}</td>
      <td><span class="step-pill">${escapeHtml(record.currentStep)}</span></td>
      <td><span class="status-pill ${statusClass(record.status)}">${escapeHtml(record.status)}</span></td>
      <td><button class="action-button" type="button" data-edit-record="${record.id}">${record.status === "Paid" ? "View" : "Process"}</button> <button class="action-button" type="button" data-delete-record="${record.id}">Delete</button></td>
    </tr>
  `).join("") : '<tr><td colspan="7">No treasury queue records yet.</td></tr>';
}

function soaStatus(record) {
  if (record.currentStep === "SOA Generation" && record.status === "Ready") return "Ready";
  if (["Payment", "Official Receipt"].includes(record.currentStep) || ["Generated", "Paid", "Accepted"].includes(record.status)) return "Generated";
  return "Not Generated";
}

function paymentStatus(record) {
  if (record.status === "Paid") return "Paid";
  if (record.currentStep === "Payment" || record.status === "Pending") return "Pending";
  return "Not Paid";
}

function orStatus(record) {
  if (record.currentStep === "Official Receipt" && record.status === "Ready") return "Ready";
  if (record.status === "Paid" || record.status === "Accepted") return "Issued";
  return "Not Issued";
}

function getIssuedReceiptRecords() {
  return recordCache.filter((record) => {
    return Boolean(record.orNo) || orStatus(record) === "Issued" || record.currentStep === "Official Receipt";
  });
}

function soaNumber(record) {
  const applicationNo = String(record?.applicationNo || "").trim();
  if (!applicationNo) {
    return "SOA-000000";
  }
  if (applicationNo.includes("APP")) {
    return applicationNo.replace("APP", "SOA");
  }
  return `SOA-${applicationNo}`;
}

function actionLabel(record) {
  if (record.currentStep === "Assessment") return "View Assessment";
  if (record.currentStep === "SOA Generation") return "Generate SOA";
  if (record.currentStep === "Payment" && record.status === "Pending") return "Accept Payment";
  if (record.currentStep === "Payment") return "Verify Payment";
  if (record.currentStep === "Official Receipt") return record.status === "Ready" ? "Issue OR" : "View OR";
  return "Process";
}

function nextProcessMeta(record) {
  if (record.currentStep === "Assessment") {
    return { label: "Next Process", nextStep: "SOA Generation", target: "/treasury/processing", message: "This will move the transaction to SOA Generation." };
  }
  if (record.currentStep === "SOA Generation") {
    return { label: "Next Process", nextStep: "Payment", target: "/treasury/payment-records", message: "This will move the transaction into Payment processing." };
  }
  if (record.currentStep === "Payment") {
    return { label: "Next Process", nextStep: "Official Receipt", target: `/treasury/official-receipts?id=${encodeURIComponent(record.id || "")}`, message: "This will save the payment progress and route the transaction to Official Receipts." };
  }
  if (record.currentStep === "Official Receipt" && record.status !== "Accepted") {
    return { label: "Next Process", nextStep: "Completed", target: `/treasury/official-receipts?id=${encodeURIComponent(record.id || "")}`, message: "This will finalize the official receipt workflow for this transaction." };
  }
  return { label: "Workflow Complete", nextStep: "Completed", target: `/treasury/official-receipts?id=${encodeURIComponent(record.id || "")}`, message: "This transaction is already at the final workflow stage. Click to open its official receipt." };
}

function renderProcessingAmounts() {
  const groups = {
    assessment: recordCache.filter((record) => record.currentStep === "Assessment"),
    soa: recordCache.filter((record) => record.currentStep === "SOA Generation"),
    payment: recordCache.filter((record) => record.currentStep === "Payment"),
    receipt: recordCache.filter((record) => record.currentStep === "Official Receipt"),
  };
  Object.entries(groups).forEach(([key, rows]) => {
    document.querySelectorAll(`[data-processing-amount="${key}"]`).forEach((node) => {
      node.textContent = money(rows.reduce((sum, record) => sum + Number(record.amount || 0), 0));
    });
  });
  document.querySelectorAll('[data-count="soaReady"]').forEach((node) => {
    node.textContent = groups.soa.length;
  });
}

function getFilteredProcessingRecords() {
  const search = (document.querySelector("[data-processing-search]")?.value || "").toLowerCase();
  const step = document.querySelector("[data-step-filter]")?.value || "";
  const status = document.querySelector("[data-processing-status-filter]")?.value || "";
  return recordCache.filter((record) => {
    const haystack = `${record.applicationNo} ${record.applicant} ${record.businessName}`.toLowerCase();
    return haystack.includes(search) && (!step || record.currentStep === step) && (!status || [record.status, soaStatus(record), paymentStatus(record), orStatus(record)].includes(status));
  });
}

function renderProcessingQueue(records = getFilteredProcessingRecords()) {
  const table = document.querySelector("[data-processing-queue]");
  if (!table) return;
  if (!records.length) {
    table.innerHTML = '<tr><td colspan="9">No processing records found.</td></tr>';
    document.querySelector("[data-processing-entry-count]").textContent = "Showing 0 entries";
    renderSelectedTransaction(null);
    return;
  }
  selectedRecordId = selectedRecordId || records[0].id;
  table.innerHTML = records.map((record) => `
    <tr class="${record.id === selectedRecordId ? "is-selected" : ""}">
      <td>${escapeHtml(record.applicationNo)}</td>
      <td>${escapeHtml(record.applicant)}</td>
      <td>${escapeHtml(record.businessName)}</td>
      <td>${money(record.amount)}</td>
      <td><span class="step-pill">${escapeHtml(record.currentStep)}</span></td>
      <td><span class="status-pill ${statusClass(soaStatus(record))}">${escapeHtml(soaStatus(record))}</span></td>
      <td><span class="status-pill ${statusClass(paymentStatus(record))}">${escapeHtml(paymentStatus(record))}</span></td>
      <td><span class="status-pill ${statusClass(orStatus(record))}">${escapeHtml(orStatus(record))}</span></td>
      <td><button class="action-button" type="button" data-process-record="${record.id}">${escapeHtml(actionLabel(record))}</button></td>
    </tr>
  `).join("");
  document.querySelector("[data-processing-entry-count]").textContent = `Showing 1 to ${records.length} of ${recordCache.length} entries`;
  renderSelectedTransaction(records.find((record) => record.id === selectedRecordId) || records[0]);
}

function getFilteredPaymentRecords() {
  const search = (document.querySelector("[data-payment-search]")?.value || "").toLowerCase();
  const status = document.querySelector("[data-payment-status-filter]")?.value || "";
  const method = document.querySelector("[data-payment-method-filter]")?.value || "";
  return recordCache.filter((record) => {
    const paymentMethod = record.paymentMethod || record.method || "";
    const haystack = `${record.orNo} ${record.applicant} ${record.businessName}`.toLowerCase();
    return haystack.includes(search) && (!status || record.status === status) && (!method || paymentMethod === method);
  });
}

function renderPaymentCounts(records = recordCache) {
  const verified = records.filter((record) => ["Verified", "Paid"].includes(record.status));
  const pending = records.filter((record) => record.status === "Pending");
  const collections = records.reduce((sum, record) => sum + Number(record.amount || 0), 0);
  const values = {
    totalPayments: moneyAscii(collections),
    verifiedPayments: verified.length,
    pendingVerification: pending.length,
    totalCollections: moneyAscii(collections),
  };
  Object.entries(values).forEach(([key, value]) => {
    document.querySelectorAll(`[data-payment-count="${key}"]`).forEach((node) => {
      node.textContent = value;
    });
  });
}

function renderPaymentRecords(records = getFilteredPaymentRecords()) {
  const table = document.querySelector("[data-payment-records-table]");
  if (!table) return;
  renderPaymentCounts(records);
  if (!records.length) {
    table.innerHTML = '<tr><td class="payment-empty-state" colspan="9">No payment records yet.</td></tr>';
    const count = document.querySelector("[data-payment-entry-count]");
    if (count) count.textContent = "Showing 0 entries";
    return;
  }
  table.innerHTML = records.map((record) => `
    <tr>
      <td>${escapeHtml(record.orNo || "-")}</td>
      <td>${escapeHtml(record.transactionDate || "-")}</td>
      <td>${escapeHtml(record.applicant)}</td>
      <td>${escapeHtml(record.businessName)}</td>
      <td>${money(record.amount)}</td>
      <td>${escapeHtml(record.paymentMethod || record.method || "-")}</td>
      <td><span class="status-pill ${statusClass(record.status)}">${escapeHtml(record.status)}</span></td>
      <td>${escapeHtml(record.cashier || "Treasury Staff")}</td>
      <td><button class="action-button" type="button" data-edit-record="${record.id}">View</button></td>
    </tr>
  `).join("");
  const count = document.querySelector("[data-payment-entry-count]");
  if (count) count.textContent = `Showing 1 to ${records.length} of ${recordCache.length} entries`;
}

function getFilteredOfficialReceipts() {
  const search = (document.querySelector("[data-receipt-search]")?.value || "").toLowerCase();
  const status = document.querySelector("[data-receipt-status-filter]")?.value || "";
  return getIssuedReceiptRecords().filter((record) => {
    const derivedStatus = orStatus(record);
    const haystack = `${record.orNo} ${record.applicant} ${record.businessName}`.toLowerCase();
    return haystack.includes(search) && (!status || derivedStatus === status);
  });
}

function getRequestedRecordId() {
  const params = new URLSearchParams(window.location.search);
  return (params.get("id") || "").trim();
}

function renderOfficialReceipts(records = getFilteredOfficialReceipts()) {
  const table = document.querySelector("[data-receipts-table]");
  if (!table) return;
  const issuedRecords = getIssuedReceiptRecords();
  const today = new Date().toISOString().slice(0, 10);
  const issuedToday = issuedRecords.filter((record) => record.transactionDate === today).length;
  const currentMonth = today.slice(0, 7);
  const issuedMonth = issuedRecords.filter((record) => (record.transactionDate || "").startsWith(currentMonth)).length;
  const cancelled = issuedRecords.filter((record) => ["Cancelled", "Void"].includes(record.status)).length;
  const receiptCounts = {
    issuedToday,
    issuedMonth,
    reprinted: 0,
    cancelled,
  };
  Object.entries(receiptCounts).forEach(([key, value]) => {
    document.querySelectorAll(`[data-receipt-count="${key}"]`).forEach((node) => {
      node.textContent = value;
    });
  });
  if (!records.length) {
    table.innerHTML = '<tr><td class="payment-empty-state" colspan="8">No official receipts yet.</td></tr>';
    const count = document.querySelector("[data-receipt-entry-count]");
    if (count) count.textContent = "Showing 0 entries";
    const details = document.querySelector("[data-receipt-details]");
    if (details) {
      details.innerHTML = '<i data-lucide="receipt-text"></i><strong>No receipt selected</strong><p>Receipt details will appear here after records are available.</p><button class="action-button" type="button" disabled>View Full Receipt</button>';
    }
    window.lucide?.createIcons();
    return;
  }
  table.innerHTML = records.map((record) => `
    <tr>
      <td>${escapeHtml(record.orNo || "-")}</td>
      <td>${escapeHtml(record.applicant)}</td>
      <td>${escapeHtml(record.businessName)}</td>
      <td>${escapeHtml(record.transactionDate || "-")}</td>
      <td>${money(record.amount)}</td>
      <td><span class="status-pill ${statusClass(orStatus(record))}">${escapeHtml(orStatus(record))}</span></td>
      <td>${escapeHtml(record.cashier || "Treasury Staff")}</td>
      <td><button class="action-button" type="button" data-view-receipt="${record.id}">View</button></td>
    </tr>
  `).join("");
  const count = document.querySelector("[data-receipt-entry-count]");
  if (count) count.textContent = `Showing 1 to ${records.length} of ${issuedRecords.length} entries`;
  const details = document.querySelector("[data-receipt-details]");
  if (details) {
    const requestedId = getRequestedRecordId();
    const selected = records.find((record) => record.id === requestedId)
      || records.find((record) => record.id === selectedRecordId)
      || records[0];
    selectedRecordId = selected.id;
    details.innerHTML = `
      <div class="selected-detail-grid">
        <div class="selected-detail"><span>OR No.</span><strong>${escapeHtml(selected.orNo || "-")}</strong></div>
        <div class="selected-detail"><span>Applicant</span><strong>${escapeHtml(selected.applicant)}</strong></div>
        <div class="selected-detail"><span>Business Name</span><strong>${escapeHtml(selected.businessName)}</strong></div>
        <div class="selected-detail"><span>Payment Date</span><strong>${escapeHtml(selected.transactionDate || "-")}</strong></div>
        <div class="selected-detail"><span>Amount</span><strong>${money(selected.amount)}</strong></div>
        <div class="selected-detail"><span>Receipt Status</span><strong>${escapeHtml(orStatus(selected))}</strong></div>
        <div class="selected-detail wide"><button class="action-button" type="button" data-edit-record="${selected.id}">View Full Receipt</button></div>
      </div>
    `;
  }
  window.lucide?.createIcons();
}

function getFilteredTreasuryReports() {
  const search = (document.querySelector("[data-report-search]")?.value || "").toLowerCase();
  const type = document.querySelector("[data-report-type-filter]")?.value || "";
  const status = document.querySelector("[data-report-status-filter]")?.value || "";
  const derived = recordCache.map((record) => ({
    id: `RPT-${record.applicationNo || record.id || ""}`,
    reportType: record.currentStep === "Official Receipt"
      ? "Official Receipts Report"
      : record.currentStep === "Payment"
        ? "Payment Summary"
        : record.currentStep === "SOA Generation"
          ? "Treasury Transactions"
          : "Collection Summary",
    coveredPeriod: record.transactionDate || record.createdAt?.slice(0, 10) || "-",
    totalAmount: Number(record.amount || 0),
    status: ["Paid", "Accepted"].includes(record.status) ? "Completed" : ["Ready", "Generated"].includes(record.status) ? "Processing" : "Pending",
    generatedBy: "Treasury Staff",
    generatedOn: record.createdAt ? record.createdAt.slice(0, 10) : (record.transactionDate || "-"),
    sourceId: record.id,
  }));
  return derived.filter((report) => {
    const haystack = `${report.id} ${report.generatedBy}`.toLowerCase();
    return haystack.includes(search) && (!type || report.reportType === type) && (!status || report.status === status);
  });
}

function renderTreasuryReports(records = getFilteredTreasuryReports()) {
  const table = document.querySelector("[data-reports-table]");
  if (!table) return;
  const totalCollections = recordCache
    .filter((record) => record.status === "Paid" || record.status === "Accepted")
    .reduce((sum, record) => sum + Number(record.amount || 0), 0);
  const values = {
    collections: moneyAscii(totalCollections),
    transactions: recordCache.length,
    receipts: getIssuedReceiptRecords().length,
    pending: recordCache.filter((record) => ["Pending", "Ready"].includes(record.status)).length,
  };
  Object.entries(values).forEach(([key, value]) => {
    document.querySelectorAll(`[data-report-count="${key}"]`).forEach((node) => {
      node.textContent = value;
    });
  });
  if (!records.length) {
    table.innerHTML = '<tr><td class="payment-empty-state" colspan="8">No treasury reports yet.</td></tr>';
    const count = document.querySelector("[data-report-entry-count]");
    if (count) count.textContent = "Showing 0 entries";
    window.lucide?.createIcons();
    return;
  }
  table.innerHTML = records.map((report) => `
    <tr>
      <td>${escapeHtml(report.id)}</td>
      <td>${escapeHtml(report.reportType)}</td>
      <td>${escapeHtml(report.coveredPeriod)}</td>
      <td>${moneyAscii(report.totalAmount)}</td>
      <td><span class="status-pill ${statusClass(report.status)}">${escapeHtml(report.status)}</span></td>
      <td>${escapeHtml(report.generatedBy)}</td>
      <td>${escapeHtml(report.generatedOn)}</td>
      <td><button class="action-button" type="button" data-edit-record="${report.sourceId}">View</button></td>
    </tr>
  `).join("");
  const count = document.querySelector("[data-report-entry-count]");
  if (count) count.textContent = `Showing 1 to ${records.length} of ${records.length} entries`;
  window.lucide?.createIcons();
}

function renderSelectedTransaction(record) {
  const node = document.querySelector("[data-selected-transaction]");
  if (!node) return;
  if (!record) {
    node.innerHTML = "<p>Select a transaction to view details.</p>";
    return;
  }
  selectedRecordId = record.id;
  node.innerHTML = `
    <div class="selected-detail-grid">
      <div class="selected-detail"><span>Application No.</span><strong>${escapeHtml(record.applicationNo)}</strong></div>
      <div class="selected-detail"><span>Business Name</span><strong>${escapeHtml(record.businessName)}</strong></div>
      <div class="selected-detail"><span>Applicant</span><strong>${escapeHtml(record.applicant)}</strong></div>
      <div class="selected-detail"><span>Current Step</span><strong>${escapeHtml(record.currentStep)}</strong></div>
      <div class="selected-detail"><span>SOA No.</span><strong>${escapeHtml(record.applicationNo.replace("APP", "SOA"))}</strong></div>
      <div class="selected-detail"><span>SOA Status</span><strong>${escapeHtml(soaStatus(record))}</strong></div>
      <div class="selected-detail"><span>Amount Due</span><strong>${money(record.amount)}</strong></div>
      <div class="selected-detail"><span>Payment Status</span><strong>${escapeHtml(paymentStatus(record))}</strong></div>
      <div class="selected-detail"><span>Payment Amount</span><strong>${record.status === "Paid" ? money(record.amount) : "PHP 0.00"}</strong></div>
      <div class="selected-detail"><span>Payment Date</span><strong>${escapeHtml(record.status === "Paid" ? record.transactionDate : "-")}</strong></div>
      <div class="selected-detail"><span>Official Receipt Status</span><strong>${escapeHtml(orStatus(record))}</strong></div>
      <div class="selected-detail"><span>OR No.</span><strong>${escapeHtml(record.orNo || "-")}</strong></div>
      <div class="selected-detail wide"><button class="action-button" type="button" data-edit-record="${record.id}">View Full Details</button></div>
    </div>
  `;
}

function setPaymentDetailsModalOpen(isOpen) {
  const modal = document.querySelector("[data-payment-details-modal]");
  if (!modal) return;
  modal.hidden = !isOpen;
  document.body.style.overflow = isOpen ? "hidden" : "";
  if (isOpen) {
    modal.querySelector("[data-close-payment-details]")?.focus();
  }
}

function renderPaymentDetails(record) {
  const body = document.querySelector("[data-payment-details-body]");
  const actionButton = document.querySelector("[data-payment-next-process]");
  if (!body || !actionButton || !record) return;
  paymentDetailsRecordId = record.id;
  const meta = nextProcessMeta(record);
  body.innerHTML = `
    <div class="payment-details-grid">
      <article class="payment-detail-card"><span>OR No.</span><strong>${escapeHtml(record.orNo || "-")}</strong></article>
      <article class="payment-detail-card"><span>Application No.</span><strong>${escapeHtml(record.applicationNo || "-")}</strong></article>
      <article class="payment-detail-card"><span>Applicant</span><strong>${escapeHtml(record.applicant || "-")}</strong></article>
      <article class="payment-detail-card"><span>Business Name</span><strong>${escapeHtml(record.businessName || "-")}</strong></article>
      <article class="payment-detail-card"><span>Amount</span><strong>${money(record.amount)}</strong></article>
      <article class="payment-detail-card"><span>Payment Method</span><strong>${escapeHtml(record.paymentMethod || record.method || "-")}</strong></article>
      <article class="payment-detail-card"><span>Current Step</span><strong>${escapeHtml(record.currentStep || "-")}</strong></article>
      <article class="payment-detail-card"><span>Status</span><strong>${escapeHtml(record.status || "-")}</strong></article>
      <article class="payment-detail-card"><span>Payment Date</span><strong>${escapeHtml(record.transactionDate || "-")}</strong></article>
      <article class="payment-detail-card"><span>Cashier</span><strong>${escapeHtml(record.cashier || "Treasury Staff")}</strong></article>
      <article class="payment-detail-card wide"><span>Remarks</span><p>${escapeHtml(record.remarks || "No remarks recorded.")}</p></article>
    </div>
    <section class="payment-process-note">
      <i data-lucide="arrow-right-circle"></i>
      <div>
        <strong>Next Stage: ${escapeHtml(meta.nextStep)}</strong>
        <p>${escapeHtml(meta.message)}</p>
      </div>
    </section>
  `;
  actionButton.textContent = meta.label;
  actionButton.disabled = Boolean(meta.disabled);
  actionButton.dataset.target = meta.target;
  window.lucide?.createIcons();
}

function openPaymentDetails(record) {
  if (!record) return;
  renderPaymentDetails(record);
  setPaymentDetailsModalOpen(true);
}

function setReceiptModalOpen(isOpen) {
  const modal = document.querySelector("[data-receipt-modal]");
  if (!modal) return;
  modal.hidden = !isOpen;
  document.body.style.overflow = isOpen ? "hidden" : "";
  if (isOpen) {
    modal.querySelector("[data-close-receipt-modal]")?.focus();
  }
}

function setPrintConfirmationModalOpen(isOpen) {
  const modal = document.querySelector("[data-print-confirmation-modal]");
  if (!modal) return;
  modal.hidden = !isOpen;
  document.body.style.overflow = isOpen ? "hidden" : "";
  if (isOpen) {
    modal.querySelector("[data-close-print-confirmation]")?.focus();
  }
}

function renderReceiptModal(record) {
  const body = document.querySelector("[data-receipt-modal-body]");
  if (!body || !record) return;
  receiptModalRecordId = record.id;
  body.innerHTML = `
    <div class="payment-details-grid">
      <article class="payment-detail-card"><span>OR No.</span><strong>${escapeHtml(record.orNo || "-")}</strong></article>
      <article class="payment-detail-card"><span>SOA No.</span><strong>${escapeHtml(soaNumber(record))}</strong></article>
      <article class="payment-detail-card"><span>Application No.</span><strong>${escapeHtml(record.applicationNo || "-")}</strong></article>
      <article class="payment-detail-card"><span>Applicant</span><strong>${escapeHtml(record.applicant || "-")}</strong></article>
      <article class="payment-detail-card"><span>Business Name</span><strong>${escapeHtml(record.businessName || "-")}</strong></article>
      <article class="payment-detail-card"><span>Payment Date</span><strong>${escapeHtml(record.transactionDate || "-")}</strong></article>
      <article class="payment-detail-card"><span>Amount</span><strong>${money(record.amount)}</strong></article>
      <article class="payment-detail-card"><span>Receipt Status</span><strong>${escapeHtml(orStatus(record))}</strong></article>
      <article class="payment-detail-card"><span>Issued By</span><strong>${escapeHtml(record.cashier || "Treasury Staff")}</strong></article>
      <article class="payment-detail-card"><span>Current Step</span><strong>${escapeHtml(record.currentStep || "-")}</strong></article>
      <article class="payment-detail-card wide"><span>Remarks</span><p>${escapeHtml(record.remarks || "No remarks recorded.")}</p></article>
    </div>
    <section class="payment-process-note">
      <i data-lucide="badge-check"></i>
      <div>
        <strong>Mark as Paid</strong>
        <p>Set this transaction to paid first, then print the Statement of Account and Official Receipt from the confirmation modal.</p>
      </div>
    </section>
  `;
  window.lucide?.createIcons();
}

function openReceiptModal(record) {
  if (!record) return;
  renderReceiptModal(record);
  setReceiptModalOpen(true);
}

function printReceiptBundle(record) {
  if (!record) {
    setStatus("Unable to find the selected receipt for printing.", true);
    return false;
  }
  const printWindow = window.open("", "_blank", "width=960,height=780");
  if (!printWindow) {
    setStatus("Allow pop-ups to print the SOA and official receipt.", true);
    return false;
  }
  const html = `<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <title>SOA and Official Receipt</title>
    <style>
      body { font-family: Arial, Helvetica, sans-serif; margin: 28px; color: #0f1b3d; }
      h1, h2 { margin: 0 0 10px; }
      .sheet { margin-bottom: 34px; padding: 22px; border: 1px solid #d7deea; border-radius: 12px; }
      .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
      .card { padding: 12px 14px; border: 1px solid #e5e7eb; border-radius: 10px; background: #fafcff; }
      .card span { display: block; margin-bottom: 6px; color: #667085; font-size: 11px; font-weight: 700; text-transform: uppercase; }
      .card strong, .card p { margin: 0; font-size: 15px; }
      .wide { grid-column: 1 / -1; }
      .amount { color: #0b55e7; }
      @media print { body { margin: 14px; } .sheet { page-break-inside: avoid; } }
    </style>
  </head>
  <body>
    <section class="sheet">
      <h1>Statement of Account</h1>
      <div class="grid">
        <div class="card"><span>SOA No.</span><strong>${escapeHtml(soaNumber(record))}</strong></div>
        <div class="card"><span>Application No.</span><strong>${escapeHtml(record.applicationNo || "-")}</strong></div>
        <div class="card"><span>Applicant</span><strong>${escapeHtml(record.applicant || "-")}</strong></div>
        <div class="card"><span>Business Name</span><strong>${escapeHtml(record.businessName || "-")}</strong></div>
        <div class="card"><span>Assessment Amount</span><strong class="amount">${moneyAscii(record.amount)}</strong></div>
        <div class="card"><span>Payment Date</span><strong>${escapeHtml(record.transactionDate || "-")}</strong></div>
        <div class="card wide"><span>Notes</span><p>${escapeHtml(record.remarks || "Generated from treasury workflow.")}</p></div>
      </div>
    </section>
    <section class="sheet">
      <h2>Official Receipt</h2>
      <div class="grid">
        <div class="card"><span>OR No.</span><strong>${escapeHtml(record.orNo || "-")}</strong></div>
        <div class="card"><span>Receipt Status</span><strong>${escapeHtml(orStatus(record))}</strong></div>
        <div class="card"><span>Applicant</span><strong>${escapeHtml(record.applicant || "-")}</strong></div>
        <div class="card"><span>Business Name</span><strong>${escapeHtml(record.businessName || "-")}</strong></div>
        <div class="card"><span>Amount Paid</span><strong class="amount">${moneyAscii(record.amount)}</strong></div>
        <div class="card"><span>Issued By</span><strong>${escapeHtml(record.cashier || "Treasury Staff")}</strong></div>
        <div class="card"><span>Payment Date</span><strong>${escapeHtml(record.transactionDate || "-")}</strong></div>
        <div class="card"><span>Current Step</span><strong>${escapeHtml(record.currentStep || "-")}</strong></div>
        <div class="card wide"><span>Remarks</span><p>${escapeHtml(record.remarks || "Official receipt generated from payment confirmation.")}</p></div>
      </div>
    </section>
  </body>
</html>`;
  printWindow.document.open();
  printWindow.document.write(html);
  printWindow.document.close();
  printWindow.focus();
  printWindow.print();
  return true;
}

async function notifyReceiptPrintComplete(record) {
  if (!record?.id) {
    throw new Error("Unable to find the selected receipt for notification.");
  }
  return apiFetch(`/treasury/api/records/${encodeURIComponent(record.id)}/print-notify`, {
    method: "POST",
  });
}

async function syncTreasuryCompletion(record) {
  if (!record?.id) {
    throw new Error("Unable to find the selected treasury record.");
  }
  return apiFetch(`/treasury/api/records/${encodeURIComponent(record.id)}/sync-completion`, {
    method: "POST",
  });
}

async function markReceiptAsPaid(record) {
  if (!record?.id) {
    throw new Error("Unable to find the selected receipt.");
  }
  const paidRecord = {
    ...record,
    currentStep: "Official Receipt",
    step: "Official Receipt",
    status: "Paid",
    transactionDate: record.transactionDate || new Date().toISOString().slice(0, 10),
    orNo: record.orNo || `OR-${new Date().getFullYear()}-${String(Math.floor(Math.random() * 99999)).padStart(5, "0")}`,
  };
  await apiFetch(`/treasury/api/records/${encodeURIComponent(record.id)}`, {
    method: "PATCH",
    body: JSON.stringify({
      applicationNo: paidRecord.applicationNo,
      orNo: paidRecord.orNo,
      applicant: paidRecord.applicant,
      businessName: paidRecord.businessName,
      amount: paidRecord.amount,
      step: paidRecord.step,
      currentStep: paidRecord.currentStep,
      status: paidRecord.status,
      transactionDate: paidRecord.transactionDate,
      remarks: paidRecord.remarks || "",
    }),
  });
  await syncTreasuryCompletion(paidRecord);
  await loadRecords();
  return recordCache.find((item) => item.id === record.id) || paidRecord;
}

function renderBars() {
  const node = document.querySelector("[data-bars]");
  if (!node) return;
  const values = [780, 320, 510, 690, 920, 660, 410, 620, 480, 960, 840, 1320, 1310, 1720, 1580, 1130, 690, 980, 740, 1100, Math.max(300, recordCache.reduce((sum, item) => sum + Number(item.amount || 0), 0) / 1000)];
  const max = Math.max(...values);
  node.innerHTML = values.map((value, index) => `<span><em style="height:${Math.max(18, Math.round((value / max) * 150))}px"></em><small>${String(index + 1).padStart(2, "0")}</small></span>`).join("");
}

async function loadRecords() {
  const result = await apiFetch("/treasury/api/records");
  recordCache = result.records || [];
  renderCounts(result.counts || {});
  renderRows();
  renderProcessingQueue();
  renderPaymentRecords();
  renderOfficialReceipts();
  renderTreasuryReports();
  renderBars();
  window.lucide?.createIcons();
  setStatus(document.body.dataset.page === "treasury-settings" ? "Settings loaded." : document.body.dataset.page === "treasury-reports" ? "Treasury reports loaded." : document.body.dataset.page === "official-receipts" ? "Official receipts loaded." : document.body.dataset.page === "payment-records" ? "Payment records loaded." : document.body.dataset.page === "processing" ? "Treasury processing loaded." : "Treasury dashboard loaded.");
}

function fillForm(record) {
  const form = document.querySelector("[data-record-form]");
  if (!form) return;
  form.elements.id.value = record?.id || "";
  form.elements.applicationNo.value = record?.applicationNo || "";
  form.elements.orNo.value = record?.orNo || "";
  form.elements.applicant.value = record?.applicant || "";
  form.elements.businessName.value = record?.businessName || "";
  form.elements.amount.value = record?.amount || "";
  form.elements.step.value = record?.step || "Assessment";
  form.elements.status.value = record?.status || "Pending";
  form.elements.transactionDate.value = record?.transactionDate || new Date().toISOString().slice(0, 10);
  form.elements.remarks.value = record?.remarks || "";
  form.scrollIntoView({ behavior: "smooth", block: "start" });
}

function bindCrud() {
  const form = document.querySelector("[data-record-form]");
  document.querySelector("[data-new-record]")?.addEventListener("click", () => fillForm(null));
  form?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const formData = new FormData(form);
    const id = formData.get("id").toString();
    const payload = {
      applicationNo: formData.get("applicationNo").toString().trim(),
      orNo: formData.get("orNo").toString().trim(),
      applicant: formData.get("applicant").toString().trim(),
      businessName: formData.get("businessName").toString().trim(),
      amount: formData.get("amount").toString(),
      step: formData.get("step").toString(),
      currentStep: formData.get("step").toString(),
      status: formData.get("status").toString(),
      transactionDate: formData.get("transactionDate").toString(),
      remarks: formData.get("remarks").toString().trim(),
    };
    await apiFetch(id ? `/treasury/api/records/${encodeURIComponent(id)}` : "/treasury/api/records", {
      method: id ? "PATCH" : "POST",
      body: JSON.stringify(payload),
    });
    form.reset();
    await loadRecords();
  });
  document.addEventListener("click", async (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) return;
    const receiptId = target.dataset.viewReceipt;
    if (receiptId) {
      const record = recordCache.find((item) => item.id === receiptId);
      selectedRecordId = receiptId;
      renderOfficialReceipts();
      openReceiptModal(record);
      return;
    }
    const editId = target.dataset.editRecord;
    if (editId) {
      const record = recordCache.find((item) => item.id === editId);
      if (document.body.dataset.page === "payment-records") {
        openPaymentDetails(record);
        return;
      }
      fillForm(record);
    }
    const processId = target.dataset.processRecord;
    if (processId) {
      const record = recordCache.find((item) => item.id === processId);
      if (record) {
        const processButton = target.closest("[data-process-record]");
        if (processButton instanceof HTMLButtonElement) {
          processButton.disabled = true;
          processButton.classList.add("is-busy");
          processButton.textContent = "Processing...";
        }
        try {
          await advanceProcessingRecord(record);
        } finally {
          if (processButton instanceof HTMLButtonElement) {
            processButton.disabled = false;
            processButton.classList.remove("is-busy");
          }
        }
      }
    }
    const deleteId = target.dataset.deleteRecord;
    if (deleteId) {
      await apiFetch(`/treasury/api/records/${encodeURIComponent(deleteId)}`, { method: "DELETE" });
      await loadRecords();
    }
  });
}

async function advanceProcessingRecord(record) {
  const next = { ...record };
  if (record.currentStep === "Assessment") {
    next.currentStep = "SOA Generation";
    next.step = "SOA Generation";
    next.status = "Ready";
  } else if (record.currentStep === "SOA Generation") {
    next.currentStep = "Payment";
    next.step = "Payment";
    next.status = "Generated";
  } else if (record.currentStep === "Payment") {
    next.currentStep = "Official Receipt";
    next.step = "Official Receipt";
    next.status = "Paid";
  } else {
    next.status = "Accepted";
  }
  await apiFetch(`/treasury/api/records/${encodeURIComponent(record.id)}`, {
    method: "PATCH",
    body: JSON.stringify({
      applicationNo: next.applicationNo,
      orNo: next.orNo || `OR-${new Date().getFullYear()}-${String(Math.floor(Math.random() * 99999)).padStart(5, "0")}`,
      applicant: next.applicant,
      businessName: next.businessName,
      amount: next.amount,
      step: next.step,
      currentStep: next.currentStep,
      status: next.status,
      transactionDate: next.transactionDate || new Date().toISOString().slice(0, 10),
      remarks: next.remarks || "",
    }),
  });
  if (next.currentStep === "Official Receipt" || next.status === "Accepted") {
    await syncTreasuryCompletion(next);
  }
  selectedRecordId = record.id;
  await loadRecords();
  return next;
}

function bindPaymentDetailsModal() {
  document.querySelectorAll("[data-close-payment-details]").forEach((button) => {
    button.addEventListener("click", () => setPaymentDetailsModalOpen(false));
  });
  document.querySelector("[data-payment-details-modal]")?.addEventListener("click", (event) => {
    if (event.target === event.currentTarget) {
      setPaymentDetailsModalOpen(false);
    }
  });
  document.addEventListener("keydown", (event) => {
    const modal = document.querySelector("[data-payment-details-modal]");
    if (event.key === "Escape" && modal && !modal.hidden) {
      setPaymentDetailsModalOpen(false);
    }
  });
  document.querySelector("[data-payment-next-process]")?.addEventListener("click", async (event) => {
    const button = event.currentTarget;
    if (!(button instanceof HTMLButtonElement) || !paymentDetailsRecordId) {
      return;
    }
    const record = recordCache.find((item) => item.id === paymentDetailsRecordId);
    if (!record) {
      setStatus("Unable to find the selected payment record.", true);
      return;
    }
    const meta = nextProcessMeta(record);
    if (meta.disabled) {
      window.location.assign(meta.target);
      return;
    }
    button.disabled = true;
    button.textContent = "Saving...";
    try {
      const updated = await advanceProcessingRecord(record);
      setStatus(`Transaction routed to ${updated.currentStep}.`);
      setPaymentDetailsModalOpen(false);
      window.location.assign(meta.target);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Unable to continue the payment workflow.", true);
      button.disabled = false;
      button.textContent = meta.label;
    }
  });
}

function bindReceiptModal() {
  document.querySelectorAll("[data-close-receipt-modal]").forEach((button) => {
    button.addEventListener("click", () => setReceiptModalOpen(false));
  });
  document.querySelector("[data-receipt-modal]")?.addEventListener("click", (event) => {
    if (event.target === event.currentTarget) {
      setReceiptModalOpen(false);
    }
  });
  document.querySelector("[data-mark-receipt-paid]")?.addEventListener("click", async (event) => {
    const record = recordCache.find((item) => item.id === receiptModalRecordId);
    const button = event.currentTarget;
    if (!(button instanceof HTMLButtonElement)) {
      return;
    }
    button.disabled = true;
    const originalLabel = button.textContent;
    button.textContent = "Saving...";
    try {
      const updated = await markReceiptAsPaid(record);
      printConfirmationRecordId = updated.id;
      setReceiptModalOpen(false);
      setPrintConfirmationModalOpen(true);
      setStatus("Payment status updated to Paid.");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Unable to update the payment status.", true);
    } finally {
      button.disabled = false;
      button.textContent = originalLabel || "Paid";
    }
  });
}

function bindPrintConfirmationModal() {
  document.querySelectorAll("[data-close-print-confirmation]").forEach((button) => {
    button.addEventListener("click", () => setPrintConfirmationModalOpen(false));
  });
  document.querySelector("[data-print-confirmation-modal]")?.addEventListener("click", (event) => {
    if (event.target === event.currentTarget) {
      setPrintConfirmationModalOpen(false);
    }
  });
  document.querySelector("[data-print-receipt-bundle]")?.addEventListener("click", async (event) => {
    const record = recordCache.find((item) => item.id === printConfirmationRecordId);
    const button = event.currentTarget;
    if (!(button instanceof HTMLButtonElement)) {
      return;
    }
    button.disabled = true;
    const originalLabel = button.textContent;
    button.textContent = "Printing...";
    try {
      const opened = printReceiptBundle(record);
      if (!opened) {
        return;
      }
      const result = await notifyReceiptPrintComplete(record);
      const adminCount = Number(result?.adminNotifications || 0);
      const applicantCopy = result?.applicantNotified ? "Applicant" : "Applicant notification unavailable";
      const adminCopy = adminCount > 0 ? `Staff admin notified (${adminCount})` : "Staff admin notification unavailable";
      const finalizationCopy = result?.applicationStatusUpdated ? "Staff admin status updated for finalization." : "Application status update unavailable.";
      setStatus(`${applicantCopy}. ${adminCopy}. ${finalizationCopy}`);
      setPrintConfirmationModalOpen(false);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Printed, but unable to send the payment completion notifications.", true);
    } finally {
      button.disabled = false;
      button.textContent = originalLabel || "Print SOA + Official Receipt";
    }
  });
}

function bindProcessingPage() {
  document.querySelector("[data-processing-search]")?.addEventListener("input", () => renderProcessingQueue());
  document.querySelector("[data-step-filter]")?.addEventListener("change", () => renderProcessingQueue());
  document.querySelector("[data-processing-status-filter]")?.addEventListener("change", () => renderProcessingQueue());
  document.querySelector("[data-refresh-processing]")?.addEventListener("click", () => loadRecords());
  document.querySelector("[data-processing-queue]")?.addEventListener("click", (event) => {
    const row = event.target instanceof HTMLElement ? event.target.closest("tr") : null;
    const button = event.target instanceof HTMLElement ? event.target.closest("[data-process-record]") : null;
    if (button) {
      return;
    }
    const rows = getFilteredProcessingRecords();
    const index = row ? Array.from(row.parentElement?.children || []).indexOf(row) : -1;
    const record = index >= 0 ? rows[index] : null;
    if (record) {
      selectedRecordId = record.id;
      renderProcessingQueue();
    }
  });
  document.querySelector("[data-reset-processing-filters]")?.addEventListener("click", () => {
    const search = document.querySelector("[data-processing-search]");
    const step = document.querySelector("[data-step-filter]");
    const status = document.querySelector("[data-processing-status-filter]");
    if (search) search.value = "";
    if (step) step.value = "";
    if (status) status.value = "";
    renderProcessingQueue();
  });
}

function bindPaymentRecordsPage() {
  document.querySelector("[data-payment-search]")?.addEventListener("input", () => renderPaymentRecords());
  document.querySelector("[data-payment-status-filter]")?.addEventListener("change", () => renderPaymentRecords());
  document.querySelector("[data-payment-method-filter]")?.addEventListener("change", () => renderPaymentRecords());
  document.querySelector("[data-reset-payment-filters]")?.addEventListener("click", () => {
    const search = document.querySelector("[data-payment-search]");
    const status = document.querySelector("[data-payment-status-filter]");
    const method = document.querySelector("[data-payment-method-filter]");
    if (search) search.value = "";
    if (status) status.value = "";
    if (method) method.value = "";
    renderPaymentRecords();
  });
  document.querySelectorAll("[data-payment-export]").forEach((button) => {
    button.addEventListener("click", () => setStatus("Export is ready for connection when payment records are available."));
  });
}

function bindOfficialReceiptsPage() {
  document.querySelector("[data-receipt-search]")?.addEventListener("input", () => renderOfficialReceipts());
  document.querySelector("[data-receipt-status-filter]")?.addEventListener("change", () => renderOfficialReceipts());
  document.querySelector("[data-reset-receipt-filters]")?.addEventListener("click", () => {
    const search = document.querySelector("[data-receipt-search]");
    const status = document.querySelector("[data-receipt-status-filter]");
    if (search) search.value = "";
    if (status) status.value = "";
    renderOfficialReceipts();
  });
  document.querySelector("[data-refresh-receipts]")?.addEventListener("click", () => loadRecords());
  document.querySelector("[data-receipt-export]")?.addEventListener("click", () => setStatus("Export is ready for connection when official receipts are available."));
}

function bindTreasuryReportsPage() {
  document.querySelector("[data-report-search]")?.addEventListener("input", () => renderTreasuryReports());
  document.querySelector("[data-report-type-filter]")?.addEventListener("change", () => renderTreasuryReports());
  document.querySelector("[data-report-status-filter]")?.addEventListener("change", () => renderTreasuryReports());
  document.querySelectorAll("[data-report-export]").forEach((button) => {
    button.addEventListener("click", () => setStatus("Export is ready for connection when treasury reports are available."));
  });
}

function bindTreasurySettingsPage() {
  document.querySelectorAll("[data-settings-form]").forEach((form) => {
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      setStatus("Settings form is ready. Connect saving when treasury profile storage is available.");
    });
  });
  document.querySelectorAll("[data-settings-action]").forEach((button) => {
    button.addEventListener("click", () => setStatus("Security action is ready for connection."));
  });
}

async function boot() {
  try {
    window.lucide?.createIcons();
    const ok = await requireTreasurySession();
    if (!ok) return;
    bindCrud();
    if (document.body.dataset.page === "processing") {
      bindProcessingPage();
    }
    if (document.body.dataset.page === "payment-records") {
      bindPaymentRecordsPage();
      bindPaymentDetailsModal();
    }
    if (document.body.dataset.page === "official-receipts") {
      bindOfficialReceiptsPage();
      bindReceiptModal();
      bindPrintConfirmationModal();
    }
    if (document.body.dataset.page === "treasury-reports") {
      bindTreasuryReportsPage();
    }
    if (document.body.dataset.page === "treasury-settings") {
      bindTreasurySettingsPage();
    }
    document.querySelector("[data-treasury-logout]")?.addEventListener("click", async (event) => {
      event.preventDefault();
      const confirmed = window.BPLOLogoutModal?.confirm
        ? await window.BPLOLogoutModal.confirm()
        : true;
      if (!confirmed) {
        return;
      }

      await initSupabase()?.auth.signOut();
      window.location.assign("/login");
    });
    await loadRecords();
  } catch (error) {
    setStatus(error instanceof Error ? error.message : "Unable to load treasury dashboard.", true);
  }
}

window.addEventListener("DOMContentLoaded", () => {
  void boot();
});
