// Dr. Mais Nutrition Clinic — shared API helper
// Local dev (frontend opened separately, e.g. via Live Server) talks to the
// Django dev server on :8000. In production the frontend is served by the
// same Django/WhiteNoise service as the API, so requests stay same-origin
// (empty base = relative "/api/..." calls, no CORS needed).
// Override by setting window.MAYS_API_BASE before this script loads.
const API_BASE = window.MAYS_API_BASE || (
  ["127.0.0.1", "localhost"].includes(window.location.hostname)
    ? "http://127.0.0.1:8000"
    : ""
);

const AUTH_KEYS = ["mays_token", "mays_role", "mays_name", "mays_patient_id", "mays_photo"];

const Auth = {
  // "Remember me" checked -> localStorage (persists after the browser closes).
  // Unchecked -> sessionStorage (cleared when the tab/browser closes).
  _store() {
    return localStorage.getItem("mays_token") ? localStorage : sessionStorage;
  },
  getToken() { return this._store().getItem("mays_token"); },
  getRole() { return this._store().getItem("mays_role"); },
  getName() { return this._store().getItem("mays_name"); },
  getPatientId() { return this._store().getItem("mays_patient_id"); },
  getPhotoUrl() { return this._store().getItem("mays_photo") || null; },
  isLoggedIn() { return !!this._store().getItem("mays_token"); },
  save(data, remember) {
    const store = remember ? localStorage : sessionStorage;
    const other = remember ? sessionStorage : localStorage;
    store.setItem("mays_token", data.access_token);
    store.setItem("mays_role", data.role);
    store.setItem("mays_name", data.full_name);
    if (data.patient_id) store.setItem("mays_patient_id", data.patient_id);
    else store.removeItem("mays_patient_id");
    if (data.profile_photo_url) store.setItem("mays_photo", data.profile_photo_url);
    else store.removeItem("mays_photo");
    AUTH_KEYS.forEach((k) => other.removeItem(k));
  },
  clear() {
    AUTH_KEYS.forEach((k) => { localStorage.removeItem(k); sessionStorage.removeItem(k); });
  },
  logout() {
    this.clear();
    window.location.href = rootPath() + "index.html";
  },
};

// Figures out how many "../" are needed to reach the frontend root,
// based on how deep the current page is (works for /patient/*.html, /doctor/*.html, /index.html)
function rootPath() {
  const path = window.location.pathname;
  if (path.includes("/patient/") || path.includes("/doctor/")) return "../";
  return "";
}

async function apiFetch(path, options = {}) {
  const token = Auth.getToken();
  const headers = Object.assign(
    { "Content-Type": "application/json" },
    options.headers || {}
  );
  if (token) headers["Authorization"] = "Bearer " + token;

  let res;
  try {
    res = await fetch(API_BASE + path, Object.assign({}, options, { headers }));
  } catch (e) {
    throw new Error("تعذر الاتصال بالخادم. تأكد أن الـ backend يعمل على " + API_BASE);
  }

  let data = null;
  try { data = await res.json(); } catch (e) { data = null; }

  // A 401 while we WERE sending a token means the session expired — bounce
  // to login. A 401 with no token (e.g. the login call itself with wrong
  // credentials) is just a normal error to show on the current page.
  if (res.status === 401 && token) {
    Auth.clear();
    window.location.href = rootPath() + "index.html";
    return null;
  }

  if (!res.ok) {
    throw new Error(extractErrorMessage(data));
  }
  return data;
}

// Django REST Framework returns either {"detail": "..."} (permission/auth
// errors) or field-keyed validation errors like {"phone": ["..."], ...}.
// Flatten either shape into one readable message.
function extractErrorMessage(data) {
  if (!data) return "حدث خطأ غير متوقع";
  if (typeof data.detail === "string") return data.detail;

  const parts = [];
  for (const key in data) {
    const val = data[key];
    if (Array.isArray(val)) {
      val.forEach((v) => parts.push(typeof v === "string" ? v : JSON.stringify(v)));
    } else if (typeof val === "string") {
      parts.push(val);
    }
  }
  return parts.length ? parts.join(" — ") : "حدث خطأ غير متوقع";
}

// Maps a role to its dashboard, for redirects.
function dashboardPathForRole(role) {
  if (role === "doctor") return "doctor/dashboard.html";
  if (role === "secretary") return "secretary/dashboard.html";
  return "patient/dashboard.html";
}

// Redirect helpers used at the top of protected pages.
// `allowed` may be a single role string or an array of allowed roles.
function requireRole(allowed) {
  const allowedList = Array.isArray(allowed) ? allowed : [allowed];
  if (!Auth.isLoggedIn()) {
    window.location.href = rootPath() + "index.html";
    return false;
  }
  if (!allowedList.includes(Auth.getRole())) {
    window.location.href = rootPath() + dashboardPathForRole(Auth.getRole());
    return false;
  }
  return true;
}

// Renders the topbar "user-chip" with an avatar (uploaded from /admin —
// see User.profile_photo) next to the display name. Falls back to a plain
// initial-letter circle when no photo has been uploaded.
function renderUserChip(elId, displayName) {
  const el = document.getElementById(elId);
  if (!el) return;
  const name = displayName || "";
  const photo = Auth.getPhotoUrl();
  const div = document.createElement("div");
  div.textContent = name;
  const safeName = div.innerHTML;
  const avatarHtml = photo
    ? `<img src="${API_BASE}${photo}" alt="" class="chip-avatar">`
    : `<span class="chip-avatar chip-avatar-placeholder">${(name.trim().charAt(0) || "?")}</span>`;
  el.innerHTML = avatarHtml + `<span>${safeName}</span>`;
}

// Renders the chip immediately from cached (login-time) data, then quietly
// re-fetches the current profile photo from the server and re-renders if it
// changed. This is needed because the photo is uploaded from /admin at any
// time — a page that was already logged in would otherwise keep showing the
// stale/placeholder avatar until the next login refreshed localStorage.
function refreshUserChip(elId, displayName) {
  renderUserChip(elId, displayName);
  apiFetch("/api/auth/me").then((me) => {
    if (!me) return;
    const store = Auth._store();
    if (me.profile_photo_url) store.setItem("mays_photo", me.profile_photo_url);
    else store.removeItem("mays_photo");
    renderUserChip(elId, displayName);
  }).catch(() => {});
}

function bmiBadgeClass(bmiClass) {
  switch (bmiClass) {
    case "وزن طبيعي": return "green";
    case "نقص الوزن": return "orange";
    case "زيادة الوزن": return "orange";
    case "السمنة – الدرجة الأولى": return "red";
    case "السمنة – الدرجة الثانية": return "red";
    case "السمنة – الدرجة الثالثة": return "red";
    default: return "gray";
  }
}

// Height is stored in meters on the server. The UI asks for centimeters
// because clinic staff almost always type 170 rather than 1.70.
function heightToCm(meters) {
  const m = parseFloat(meters);
  if (!m) return "";
  if (m > 3) return Math.round(m); // already cm (legacy / mistyped)
  return Math.round(m * 1000) / 10; // keep one decimal when needed (1.705 -> 170.5)
}

function heightToMeters(cmOrMeters) {
  const h = parseFloat(cmOrMeters);
  if (!h || h <= 0) return 0;
  if (h > 3) return Math.round(h) / 100;
  return h;
}

function computeBmiLocal(weight, heightCmOrM) {
  const w = parseFloat(weight) || 0;
  const h = heightToMeters(heightCmOrM);
  if (!w || !h) return { bmi: 0, bmiClass: "" };
  const bmi = Math.round((w / (h * h)) * 10) / 10;
  let bmiClass = "";
  if (bmi < 18.5) bmiClass = "نقص الوزن";
  else if (bmi < 25) bmiClass = "وزن طبيعي";
  else if (bmi < 30) bmiClass = "زيادة الوزن";
  else if (bmi < 35) bmiClass = "السمنة – الدرجة الأولى";
  else if (bmi < 40) bmiClass = "السمنة – الدرجة الثانية";
  else bmiClass = "السمنة – الدرجة الثالثة";
  return { bmi, bmiClass };
}

function computeWhrLocal(waist, hip) {
  const w = parseFloat(waist) || 0;
  const h = parseFloat(hip) || 0;
  if (!w || !h) return 0;
  return Math.round((w / h) * 100) / 100;
}

function fmtDate(iso) {
  if (!iso) return "-";
  const d = new Date(iso);
  return d.toLocaleDateString("ar-EG", { year: "numeric", month: "2-digit", day: "2-digit" });
}

function showMsg(el, text, type) {
  el.textContent = text;
  el.className = "msg " + (type || "error");
  el.style.display = "block";
}
function hideMsg(el) {
  el.style.display = "none";
}
