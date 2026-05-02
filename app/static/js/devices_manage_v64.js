(function () {
  function initDeviceDrawer() {
    const drawer = document.querySelector("[data-device-drawer]");
    const backdrop = document.querySelector("[data-device-drawer-backdrop]");
    if (!drawer || !backdrop) return;

    const openers = document.querySelectorAll("[data-open-device-drawer]");
    const closers = document.querySelectorAll("[data-close-device-drawer]");

    function openDrawer() {
      drawer.hidden = false;
      backdrop.hidden = false;
      drawer.setAttribute("aria-hidden", "false");
      document.body.classList.add("dm64-body-lock");
    }

    function closeDrawer() {
      drawer.hidden = true;
      backdrop.hidden = true;
      drawer.setAttribute("aria-hidden", "true");
      document.body.classList.remove("dm64-body-lock");
    }

    openers.forEach((button) => {
      button.addEventListener("click", openDrawer);
    });

    closers.forEach((button) => {
      button.addEventListener("click", closeDrawer);
    });

    backdrop.addEventListener("click", closeDrawer);
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && !drawer.hidden) {
        closeDrawer();
      }
    });
  }

  document.addEventListener("DOMContentLoaded", initDeviceDrawer);
})();
