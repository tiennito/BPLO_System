const REVIEW_SUPABASE_URL = window.APP_CONFIG?.supabaseUrl || "";
const REVIEW_SUPABASE_KEY =
  window.APP_CONFIG?.supabaseAnonKey || window.APP_CONFIG?.supabasePublishableKey || "";

const reviewMessage = document.querySelector("[data-review-message]");
const reviewHeader = document.querySelector("[data-review-header]");
const reviewWorkflow = document.querySelector("[data-review-workflow]");
const applicantInfo = document.querySelector("[data-applicant-info]");
const businessInfo = document.querySelector("[data-business-info]");
const documentsBody = document.querySelector("[data-documents-body]");
const departmentProgress = document.querySelector("[data-department-progress]");
const assessmentItems = document.querySelector("[data-assessment-items]");
const assessmentSummary = document.querySelector("[data-assessment-summary]");
const assessmentTotals = document.querySelector("[data-assessment-totals]");
const paymentPermitInfo = document.querySelector("[data-payment-permit-info]");
const finalSummary = document.querySelector("[data-final-summary]");
const feeForm = document.querySelector("[data-fee-form]");
const previewModal = document.querySelector("[data-preview-modal]");
const previewContent = document.querySelector("[data-preview-content]");
const previewFileName = document.querySelector("[data-preview-file-name]");
const routingModal = document.querySelector("[data-routing-modal]");
const routingContent = document.querySelector("[data-routing-content]");

let reviewClient = null;
let reviewSession = null;
let reviewData = null;
let activePreviewUrl = "";

function applicationIdFromPath() {
  const parts = window.location.pathname.split("/").filter(Boolean);
  return decodeURIComponent(parts[parts.length - 1] || "");
}

function client() {
  if (!reviewClient && window.supabase?.createClient) {
    reviewClient = window.supabase.createClient(REVIEW_SUPABASE_URL, REVIEW_SUPABASE_KEY);
  }
  return reviewClient;
}

async function session() {
  if (reviewSession?.access_token) {
    return reviewSession;
  }
  const api = client();
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
  reviewSession = data.session;
  return reviewSession;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function peso(value) {
  const number = Number(value || 0);
  return number.toLocaleString(undefined, { style: "currency", currency: "PHP" });
}

function dateText(value) {
  if (!value) {
    return "-";
  }
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "-" : date.toLocaleString();
}

function setMessage(message, isError = false) {
  if (!reviewMessage) {
    return;
  }
  reviewMessage.textContent = message || "";
  reviewMessage.style.color = isError ? "#b42318" : "#516159";
}

function statusTone(value) {
  const status = String(value || "").toLowerCase();
  if (status.includes("submitted") || status.includes("verified") || status.includes("paid") || status.includes("complete") || status.includes("ready") || status.includes("active") || status.includes("uploaded")) {
    return "success";
  }
  if (status.includes("unpaid") || status.includes("pending") || status.includes("draft")) {
    return "warning";
  }
  if (status.includes("reject") || status.includes("revision") || status.includes("cancel")) {
    return "danger";
  }
  return "info";
}

function compactDate(value) {
  if (!value) {
    return "Pending";
  }
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? "Pending"
    : date.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

function displayFileName(value) {
  const text = String(value || "-");
  if (text.length <= 36) {
    return escapeHtml(text);
  }
  return escapeHtml(text.replaceAll("_", "_\u200b"));
}

function statusPill(value) {
  const label = value || "-";
  return `<span class="review-pill review-pill--${statusTone(label)}"><i data-lucide="check" aria-hidden="true"></i>${escapeHtml(label)}</span>`;
}

function dl(items) {
  return items
    .map(([label, value]) => `<div><dt>${escapeHtml(label)}</dt><dd>${escapeHtml(value || "-")}</dd></div>`)
    .join("");
}

function enhancedDl(items) {
  return items
    .map(([label, value, html]) => `<div><dt>${escapeHtml(label)}</dt><dd>${html || escapeHtml(value || "-")}</dd></div>`)
    .join("");
}

function renderWorkflow(app, assessment, permit) {
  if (!reviewWorkflow) {
    return;
  }
  const status = String(app.status || "").toLowerCase();
  const departmentReviews = app.departmentReviews || [];
  const hasInitialReview = Boolean(app.reviewedAt || status.includes("department") || status.includes("payment") || status.includes("permit"));
  const hasDepartments = departmentReviews.length > 0 && departmentReviews.every((review) => ["Approved", "Completed"].includes(review.status));
  const hasAssessment = ["Completed", "For Payment", "Paid"].includes(assessment.status) || status.includes("payment");
  const hasFinal = Boolean(permit.permit_number) || status.includes("permit");
  const steps = [
    { label: "Submitted", icon: "check", done: Boolean(app.submittedAt), meta: compactDate(app.submittedAt) },
    { label: "Initial Review", icon: "user-round", done: hasInitialReview, active: !hasInitialReview, meta: hasInitialReview ? "Completed" : "In Progress" },
    { label: "Department Review", icon: "clipboard-list", done: hasDepartments, active: hasInitialReview && !hasDepartments, meta: hasDepartments ? "Completed" : "Pending" },
    { label: "Assessment", icon: "clipboard-check", done: hasAssessment, active: hasDepartments && !hasAssessment, meta: hasAssessment ? assessment.status || "Completed" : "Pending" },
    { label: "Finalization", icon: "file-text", done: hasFinal, active: hasAssessment && !hasFinal, meta: hasFinal ? "Ready" : "Pending" },
  ];

  reviewWorkflow.innerHTML = steps
    .map((step, index) => `
      <div class="review-step ${step.done ? "is-done" : ""} ${step.active ? "is-active" : ""}">
        ${index ? '<span class="review-step-line" aria-hidden="true"></span>' : ""}
        <span class="review-step-icon"><i data-lucide="${step.icon}" aria-hidden="true"></i></span>
        <span class="review-step-copy">
          <strong>${escapeHtml(step.label)}</strong>
          <small>${escapeHtml(step.meta)}</small>
        </span>
      </div>
    `)
    .join("");
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

function latestReviewForDocument(documentId) {
  const reviews = reviewData?.documentReviews || [];
  return reviews.find((review) => review.document_id === documentId) || null;
}

function documentById(documentId) {
  return (reviewData?.documents || []).find((document) => String(document.id) === String(documentId)) || null;
}

function render() {
  if (!reviewData) {
    return;
  }
  const app = reviewData;
  const assessment = app.assessment || {};
  const queue = app.treasuryQueue || {};
  const receipt = (app.receipts || [])[0] || {};
  const payment = (app.payments || [])[0] || {};
  const permit = app.businessPermit || {};

  reviewHeader.innerHTML = `
    <article class="review-kpi">
      <span class="review-kpi-icon"><i data-lucide="clipboard-check" aria-hidden="true"></i></span>
      <span><small>Control No.</small><strong>${escapeHtml(app.controlNumber)}</strong></span>
    </article>
    <article class="review-kpi">
      <span class="review-kpi-icon"><i data-lucide="file-check-2" aria-hidden="true"></i></span>
      <span><small>Application Status</small><strong class="review-status-text review-status-text--${statusTone(app.status)}">${escapeHtml(app.status)}</strong></span>
    </article>
    <article class="review-kpi">
      <span class="review-kpi-icon"><i data-lucide="credit-card" aria-hidden="true"></i></span>
      <span><small>Payment Status</small><strong class="review-status-text review-status-text--${statusTone(app.paymentStatus)}">${escapeHtml(app.paymentStatus)}</strong></span>
    </article>
    <article class="review-kpi">
      <span class="review-kpi-icon"><i data-lucide="clipboard-list" aria-hidden="true"></i></span>
      <span><small>Assessment Status</small><strong class="review-status-text review-status-text--${statusTone(assessment.status || app.assessmentStatus || "Draft")}">${escapeHtml(assessment.status || app.assessmentStatus || "Draft")}</strong></span>
    </article>
  `;
  renderWorkflow(app, assessment, permit);

  applicantInfo.innerHTML = enhancedDl([
    ["Full name", app.applicant?.name],
    ["Email", app.applicant?.email],
    ["Contact number", app.applicant?.contactNumber],
    ["Residential address", app.applicant?.address],
    ["Account status", app.applicant?.verificationStatus, statusPill(app.applicant?.verificationStatus || "Active")],
  ]);
  businessInfo.innerHTML = enhancedDl([
    ["Business name", app.business?.name],
    ["Trade name", app.business?.tradeName],
    ["Business classification", app.business?.classification],
    ["Parent category", app.business?.parentCategory],
    ["Ownership type", app.business?.ownershipType],
    ["Business address", app.business?.address],
    ["TIN", app.business?.tin],
    ["Registration no.", app.business?.registrationNumber],
    ["Capital investment", app.business?.capitalInvestment],
    ["Gross sales / receipts", app.business?.grossSales],
    ["Employees", app.business?.employees],
    ["Business area", app.business?.businessArea],
    ["Delivery vehicles", app.business?.deliveryVehicles],
    ["Signboard area", app.business?.signboardArea],
    ["Storage area", app.business?.storageArea],
  ]);

  documentsBody.innerHTML = (app.documents || []).length
    ? app.documents
        .map((document) => {
          const snapshot = document.document_snapshot || {};
          const review = latestReviewForDocument(document.id);
          return `
            <tr>
              <td><span class="review-document-name"><i data-lucide="file-image" aria-hidden="true"></i>${escapeHtml(snapshot.documentName || snapshot.document_name || "Document")}</span></td>
              <td class="review-file-cell">${displayFileName(document.file_name)}</td>
              <td>${statusPill(document.upload_status || "-")}</td>
              <td>${statusPill(review?.status || "Pending")}</td>
              <td>${escapeHtml(review?.remarks || document.remarks || "-")}</td>
              <td class="review-row-actions">
                ${document.file_url ? `<button class="review-mini-button" type="button" data-preview-document="${escapeHtml(document.id)}"><i data-lucide="eye" aria-hidden="true"></i>Preview</button>` : ""}
                <button class="review-mini-button review-mini-button--green" type="button" data-review-document="${escapeHtml(document.id)}"><i data-lucide="file-check-2" aria-hidden="true"></i>Review</button>
              </td>
            </tr>
          `;
        })
        .join("")
    : '<tr><td colspan="6" class="staff-empty-cell">No uploaded documents found.</td></tr>';

  departmentProgress.innerHTML = (app.departmentReviews || []).length
    ? app.departmentReviews
        .map((review) => `<span class="review-chip">${escapeHtml(review.department_key || "office")} - ${escapeHtml(review.status || "Pending")}</span>`)
        .join("")
    : `
      <div class="review-empty-box">
        <i data-lucide="clipboard-search" aria-hidden="true"></i>
        <strong>No department routing yet</strong>
        <span>After initial approval, required offices will appear here.</span>
      </div>
    `;

  assessmentItems.innerHTML = (app.assessmentItems || []).length
    ? app.assessmentItems
        .map(
          (item) => `
          <tr>
            <td>${escapeHtml(item.department_key)}</td>
            <td>${escapeHtml(item.category)}</td>
            <td>${escapeHtml(item.fee_name)}</td>
            <td>${escapeHtml(item.quantity)}</td>
            <td>${peso(item.rate)}</td>
            <td>${peso(item.amount)}</td>
            <td>${peso(item.penalty)}</td>
            <td>${peso(item.discount)}</td>
            <td>${peso(item.final_amount)}</td>
            <td><button class="review-mini-button review-mini-button--danger" type="button" data-delete-fee="${escapeHtml(item.id)}">Remove</button></td>
          </tr>
        `
        )
        .join("")
    : '<tr><td colspan="10" class="staff-empty-cell"><span class="review-inline-empty"><i data-lucide="archive" aria-hidden="true"></i><strong>No assessment items yet.</strong><small>Add fee items above to start the assessment.</small></span></td></tr>';

  assessmentSummary.textContent = assessment.assessment_number
    ? `Assessment ${assessment.assessment_number}`
    : "Add fee items to start the assessment.";
  assessmentTotals.innerHTML = `
    <article><small>Subtotal</small><strong>${peso(assessment.subtotal)}</strong></article>
    <article class="is-warning"><small>Penalty</small><strong>${peso(assessment.penalty_total)}</strong></article>
    <article><small>Discount</small><strong>${peso(assessment.discount_total)}</strong></article>
    <article class="is-total"><small>Grand Total</small><strong>${peso(assessment.grand_total)}</strong></article>
  `;

  paymentPermitInfo.innerHTML = dl([
    ["Queue number", queue.queue_number],
    ["Queue status", queue.status],
    ["Amount due", queue.amount_due ? peso(queue.amount_due) : ""],
    ["Amount paid", payment.amount_paid ? peso(payment.amount_paid) : ""],
    ["Payment method", payment.payment_method],
    ["Official receipt", receipt.receipt_number || payment.official_receipt_number],
    ["Date paid", payment.paid_at ? dateText(payment.paid_at) : ""],
    ["Permit number", permit.permit_number],
    ["Permit status", permit.status],
    ["Verification code", permit.verification_code],
  ]);
  finalSummary.textContent = permit.permit_number
    ? `Permit ${permit.permit_number} is ${permit.status}.`
    : "Permit is generated after Treasury payment confirmation.";

  window.lucide?.createIcons();
}

async function loadReview() {
  try {
    setMessage("Loading application review...");
    const id = applicationIdFromPath();
    const payload = await apiFetch(`/admin/api/applications/${encodeURIComponent(id)}`);
    reviewData = payload.application;
    render();
    setMessage("Application review loaded.");
  } catch (error) {
    setMessage(error.message || "Unable to load application review.", true);
  }
}

async function runApplicationAction(action) {
  const id = applicationIdFromPath();
  let body = {};
  if (action === "reject" || action === "request-revision") {
    const remarks = window.prompt(action === "reject" ? "Reason for rejection" : "What needs revision?");
    if (!remarks) {
      return;
    }
    body = { remarks };
  } else {
    const labels = {
      "approve-initial-review": "Approve initial review?",
      "complete-assessment": "Complete the assessment and send it to Treasury?",
      "finalize": "Finalize and generate the business permit?",
    };
    if (!window.confirm(labels[action] || "Continue?")) {
      return;
    }
  }

  try {
    setMessage("Saving action...");
    const result = await apiFetch(`/admin/api/applications/${encodeURIComponent(id)}/${action}`, {
      method: "POST",
      body: JSON.stringify(body),
    });
    await loadReview();
    if (action === "approve-initial-review") {
      showRoutingConfirmation(result);
    }
  } catch (error) {
    setMessage(error.message || "Unable to save action.", true);
  }
}

function closeRoutingConfirmation() {
  if (!routingModal) {
    return;
  }
  routingModal.hidden = true;
  routingModal.setAttribute("aria-hidden", "true");
}

function showRoutingConfirmation(result) {
  if (!routingModal || !routingContent) {
    return;
  }
  const app = result?.application || reviewData || {};
  const routing = result?.routing || {};
  const departments = routing.departments || [];
  const notificationCount = Number(routing.notificationsSent || 0);
  const departmentRows = departments.length
    ? departments
        .map((department) => {
          const sent = Number(department.notificationsSent || 0);
          const notice = sent > 0 ? `${sent} notification${sent === 1 ? "" : "s"} sent` : "Application visible";
          return `<li><span>${escapeHtml(department.name || department.key || "Department")}</span><em>${escapeHtml(notice)}</em></li>`;
        })
        .join("")
    : "<li><span>No required departments were returned.</span><em>Check permit setup</em></li>";

  routingContent.innerHTML = `
    <section class="review-routing-summary" aria-label="Application routing summary">
      <article><small>Control No.</small><strong>${escapeHtml(app.controlNumber || app.id || "-")}</strong></article>
      <article><small>Business Name</small><strong>${escapeHtml(app.businessName || reviewData?.business?.name || "-")}</strong></article>
      <article><small>Applicant</small><strong>${escapeHtml(app.applicantName || reviewData?.applicant?.name || "-")}</strong></article>
      <article><small>Current Status</small><strong>${escapeHtml(app.status || reviewData?.status || "-")}</strong></article>
      <article><small>Departments Routed</small><strong>${escapeHtml(String(routing.departmentCount ?? departments.length))}</strong></article>
      <article><small>Notifications</small><strong>${escapeHtml(notificationCount ? `${notificationCount} sent` : "Confirmed")}</strong></article>
    </section>
    <section class="review-routing-departments">
      <h3>Assigned Departments</h3>
      <small>These offices can now see the application in their Applications page.</small>
      <ul>${departmentRows}</ul>
    </section>
  `;
  routingModal.hidden = false;
  routingModal.setAttribute("aria-hidden", "false");
  routingModal.querySelector("[data-close-routing]")?.focus();
  window.lucide?.createIcons();
}

async function saveDocumentReview(documentId) {
  const status = window.prompt("Document status: Verified, Rejected, For Revision, Under Review", "Verified");
  if (!status) {
    return;
  }
  const remarks = window.prompt("Remarks", "") || "";
  try {
    await apiFetch("/admin/api/document-reviews", {
      method: "POST",
      body: JSON.stringify({
        applicationId: applicationIdFromPath(),
        documentId,
        status,
        remarks,
        departmentKey: "bplo",
      }),
    });
    await loadReview();
  } catch (error) {
    setMessage(error.message || "Unable to save document review.", true);
  }
}

async function openDocumentPreview(documentId) {
  if (!documentId) {
    return;
  }
  try {
    setMessage("Opening document preview...");
    const activeSession = await session();
    const response = await fetch(`/admin/application-documents/${encodeURIComponent(documentId)}/preview`, {
      headers: { "Authorization": `Bearer ${activeSession.access_token}` },
    });
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      throw new Error(payload.error || "Unable to preview document.");
    }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    showDocumentPreview(url, blob.type, documentById(documentId)?.file_name || "Uploaded document");
    setMessage("Document preview opened.");
  } catch (error) {
    setMessage(error.message || "Unable to preview document.", true);
  }
}

function closeDocumentPreview() {
  if (!previewModal || !previewContent) {
    return;
  }
  previewModal.hidden = true;
  previewModal.setAttribute("aria-hidden", "true");
  previewContent.innerHTML = "";
  if (activePreviewUrl) {
    URL.revokeObjectURL(activePreviewUrl);
    activePreviewUrl = "";
  }
}

function showDocumentPreview(url, mimeType, fileName) {
  if (!previewModal || !previewContent) {
    window.open(url, "_blank", "noopener,noreferrer");
    return;
  }
  closeDocumentPreview();
  activePreviewUrl = url;
  if (previewFileName) {
    previewFileName.textContent = fileName || "Uploaded document";
  }
  const normalizedType = String(mimeType || "").toLowerCase();
  const normalizedName = String(fileName || "").toLowerCase();
  const isImage = normalizedType.startsWith("image/") || /\.(avif|bmp|gif|jpe?g|png|webp)$/i.test(normalizedName);
  const isPdf = normalizedType.includes("pdf") || /\.pdf$/i.test(normalizedName);
  const escapedUrl = escapeHtml(url);
  const escapedName = escapeHtml(fileName || "Uploaded document");
  if (isImage) {
    previewContent.innerHTML = `<img src="${escapedUrl}" alt="${escapedName}" />`;
  } else if (isPdf) {
    previewContent.innerHTML = `<iframe src="${escapedUrl}" title="${escapedName}"></iframe>`;
  } else {
    previewContent.innerHTML = `
      <div class="review-preview-fallback">
        <strong>Preview is not available for this file type.</strong>
        <span>The file was loaded, but this browser cannot display it inside the page.</span>
      </div>
    `;
  }
  previewModal.hidden = false;
  previewModal.setAttribute("aria-hidden", "false");
  previewModal.querySelector("[data-close-preview]")?.focus();
  window.lucide?.createIcons();
}

feeForm?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const formData = new FormData(feeForm);
  const quantity = Number(formData.get("quantity") || 1);
  const rate = Number(formData.get("rate") || 0);
  try {
    await apiFetch("/admin/api/assessment-items", {
      method: "POST",
      body: JSON.stringify({
        applicationId: applicationIdFromPath(),
        feeName: formData.get("feeName"),
        departmentKey: formData.get("departmentKey"),
        category: formData.get("category"),
        quantity,
        rate,
        amount: quantity * rate,
        finalAmount: quantity * rate,
        remarks: formData.get("remarks"),
      }),
    });
    feeForm.reset();
    feeForm.elements.departmentKey.value = "bplo";
    feeForm.elements.category.value = "Regulatory Fees and Charges";
    feeForm.elements.quantity.value = "1";
    await loadReview();
  } catch (error) {
    setMessage(error.message || "Unable to add fee item.", true);
  }
});

document.addEventListener("click", async (event) => {
  const target = event.target;
  if (!(target instanceof HTMLElement)) {
    return;
  }
  const actionButton = target.closest("[data-action]");
  if (actionButton instanceof HTMLElement) {
    await runApplicationAction(actionButton.dataset.action || "");
    return;
  }
  const documentButton = target.closest("[data-review-document]");
  if (documentButton instanceof HTMLElement) {
    await saveDocumentReview(documentButton.dataset.reviewDocument || "");
    return;
  }
  const previewButton = target.closest("[data-preview-document]");
  if (previewButton instanceof HTMLElement) {
    await openDocumentPreview(previewButton.dataset.previewDocument || "");
    return;
  }
  if (target.closest("[data-close-preview]")) {
    closeDocumentPreview();
    return;
  }
  if (target.closest("[data-close-routing]")) {
    closeRoutingConfirmation();
    return;
  }
  const deleteButton = target.closest("[data-delete-fee]");
  if (deleteButton instanceof HTMLElement && window.confirm("Remove this fee item?")) {
    try {
      await apiFetch(`/admin/api/assessment-items/${encodeURIComponent(deleteButton.dataset.deleteFee || "")}`, { method: "DELETE" });
      await loadReview();
    } catch (error) {
      setMessage(error.message || "Unable to remove fee item.", true);
    }
    return;
  }
  if (target.closest("[data-refresh-assessment]")) {
    await loadReview();
  }
});

document.querySelector("[data-review-back]")?.addEventListener("click", (event) => {
  if (document.referrer && new URL(document.referrer).origin === window.location.origin) {
    event.preventDefault();
    window.history.back();
  }
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && previewModal && !previewModal.hidden) {
    closeDocumentPreview();
  }
  if (event.key === "Escape" && routingModal && !routingModal.hidden) {
    closeRoutingConfirmation();
  }
});

window.addEventListener("DOMContentLoaded", () => {
  window.lucide?.createIcons();
  void loadReview();
});
