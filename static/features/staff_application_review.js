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
const departmentEvidence = document.querySelector("[data-department-evidence]");
const ocrResults = document.querySelector("[data-ocr-results]");
const assessmentItems = document.querySelector("[data-assessment-items]");
const assessmentSummary = document.querySelector("[data-assessment-summary]");
const assessmentTotals = document.querySelector("[data-assessment-totals]");
const paymentPermitInfo = document.querySelector("[data-payment-permit-info]");
const finalSummary = document.querySelector("[data-final-summary]");
const permitReadiness = document.querySelector("[data-permit-readiness]");
const feeForm = document.querySelector("[data-fee-form]");
const previewModal = document.querySelector("[data-preview-modal]");
const previewContent = document.querySelector("[data-preview-content]");
const previewFileName = document.querySelector("[data-preview-file-name]");
const routingModal = document.querySelector("[data-routing-modal]");
const routingContent = document.querySelector("[data-routing-content]");
const releasePermitButton = document.querySelector('[data-action="release-permit"]');
const printPermitButton = document.querySelector('[data-action="print-permit"]');
const actionModal = document.querySelector("[data-action-modal]");
const actionModalSubtitle = document.querySelector("[data-action-modal-subtitle]");
const actionModalCopy = document.querySelector("[data-action-modal-copy]");
const actionModalRemarks = document.querySelector("[data-action-modal-remarks]");
const actionModalRemarksLabel = document.querySelector("[data-action-modal-remarks-label]");
const actionModalRemarksInput = document.querySelector("[data-action-modal-remarks-input]");
const actionModalConfirm = document.querySelector("[data-confirm-action-modal]");
const actionModalSecondary = document.querySelector("[data-action-modal-secondary]");
const printApplicationFormStaffButton = document.querySelector("[data-print-application-form-staff]");

let reviewClient = null;
let reviewSession = null;
let reviewData = null;
let activePreviewUrl = "";
let pendingAction = "";
let releasePrintCompleted = false;

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
  if (status.includes("submitted") || status.includes("verified") || status.includes("paid") || status.includes("complete") || status.includes("ready") || status.includes("active") || status.includes("uploaded") || status.includes("released")) {
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

function ocrFieldLabel(value) {
  return String(value || "")
    .replaceAll("_", " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function syncPermitActionButtons(app, permit) {
  const hasPermit = Boolean(permit?.permit_number);
  const canRelease = hasPermit && ["Generated", "Ready for Release"].includes(permit?.status || "") && ["Permit Ready for Release", "For Pickup"].includes(app?.status || "");
  const canPrint = hasPermit;
  if (releasePermitButton) {
    releasePermitButton.hidden = !canRelease;
    releasePermitButton.disabled = !canRelease;
  }
  if (printPermitButton) {
    printPermitButton.hidden = !canPrint;
    printPermitButton.disabled = !canPrint;
  }
}

function renderPermitReadiness(app, permit) {
  if (!permitReadiness) {
    return;
  }
  const eligibility = app.permitEligibility || {};
  const missing = eligibility.missingRequirements || [];
  const warnings = eligibility.warnings || [];
  const hasPermit = Boolean(permit?.permit_number);
  const previewUrl = `/admin/staff-administrator/applications/${encodeURIComponent(app.id)}/permit-preview`;
  if (hasPermit) {
    permitReadiness.innerHTML = `
      <div class="review-empty-box review-empty-box--ready">
        <i data-lucide="file-check-2" aria-hidden="true"></i>
        <strong>Official permit ${escapeHtml(permit.permit_number)} is ${escapeHtml(permit.status || "generated")}.</strong>
        <span>Preview the exact A4 permit before printing, downloading, or release.</span>
        <a class="review-mini-button review-mini-button--green" href="${previewUrl}"><i data-lucide="eye" aria-hidden="true"></i>Open Official Preview</a>
      </div>
    `;
    return;
  }
  if (eligibility.eligible) {
    permitReadiness.innerHTML = `
      <div class="review-empty-box review-empty-box--ready">
        <i data-lucide="shield-check" aria-hidden="true"></i>
        <strong>Ready to generate the final permit.</strong>
        <span>All required reviews, inspections, assessment, payment, and receipt checks are complete.</span>
      </div>
    `;
    return;
  }
  const rows = [...missing, ...warnings].map((item) => `<li><i data-lucide="alert-circle" aria-hidden="true"></i>${escapeHtml(item)}</li>`).join("");
  permitReadiness.innerHTML = `
    <ul class="permit-eligibility-list review-eligibility-list">
      ${rows || '<li><i data-lucide="alert-circle" aria-hidden="true"></i>Eligibility could not be checked yet.</li>'}
    </ul>
  `;
}

function closeActionModal() {
  if (!actionModal) {
    return;
  }
  actionModal.hidden = true;
  actionModal.setAttribute("aria-hidden", "true");
  pendingAction = "";
  releasePrintCompleted = false;
  if (actionModalRemarksInput) {
    actionModalRemarksInput.value = "";
  }
  if (actionModalSecondary) {
    actionModalSecondary.hidden = true;
  }
  if (actionModalConfirm) {
    actionModalConfirm.disabled = false;
  }
}

function bindModalExitButtons() {
  const bindings = [
    { selector: "[data-close-preview]", close: closeDocumentPreview },
    { selector: "[data-close-routing]", close: closeRoutingConfirmation },
    { selector: "[data-close-action-modal]", close: closeActionModal },
  ];
  bindings.forEach(({ selector, close }) => {
    document.querySelectorAll(selector).forEach((button) => {
      button.addEventListener("click", (event) => {
        event.preventDefault();
        event.stopPropagation();
        close();
      });
    });
  });
}

function openActionModal(action) {
  if (!actionModal || !actionModalCopy || !actionModalConfirm) {
    return;
  }
  const modalConfig = {
    "approve-initial-review": {
      subtitle: "Approve the application",
      copy: "This will approve the initial review and continue the application to the next processing stage.",
      confirm: "Approve",
    },
    "request-revision": {
      subtitle: "Request a revision",
      copy: "Add revision notes so the applicant knows what needs to be corrected before the review can continue.",
      confirm: "Send Revision Request",
      requiresRemarks: true,
      remarksLabel: "Revision notes",
      placeholder: "What needs to be revised?",
    },
    "reject": {
      subtitle: "Reject the application",
      copy: "Add a clear reason for rejection. This will stop the current review until a new or corrected submission is made.",
      confirm: "Reject Application",
      requiresRemarks: true,
      remarksLabel: "Reason for rejection",
      placeholder: "Enter the reason for rejection",
    },
    "complete-assessment": {
      subtitle: "Complete the assessment",
      copy: "This will lock the assessment and route the application to Treasury for payment processing.",
      confirm: "Complete Assessment",
    },
    "finalize": {
      subtitle: "Generate the final permit",
      copy: "This will reserve the official permit number, build the QR verification link, and prepare the A4 permit preview from approved source records.",
      confirm: "Generate Permit",
    },
    "release-permit": {
      subtitle: "Release the business permit",
      copy: "Open the official permit preview to print, download, or complete the release.",
      confirm: "Open Preview",
    },
    "print-permit": {
      subtitle: "Print the business permit",
      copy: "This will open a printable version of the released business permit.",
      confirm: "Print Permit",
    },
  };
  const config = modalConfig[action];
  if (!config) {
    return;
  }
  pendingAction = action;
  actionModalSubtitle.textContent = config.subtitle;
  actionModalCopy.textContent = config.copy;
  actionModalConfirm.textContent = config.confirm;
  releasePrintCompleted = false;
  if (actionModalRemarks && actionModalRemarksInput && actionModalRemarksLabel) {
    const requiresRemarks = Boolean(config.requiresRemarks);
    actionModalRemarks.hidden = !requiresRemarks;
    actionModalRemarksLabel.textContent = config.remarksLabel || "Remarks";
    actionModalRemarksInput.placeholder = config.placeholder || "Enter remarks";
    actionModalRemarksInput.value = "";
  }
  if (actionModalSecondary) {
    actionModalSecondary.hidden = !config.requiresPrint;
    actionModalSecondary.textContent = config.requiresPrint ? "Print Permit" : "";
    if (config.requiresPrint) {
      actionModalSecondary.innerHTML = '<i data-lucide="printer" aria-hidden="true"></i>Print Permit';
    }
  }
  if (actionModalConfirm) {
    actionModalConfirm.disabled = Boolean(config.requiresPrint);
  }
  actionModal.hidden = false;
  actionModal.setAttribute("aria-hidden", "false");
  (actionModalRemarks?.hidden ? (config.requiresPrint ? actionModalSecondary : actionModalConfirm) : actionModalRemarksInput)?.focus();
  window.lucide?.createIcons();
}

function printBusinessPermit() {
  const app = reviewData || {};
  const permit = app.businessPermit || {};
  if (!permit?.permit_number) {
    setMessage("No business permit is available for printing yet.", true);
    return false;
  }
  window.open(`/admin/staff-administrator/applications/${encodeURIComponent(app.id)}/permit-preview?print=1`, "_blank", "noopener,noreferrer");
  return true;
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
  if (app.renewal?.isRenewal) {
    reviewHeader.insertAdjacentHTML("beforeend", `
      <article class="review-kpi review-kpi--renewal">
        <span class="review-kpi-icon"><i data-lucide="refresh-cw" aria-hidden="true"></i></span>
        <span><small>Renewal</small><strong>${escapeHtml(app.renewal.renewalNumber || `Year ${app.renewal.renewalYear || "-"}`)}</strong></span>
      </article>
    `);
  }
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
  document.querySelector(".review-renewal-compare")?.remove();
  if (app.renewal?.isRenewal) {
    const changes = app.renewal.changes || [];
    businessInfo.insertAdjacentHTML("afterend", `
      <article class="review-renewal-compare">
        <header>
          <strong>Renewal Comparison</strong>
          <span>Previous permit ${escapeHtml(app.renewal.previousPermit?.permit_number || "-")}</span>
        </header>
        ${changes.length ? changes.map((change) => `
          <div>
            <span>${escapeHtml(change.field_label || change.field_name || "Field")}</span>
            <del>${escapeHtml(change.previous_value || "-")}</del>
            <strong>${escapeHtml(change.new_value || "-")}</strong>
          </div>
        `).join("") : '<p>No important copied fields changed.</p>'}
      </article>
    `);
  }

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

  if (departmentEvidence) {
    departmentEvidence.classList.toggle("review-department-content--evidence", Boolean((app.departmentEvidence || []).length));
    departmentEvidence.innerHTML = (app.departmentEvidence || []).length
      ? app.departmentEvidence
          .map((evidence) => `
            <div class="review-evidence-item">
              <strong class="review-evidence-title">${escapeHtml(evidence.departmentKey || "Department")}</strong>
              <span class="review-evidence-file">${escapeHtml(evidence.fileName || "Evidence")}</span>
              <span class="review-evidence-remarks">${escapeHtml(evidence.remarks || "No remarks")}</span>
              <small class="review-evidence-meta">Uploaded by ${escapeHtml(evidence.uploadedByName || "Department staff")} ${evidence.createdAt ? `on ${escapeHtml(dateText(evidence.createdAt))}` : ""}</small>
              <p class="review-evidence-actions">
                <button class="review-mini-button" type="button" data-preview-evidence="${escapeHtml(evidence.viewUrl)}" data-file-name="${escapeHtml(evidence.fileName || "Evidence")}"><i data-lucide="eye" aria-hidden="true"></i>View</button>
                <button class="review-mini-button review-mini-button--green" type="button" data-download-evidence="${escapeHtml(evidence.downloadUrl)}" data-file-name="${escapeHtml(evidence.fileName || "Evidence")}"><i data-lucide="download" aria-hidden="true"></i>Download</button>
              </p>
            </div>
          `)
          .join("")
      : `
        <div class="review-empty-box">
          <i data-lucide="paperclip" aria-hidden="true"></i>
          <strong>No department evidence yet</strong>
          <span>Uploaded inspection photos, reports, or clearance files will appear here.</span>
        </div>
      `;
  }

  if (ocrResults) {
    ocrResults.innerHTML = (app.ocrResults || []).length
      ? app.ocrResults
          .map((result) => {
            const fields = result.extracted_fields_json || {};
            const fieldRows = Object.entries(fields).length
              ? Object.entries(fields)
                  .map(([fieldName, meta]) => {
                    const value = meta.corrected_value || meta.value || "-";
                    const original = meta.original_value && meta.original_value !== value ? `Original: ${escapeHtml(meta.original_value)}` : "";
                    const status = meta.validation_status || "needs_review";
                    return `
                      <div class="review-ocr-field">
                        <span>${escapeHtml(ocrFieldLabel(meta.application_field || fieldName))}</span>
                        <strong>${escapeHtml(value)}</strong>
                        <small>${escapeHtml(meta.confidence || 0)}% confidence - ${escapeHtml(status.replaceAll("_", " "))}</small>
                        ${original ? `<small>${original}</small>` : ""}
                        ${meta.corrected ? `<small>Corrected by applicant ${meta.corrected_at ? `on ${escapeHtml(dateText(meta.corrected_at))}` : ""}</small>` : ""}
                      </div>
                    `;
                  })
                  .join("")
              : '<div class="review-ocr-field"><span>No safe fields detected</span><strong>Manual review required</strong></div>';
            return `
              <article class="review-ocr-result">
                <header>
                  <strong>${escapeHtml(result.document_type || "Unknown Document")}</strong>
                  <span>${escapeHtml(result.confidence_score || 0)}% overall</span>
                </header>
                ${fieldRows}
              </article>
            `;
          })
          .join("")
      : `
        <div class="review-empty-box">
          <i data-lucide="scan-text" aria-hidden="true"></i>
          <strong>No structured OCR results yet</strong>
          <span>Document type, confidence scores, and applicant corrections will appear here after OCR review.</span>
        </div>
      `;
  }

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
  renderPermitReadiness(app, permit);
  syncPermitActionButtons(app, permit);

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
  if (action === "print-permit") {
    printBusinessPermit();
    return;
  }
  if (action === "release-permit") {
    window.location.href = `/admin/staff-administrator/applications/${encodeURIComponent(id)}/permit-preview`;
    return;
  }
  if (action === "reject" || action === "request-revision") {
    const remarks = (actionModalRemarksInput?.value || "").trim();
    if (!remarks) {
      throw new Error(action === "reject" ? "A rejection reason is required." : "Revision notes are required.");
    }
    body = { remarks };
  }

  try {
    setMessage("Saving action...");
    const result = await apiFetch(`/admin/api/applications/${encodeURIComponent(id)}/${action}`, {
      method: "POST",
      body: JSON.stringify(body),
    });
    if (action === "finalize" && result.previewUrl) {
      window.location.href = result.previewUrl;
      return;
    }
    await loadReview();
    setMessage(result.message || "Action completed successfully.");
    if (action === "approve-initial-review") {
      showRoutingConfirmation(result);
    }
  } catch (error) {
    setMessage(error.message || "Unable to save action.", true);
    throw error;
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

async function openProtectedFile(path, fileName, mode = "view") {
  const activeSession = await session();
  const response = await fetch(path, {
    headers: { "Authorization": `Bearer ${activeSession.access_token}` },
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload.error || "Unable to load file.");
  }
  const blob = await response.blob();
  const disposition = response.headers.get("Content-Disposition") || "";
  const match = disposition.match(/filename="([^"]+)"/);
  const url = URL.createObjectURL(blob);
  if (mode === "download") {
    const link = document.createElement("a");
    link.href = url;
    link.download = match?.[1] || fileName || "download";
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
    return;
  }
  showDocumentPreview(url, blob.type, fileName || "Attachment");
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
  if (target.closest("[data-print-application-form-staff]")) {
    const applicationId = applicationIdFromPath();
    if (!applicationId) {
      setMessage("The application form could not be found.", true);
      return;
    }
    printApplicationFormStaffButton.disabled = true;
    setMessage("Preparing application form...");
    const printSession = window.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`;
    window.location.href = `/applicant/application-print?applicationId=${encodeURIComponent(applicationId)}&printSession=${encodeURIComponent(printSession)}`;
    return;
  }
  const actionButton = target.closest("[data-action]");
  if (actionButton instanceof HTMLElement) {
    openActionModal(actionButton.dataset.action || "");
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
  const previewEvidenceButton = target.closest("[data-preview-evidence]");
  if (previewEvidenceButton instanceof HTMLElement) {
    try {
      await openProtectedFile(previewEvidenceButton.dataset.previewEvidence || "", previewEvidenceButton.dataset.fileName || "Evidence", "view");
    } catch (error) {
      setMessage(error.message || "Unable to preview evidence.", true);
    }
    return;
  }
  const downloadEvidenceButton = target.closest("[data-download-evidence]");
  if (downloadEvidenceButton instanceof HTMLElement) {
    try {
      await openProtectedFile(downloadEvidenceButton.dataset.downloadEvidence || "", downloadEvidenceButton.dataset.fileName || "Evidence", "download");
    } catch (error) {
      setMessage(error.message || "Unable to download evidence.", true);
    }
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
  if (target.closest("[data-close-action-modal]")) {
    closeActionModal();
    return;
  }
  if (target.closest("[data-confirm-action-modal]")) {
    try {
      await runApplicationAction(pendingAction);
      closeActionModal();
    } catch (_error) {
      // keep modal open so the user can adjust input or retry
    }
    return;
  }
  if (target.closest("[data-action-modal-secondary]")) {
    const printed = printBusinessPermit();
    if (printed) {
      releasePrintCompleted = true;
      if (actionModalConfirm) {
        actionModalConfirm.disabled = false;
      }
      if (actionModalCopy && pendingAction === "release-permit") {
        actionModalCopy.textContent = "Printing completed. You can now finalize the release to mark the permit for pickup and notify the applicant.";
      }
      setMessage("Permit print opened. Complete the release to finish the pickup process.");
    }
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
  if (event.key === "Escape" && actionModal && !actionModal.hidden) {
    closeActionModal();
  }
});

window.addEventListener("DOMContentLoaded", () => {
  window.lucide?.createIcons();
  bindModalExitButtons();
  void loadReview();
});
