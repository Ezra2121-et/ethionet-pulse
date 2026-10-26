"use strict";

(function () {
  const STORAGE_KEY = "ethionet-pulse-theme";

  function setTheme(theme) {
    const selected = theme === "light" ? "light" : "dark";
    document.documentElement.dataset.theme = selected;
    const isDark = selected === "dark";
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.content = isDark ? "#0c1210" : "#f5f7f5";

    document.querySelectorAll("[data-theme-toggle], #theme-toggle, #theme-toggle-settings")
      .forEach((button) => {
        const action = isDark ? "light" : "dark";
        const label = isDark ? "Light mode" : "Dark mode";
        button.setAttribute("aria-label", `Switch to ${action} theme`);
        button.title = `Switch to ${action} theme`;
        const icon = button.querySelector(".theme-toggle-icon");
        const text = button.querySelector("[data-theme-label], #theme-toggle-label, #theme-toggle-settings-label");
        if (icon) icon.textContent = isDark ? "☀" : "☾";
        if (text) text.textContent = label;
      });

    window.dispatchEvent(new CustomEvent("ethionet-theme-change", {
      detail: { theme: selected },
    }));
  }

  let initialTheme = "dark";
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    if (stored === "light" || stored === "dark") initialTheme = stored;
  } catch (_error) {
    // Keep dark mode as the default when storage is unavailable.
  }
  setTheme(initialTheme);

  document.addEventListener("click", (event) => {
    const button = event.target.closest("[data-theme-toggle], #theme-toggle, #theme-toggle-settings");
    if (!button) return;
    event.preventDefault();
    const nextTheme = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    setTheme(nextTheme);
    try {
      window.localStorage.setItem(STORAGE_KEY, nextTheme);
    } catch (_error) {
      // Theme switching remains available until this page is closed.
    }
  });
})();