/* StayBuddy – Main JavaScript */

// ── Flash alerts auto-dismiss ──────────────────────────────────────────────
document.querySelectorAll(".alert-close").forEach(btn => {
  btn.addEventListener("click", () => btn.closest(".alert").remove());
});
setTimeout(() => {
  document.querySelectorAll(".alert").forEach(el => el.remove());
}, 5000);

// ── Mobile nav toggle ──────────────────────────────────────────────────────
const navToggle = document.querySelector(".navbar-toggle");
const navLinks  = document.querySelector(".nav-links");
if (navToggle) {
  navToggle.addEventListener("click", () => navLinks.classList.toggle("open"));
}

// ── Image gallery ──────────────────────────────────────────────────────────
function switchMainPhoto(src) {
  const main = document.getElementById("main-photo");
  if (main) main.src = src;
}

// ── File upload preview ────────────────────────────────────────────────────
const photoInput = document.getElementById("photo-input");
const photoPreviewContainer = document.getElementById("photo-preview");
if (photoInput && photoPreviewContainer) {
  photoInput.addEventListener("change", function() {
    photoPreviewContainer.innerHTML = "";
    const files = Array.from(this.files);
    files.forEach(file => {
      if (!file.type.startsWith("image/")) return;
      const reader = new FileReader();
      reader.onload = e => {
        const wrap = document.createElement("div");
        wrap.className = "photo-thumb";
        const img = document.createElement("img");
        img.src = e.target.result;
        wrap.appendChild(img);
        photoPreviewContainer.appendChild(wrap);
      };
      reader.readAsDataURL(file);
    });
  });
}

// ── Confirm delete ─────────────────────────────────────────────────────────
document.querySelectorAll("[data-confirm]").forEach(el => {
  el.addEventListener("click", e => {
    if (!confirm(el.dataset.confirm)) e.preventDefault();
  });
});

// ── Smooth scroll to section ───────────────────────────────────────────────
document.querySelectorAll('a[href^="#"]').forEach(a => {
  a.addEventListener("click", e => {
    const target = document.querySelector(a.getAttribute("href"));
    if (target) { e.preventDefault(); target.scrollIntoView({ behavior: "smooth" }); }
  });
});

// ── Auto-scroll message thread to bottom ──────────────────────────────────
const msgThread = document.querySelector(".msg-thread");
if (msgThread) msgThread.scrollTop = msgThread.scrollHeight;

// ── Meeting date min = today ───────────────────────────────────────────────
const dateInput = document.querySelector('input[name="proposed_date"]');
if (dateInput) {
  const today = new Date().toISOString().split("T")[0];
  dateInput.setAttribute("min", today);
}

// ── Vacancy badge color ────────────────────────────────────────────────────
document.querySelectorAll(".vacancy-text").forEach(el => {
  const v = el.dataset.vacancy;
  if (v === "available") el.classList.add("vacancy-available");
  else if (v === "limited") el.classList.add("vacancy-limited");
  else el.classList.add("vacancy-full");
});
