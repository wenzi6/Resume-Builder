// @ts-check
/** 轻量 Toast 通知。 */

const root = document.getElementById("toastRoot");

export function toast(message, type = "info", duration = 2800) {
  if (!root) return;
  const el = document.createElement("div");
  el.className = `toast ${type}`;
  el.textContent = message;
  root.appendChild(el);
  setTimeout(() => {
    el.classList.add("leaving");
    setTimeout(() => el.remove(), 300);
  }, duration);
}

export const toastSuccess = (m) => toast(m, "success");
export const toastError = (m) => toast(m, "error", 4200);
