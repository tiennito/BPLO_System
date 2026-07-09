const STAFF_REPORT_SUPABASE_URL = window.APP_CONFIG?.supabaseUrl || "";
const STAFF_REPORT_SUPABASE_KEY =
  window.APP_CONFIG?.supabaseAnonKey || window.APP_CONFIG?.supabasePublishableKey || "";

let staffReportClient = null;
let staffReportSession = null;

function staffReportStatus(message, isError = false) {
  let node = document.querySelector("[data-staff-report-status]");
  if (!node) {
    node = document.createElement("p");
    node.dataset.staffReportStatus = "";
    node.className = "status-line";
    document.querySelector(".staff-report-controls")?.appendChild(node);
  }
  node.textContent = message;
  node.style.color = isError ? "#b42318" : "#667085";
}

function staffClient() {
  if (!staffReportClient && window.supabase?.createClient) {
    staffReportClient = window.supabase.createClient(STAFF_REPORT_SUPABASE_URL, STAFF_REPORT_SUPABASE_KEY);
  }
  return staffReportClient;
}

async function staffSession() {
  if (staffReportSession?.access_token) {
    return staffReportSession;
  }
  const client = staffClient();
  if (!client) {
    throw new Error("Supabase is not available.");
  }
  const { data, error } = await client.auth.getSession();
  if (error) {
    throw error;
  }
  if (!data.session?.access_token) {
    throw new Error("Please log in as BPLO staff admin.");
  }
  staffReportSession = data.session;
  return staffReportSession;
}

async function downloadStaffReport(format) {
  const session = await staffSession();
  const response = await fetch(`/admin/api/reports/export?type=applications&format=${encodeURIComponent(format)}`, {
    headers: { "Authorization": `Bearer ${session.access_token}` },
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload.error || "Unable to export report.");
  }
  const blob = await response.blob();
  const disposition = response.headers.get("Content-Disposition") || "";
  const match = disposition.match(/filename="([^"]+)"/);
  const link = document.createElement("a");
  const url = URL.createObjectURL(blob);
  link.href = url;
  link.download = match?.[1] || (format === "pdf" ? "applications-report.html" : "applications-report.csv");
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

window.addEventListener("DOMContentLoaded", () => {
  window.lucide?.createIcons();
  document.querySelectorAll("[data-staff-report-export]").forEach((button) => {
    button.addEventListener("click", async () => {
      const format = button.dataset.staffReportExport === "pdf" ? "pdf" : "csv";
      try {
        button.disabled = true;
        staffReportStatus("Preparing report export...");
        await downloadStaffReport(format);
        staffReportStatus("Report export downloaded.");
      } catch (error) {
        staffReportStatus(error instanceof Error ? error.message : "Unable to export report.", true);
      } finally {
        button.disabled = false;
      }
    });
  });
});
