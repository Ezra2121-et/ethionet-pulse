"use strict";

(() => {
  const sidebar = document.getElementById("app-sidebar");
  const toggle = document.getElementById("sidebar-toggle");
  const backdrop = document.getElementById("sidebar-backdrop");
  if (!sidebar || !toggle || !backdrop) return;

  const desktopQuery = window.matchMedia("(min-width: 1051px)");

  function isOpen() {
    return toggle.getAttribute("aria-expanded") === "true";
  }

  function closeSidebar(restoreFocus = false) {
    sidebar.classList.remove("is-open");
    toggle.setAttribute("aria-expanded", "false");
    toggle.setAttribute("aria-label", "Open navigation menu");
    backdrop.hidden = true;
    document.body.classList.remove("sidebar-open");

    if (restoreFocus && !desktopQuery.matches) {
      toggle.focus();
    }
  }

  function openSidebar() {
    if (desktopQuery.matches) return;

    sidebar.classList.add("is-open");
    toggle.setAttribute("aria-expanded", "true");
    toggle.setAttribute("aria-label", "Close navigation menu");
    backdrop.hidden = false;
    document.body.classList.add("sidebar-open");

    const firstLink = sidebar.querySelector(".nav-link");
    if (firstLink) firstLink.focus({ preventScroll: true });
  }

  toggle.addEventListener("click", () => {
    if (isOpen()) {
      closeSidebar(true);
    } else {
      openSidebar();
    }
  });

  backdrop.addEventListener("click", () => closeSidebar(true));

  sidebar.querySelectorAll(".nav-link").forEach((link) => {
    link.addEventListener("click", () => closeSidebar(false));
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && isOpen()) {
      closeSidebar(true);
    }
  });

  desktopQuery.addEventListener("change", (event) => {
    if (event.matches) closeSidebar(false);
  });

  // Start from a consistent closed drawer on narrow screens.
  if (!desktopQuery.matches) closeSidebar(false);
})();
