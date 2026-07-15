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

function activeReportRange() {
  const activeTab = document.querySelector(".staff-report-tabs button.is-active");
  return (activeTab?.textContent || "Today").trim().toLowerCase();
}

async function downloadStaffReport() {
  const session = await staffSession();
  const params = new URLSearchParams({
    type: "applications",
    format: "pdf",
    range: activeReportRange(),
  });
  const response = await fetch(`/admin/api/reports/export?${params.toString()}`, {
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
  link.download = match?.[1] || "applications-report.pdf";
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

window.addEventListener("DOMContentLoaded", () => {
  window.lucide?.createIcons();
  document.querySelectorAll(".staff-report-tabs button").forEach((tab) => {
    tab.addEventListener("click", () => {
      document.querySelectorAll(".staff-report-tabs button").forEach((item) => item.classList.remove("is-active"));
      tab.classList.add("is-active");
      staffReportStatus(`${tab.textContent.trim()} report range selected.`);
    });
  });
  document.querySelectorAll("[data-staff-report-export]").forEach((button) => {
    button.addEventListener("click", async () => {
      try {
        button.disabled = true;
        staffReportStatus("Preparing PDF export...");
        await downloadStaffReport();
        staffReportStatus("PDF export downloaded.");
      } catch (error) {
        staffReportStatus(error instanceof Error ? error.message : "Unable to export report.", true);
      } finally {
        button.disabled = false;
      }
    });
  });
});
