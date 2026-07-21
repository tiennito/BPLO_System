const departmentShell = document.querySelector(".department-shell");
const departmentMenuButton = document.querySelector("[data-department-menu]");

function setDepartmentNavigationOpen(isOpen) {
  if (!departmentShell || !departmentMenuButton) {
    return;
  }

  departmentShell.classList.toggle("is-nav-open", isOpen);
  departmentMenuButton.setAttribute("aria-expanded", String(isOpen));
}

if (departmentShell && departmentMenuButton) {
  const scrim = document.createElement("button");
  scrim.type = "button";
  scrim.className = "department-sidebar-scrim";
  scrim.setAttribute("aria-label", "Close navigation");
  departmentShell.appendChild(scrim);

  departmentMenuButton.addEventListener("click", () => {
    setDepartmentNavigationOpen(!departmentShell.classList.contains("is-nav-open"));
  });

  scrim.addEventListener("click", () => setDepartmentNavigationOpen(false));

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      setDepartmentNavigationOpen(false);
    }
  });

  window.addEventListener("resize", () => {
    if (window.innerWidth > 760) {
      setDepartmentNavigationOpen(false);
    }
  });
}
