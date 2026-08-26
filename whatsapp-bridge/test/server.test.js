"use strict";
/**
 * Exercises src/server.js's HTTP layer (auth, validation, status codes)
 * against a fake `wa` module — no real Baileys/WhatsApp connection needed
 * or possible in CI/sandbox. Run: node test/server.test.js
 */
const assert = require("node:assert");
const http = require("node:http");
const { createApp } = require("../src/server");

const TOKEN = "test-shared-secret";

function makeFakeWa(overrides = {}) {
  return Object.assign({
    getStatus: () => ({ state: "connected", connected: true, phone: "9647708814323", last_error: null }),
    getQrPngBuffer: async () => null,
    sendText: async (to, message) => ({ message_id: "WA_FAKE_ID_1" }),
    logout: async () => {},
  }, overrides);
}

function listen(app) {
  return new Promise((resolve) => {
    const server = app.listen(0, () => resolve(server));
  });
}

function request(server, method, path, { body, headers } = {}) {
  return new Promise((resolve, reject) => {
    const port = server.address().port;
    const data = body ? JSON.stringify(body) : null;
    const req = http.request({
      host: "127.0.0.1", port, path, method,
      headers: Object.assign(
        { "Content-Type": "application/json" },
        data ? { "Content-Length": Buffer.byteLength(data) } : {},
        headers || {},
      ),
    }, (res) => {
      let raw = "";
      res.on("data", (chunk) => { raw += chunk; });
      res.on("end", () => {
        let parsed = raw;
        try { parsed = JSON.parse(raw); } catch (e) { /* binary (PNG) or empty */ }
        resolve({ status: res.statusCode, body: parsed, headers: res.headers });
      });
    });
    req.on("error", reject);
    if (data) req.write(data);
    req.end();
  });
}

const results = [];
function ok(label, cond, extra = "") {
  results.push([label, cond]);
  console.log((cond ? "PASS " : "FAIL "), label, cond ? "" : JSON.stringify(extra));
}

async function main() {
  // ---- /health is unauthenticated ----
  {
    const app = createApp(makeFakeWa(), TOKEN);
    const server = await listen(app);
    const r = await request(server, "GET", "/health");
    ok("GET /health returns 200 with no token", r.status === 200 && r.body.status === "ok", r);
    server.close();
  }

  // ---- missing/wrong token rejected on protected routes ----
  {
    const app = createApp(makeFakeWa(), TOKEN);
    const server = await listen(app);
    const r1 = await request(server, "GET", "/status");
    ok("GET /status with no Authorization header -> 401", r1.status === 401, r1);
    const r2 = await request(server, "GET", "/status", { headers: { Authorization: "Bearer wrong-token" } });
    ok("GET /status with wrong token -> 401", r2.status === 401, r2);
    server.close();
  }

  // ---- correct token + /status reflects the wa module ----
  {
    const app = createApp(makeFakeWa(), TOKEN);
    const server = await listen(app);
    const r = await request(server, "GET", "/status", { headers: { Authorization: `Bearer ${TOKEN}` } });
    ok("GET /status with correct token -> 200", r.status === 200, r);
    ok("status body reflects fake wa.getStatus()", r.body.connected === true && r.body.phone === "9647708814323", r.body);
    server.close();
  }

  // ---- /qr returns 404 JSON when no QR pending ----
  {
    const app = createApp(makeFakeWa(), TOKEN);
    const server = await listen(app);
    const r = await request(server, "GET", "/qr", { headers: { Authorization: `Bearer ${TOKEN}` } });
    ok("GET /qr -> 404 when no QR buffer available", r.status === 404, r);
    server.close();
  }

  // ---- /qr returns a PNG when one is pending ----
  {
    const fakePng = Buffer.from([0x89, 0x50, 0x4e, 0x47]); // PNG magic bytes
    const app = createApp(makeFakeWa({ getQrPngBuffer: async () => fakePng }), TOKEN);
    const server = await listen(app);
    const r = await request(server, "GET", "/qr", { headers: { Authorization: `Bearer ${TOKEN}` } });
    ok("GET /qr -> 200 image/png when a QR is pending", r.status === 200 && r.headers["content-type"] === "image/png", r.headers);
    server.close();
  }

  // ---- /send validation ----
  {
    const app = createApp(makeFakeWa(), TOKEN);
    const server = await listen(app);
    const auth = { Authorization: `Bearer ${TOKEN}` };
    const r1 = await request(server, "POST", "/send", { headers: auth, body: { message: "hi" } });
    ok("POST /send missing 'to' -> 400", r1.status === 400, r1);
    const r2 = await request(server, "POST", "/send", { headers: auth, body: { to: "notdigits", message: "hi" } });
    ok("POST /send non-digit 'to' -> 400", r2.status === 400, r2);
    const r3 = await request(server, "POST", "/send", { headers: auth, body: { to: "9647701112233" } });
    ok("POST /send missing 'message' -> 400", r3.status === 400, r3);
    server.close();
  }

  // ---- /send success path ----
  {
    let capturedArgs = null;
    const app = createApp(makeFakeWa({
      sendText: async (to, message) => { capturedArgs = { to, message }; return { message_id: "WAMID.abc123" }; },
    }), TOKEN);
    const server = await listen(app);
    const r = await request(server, "POST", "/send", {
      headers: { Authorization: `Bearer ${TOKEN}` },
      body: { to: "9647701112233", message: "مرحباً، هذا تذكير" },
    });
    ok("POST /send success -> 200 with message_id", r.status === 200 && r.body.success === true && r.body.message_id === "WAMID.abc123", r);
    ok("sendText called with normalized 'to' and message text", capturedArgs.to === "9647701112233" && capturedArgs.message === "مرحباً، هذا تذكير", capturedArgs);
    server.close();
  }

  // ---- /send when not connected -> 503 ----
  {
    const err = new Error("WhatsApp session is not connected — scan the QR code first");
    err.code = "NOT_CONNECTED";
    const app = createApp(makeFakeWa({ sendText: async () => { throw err; } }), TOKEN);
    const server = await listen(app);
    const r = await request(server, "POST", "/send", {
      headers: { Authorization: `Bearer ${TOKEN}` },
      body: { to: "9647701112233", message: "test" },
    });
    ok("POST /send when not connected -> 503", r.status === 503 && r.body.success === false, r);
    server.close();
  }

  // ---- /send when WhatsApp rejects it -> 502 ----
  {
    const app = createApp(makeFakeWa({ sendText: async () => { throw new Error("some other failure"); } }), TOKEN);
    const server = await listen(app);
    const r = await request(server, "POST", "/send", {
      headers: { Authorization: `Bearer ${TOKEN}` },
      body: { to: "9647701112233", message: "test" },
    });
    ok("POST /send generic failure -> 502", r.status === 502 && r.body.success === false, r);
    server.close();
  }

  // ---- /logout ----
  {
    let logoutCalled = false;
    const app = createApp(makeFakeWa({ logout: async () => { logoutCalled = true; } }), TOKEN);
    const server = await listen(app);
    const r = await request(server, "POST", "/logout", { headers: { Authorization: `Bearer ${TOKEN}` } });
    ok("POST /logout -> 200 success", r.status === 200 && r.body.success === true && logoutCalled, r);
    server.close();
  }

  const failed = results.filter(([, cond]) => !cond);
  if (failed.length) {
    console.log(`\n${failed.length} CHECK(S) FAILED`);
    process.exit(1);
  } else {
    console.log(`\nALL ${results.length} WHATSAPP-BRIDGE CHECKS PASSED`);
  }
}

main().catch((e) => { console.error(e); process.exit(1); });
