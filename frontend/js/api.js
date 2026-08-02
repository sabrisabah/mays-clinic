// Dr. Mais Nutrition Clinic — shared API helper
// Change this if your backend runs on a different host/port.
const API_BASE = window.MAYS_API_BASE || "http://127.0.0.1:8000";

const AUTH_KEYS = ["mays_token", "mays_role", "mays_name", "mays_patient_id"];

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
  isLoggedIn() { return !!this._store().getItem("mays_token"); },
  save(data, remember) {
    const store = remember ? localStorage : sessionStorage;
    const other = remember ? sessionStorage : localStorage;
    store.setItem("mays_token", data.access_token);
    store.setItem("mays_role", data.role);
    store.setItem("mays_name", data.full_name);
    if (data.patient_id) store.setItem("mays_patient_id", data.patient_id);
    else store.removeItem("mays_patient_id");
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

// Redirect helpers used at the top of protected pages
function requireRole(role) {
  if (!Auth.isLoggedIn()) {
    window.location.href = rootPath() + "index.html";
    return false;
  }
  if (Auth.getRole() !== role) {
    window.location.href = rootPath() + (Auth.getRole() === "doctor" ? "doctor/dashboard.html" : "patient/dashboard.html");
    return false;
  }
  return true;
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
