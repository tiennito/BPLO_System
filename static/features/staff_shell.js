const staffShell = document.querySelector(".staff-admin-shell");
const staffMenuButton = document.querySelector("[data-staff-menu]");

function setStaffNavigationOpen(isOpen) {
  if (!staffShell || !staffMenuButton) {
    return;
  }
  staffShell.classList.toggle("is-nav-open", isOpen);
  staffMenuButton.setAttribute("aria-expanded", String(isOpen));
}

if (staffShell && staffMenuButton) {
  const scrim = document.createElement("button");
  scrim.type = "button";
  scrim.className = "staff-sidebar-scrim";
  scrim.setAttribute("aria-label", "Close navigation");
  staffShell.appendChild(scrim);

  staffMenuButton.addEventListener("click", () => {
    setStaffNavigationOpen(!staffShell.classList.contains("is-nav-open"));
  });
  scrim.addEventListener("click", () => setStaffNavigationOpen(false));
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      setStaffNavigationOpen(false);
    }
  });
  window.addEventListener("resize", () => {
    if (window.innerWidth > 760) {
      setStaffNavigationOpen(false);
    }
  });
}
