(function () {
  const modalId = "bplo-logout-modal";
  let pendingResolve = null;
  let previousFocus = null;

  function ensureStyles() {
    if (document.getElementById("bplo-logout-modal-style")) {
      return;
    }

    const style = document.createElement("style");
    style.id = "bplo-logout-modal-style";
    style.textContent = `
      .bplo-logout-overlay {
        position: fixed;
        inset: 0;
        z-index: 9999;
        display: none;
        align-items: center;
        justify-content: center;
        padding: 24px;
        background: rgba(9, 16, 12, 0.55);
        backdrop-filter: blur(2px);
      }

      .bplo-logout-overlay.is-open {
        display: flex;
      }

      .bplo-logout-dialog {
        width: min(100%, 310px);
        display: grid;
        justify-items: center;
        gap: 13px;
        padding: 28px 28px 22px;
        border-radius: 12px;
        background: #ffffff;
        box-shadow: 0 18px 45px rgba(20, 28, 23, 0.28);
        color: #1c241f;
        text-align: center;
      }

      .bplo-logout-icon {
        width: 58px;
        height: 58px;
        display: grid;
        place-items: center;
        border-radius: 50%;
        background: #ddf6e5;
        color: #078b36;
      }

      .bplo-logout-icon svg {
        width: 30px;
        height: 30px;
      }

      .bplo-logout-dialog h2 {
        margin: 2px 0 0;
        font-size: 22px;
        line-height: 1.15;
      }

      .bplo-logout-dialog p {
        max-width: 248px;
        margin: 0;
        color: #4f5b54;
        font-size: 12px;
        line-height: 1.45;
      }

      .bplo-logout-actions {
        width: 100%;
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 12px;
        margin-top: 8px;
      }

      .bplo-logout-actions button {
        min-height: 35px;
        border-radius: 7px;
        cursor: pointer;
        font-size: 12px;
        font-weight: 700;
      }

      .bplo-logout-cancel {
        border: 1px solid #87958d;
        background: #ffffff;
        color: #1f2c24;
      }

      .bplo-logout-confirm {
        border: 1px solid #078b36;
        background: #007f34;
        color: #ffffff;
      }
    `;
    document.head.appendChild(style);
  }

  function ensureModal() {
    ensureStyles();

    let overlay = document.getElementById(modalId);
    if (overlay) {
      return overlay;
    }

    overlay = document.createElement("div");
    overlay.id = modalId;
    overlay.className = "bplo-logout-overlay";
    overlay.setAttribute("role", "presentation");
    overlay.innerHTML = `
      <section class="bplo-logout-dialog" role="dialog" aria-modal="true" aria-labelledby="bplo-logout-title" aria-describedby="bplo-logout-message">
        <span class="bplo-logout-icon" aria-hidden="true">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"></path>
            <polyline points="16 17 21 12 16 7"></polyline>
            <line x1="21" y1="12" x2="9" y2="12"></line>
          </svg>
        </span>
        <h2 id="bplo-logout-title">Log out?</h2>
        <p id="bplo-logout-message">Are you sure you want to log out of the BPLO system?</p>
        <div class="bplo-logout-actions">
          <button class="bplo-logout-cancel" type="button">Cancel</button>
          <button class="bplo-logout-confirm" type="button">Log out</button>
        </div>
      </section>
    `;

    overlay.addEventListener("click", (event) => {
      if (event.target === overlay) {
        close(false);
      }
    });
    overlay.querySelector(".bplo-logout-cancel")?.addEventListener("click", () => close(false));
    overlay.querySelector(".bplo-logout-confirm")?.addEventListener("click", () => close(true));
    document.body.appendChild(overlay);
    return overlay;
  }

  function close(result) {
    const overlay = document.getElementById(modalId);
    overlay?.classList.remove("is-open");
    document.body.style.overflow = "";

    if (previousFocus instanceof HTMLElement) {
      previousFocus.focus();
    }

    if (pendingResolve) {
      const resolve = pendingResolve;
      pendingResolve = null;
      resolve(result);
    }
  }

  function confirm(options = {}) {
    if (pendingResolve) {
      return Promise.resolve(false);
    }

    const overlay = ensureModal();
    const title = overlay.querySelector("#bplo-logout-title");
    const message = overlay.querySelector("#bplo-logout-message");

    if (title) {
      title.textContent = options.title || "Log out?";
    }
    if (message) {
      message.textContent = options.message || "Are you sure you want to log out of the BPLO system?";
    }

    previousFocus = document.activeElement;
    overlay.classList.add("is-open");
    document.body.style.overflow = "hidden";
    overlay.querySelector(".bplo-logout-cancel")?.focus();

    return new Promise((resolve) => {
      pendingResolve = resolve;
    });
  }

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && pendingResolve) {
      close(false);
    }
  });

  document.addEventListener("click", async (event) => {
    const trigger = event.target.closest?.("[data-logout-modal-only]");
    if (!trigger) {
      return;
    }

    event.preventDefault();
    const accepted = await confirm({
      message: trigger.getAttribute("data-logout-message") || undefined,
    });

    if (accepted) {
      window.location.href = trigger.getAttribute("href") || "/login";
    }
  });

  window.BPLOLogoutModal = { confirm };
})();
