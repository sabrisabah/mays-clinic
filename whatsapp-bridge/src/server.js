"use strict";
/**
 * Tiny internal HTTP API in front of ./whatsapp.js. This is the only thing
 * the Django backend talks to — it never touches Baileys directly.
 *
 * Every route requires "Authorization: Bearer <WA_BRIDGE_TOKEN>" (shared
 * secret, set as an env var on both this service and the Django service).
 * This service has no public Railway domain — it's reached only over
 * Railway's private network — the token is a second layer of defense, not
 * the only one.
 */
const express = require("express");

function createApp(wa, token) {
  const app = express();
  app.use(express.json());

  // Unauthenticated healthcheck for Railway — deliberately reveals nothing
  // about connection state (that's what GET /status, behind the token, is
  // for) so a public network scan of this endpoint learns nothing useful.
  app.get("/health", (req, res) => res.json({ status: "ok" }));

  app.use((req, res, next) => {
    const header = req.headers.authorization || "";
    const provided = header.startsWith("Bearer ") ? header.slice(7) : "";
    if (!token || provided !== token) {
      return res.status(401).json({ detail: "unauthorized" });
    }
    next();
  });

  app.get("/status", (req, res) => {
    res.json(wa.getStatus());
  });

  app.get("/qr", async (req, res) => {
    try {
      const buf = await wa.getQrPngBuffer();
      if (!buf) {
        return res.status(404).json({ detail: "no QR available right now (already connected, or not generated yet)" });
      }
      res.set("Content-Type", "image/png");
      res.send(buf);
    } catch (e) {
      res.status(500).json({ detail: "failed to render QR", error: String(e && e.message || e) });
    }
  });

  app.post("/send", async (req, res) => {
    const { to, message } = req.body || {};
    if (!to || typeof to !== "string" || !/^\d{8,15}$/.test(to)) {
      return res.status(400).json({ success: false, error: "invalid or missing 'to' (expected digits-only phone, e.g. 9647501234567)" });
    }
    if (!message || typeof message !== "string" || !message.trim()) {
      return res.status(400).json({ success: false, error: "missing 'message'" });
    }
    try {
      const result = await wa.sendText(to, message);
      res.json({ success: true, message_id: result.message_id });
    } catch (e) {
      const status = e && e.code === "NOT_CONNECTED" ? 503 : 502;
      res.status(status).json({ success: false, error: String(e && e.message || e) });
    }
  });

  app.post("/logout", async (req, res) => {
    try {
      await wa.logout();
      res.json({ success: true });
    } catch (e) {
      res.status(500).json({ success: false, error: String(e && e.message || e) });
    }
  });

  return app;
}

module.exports = { createApp };

if (require.main === module) {
  const wa = require("./whatsapp");
  const token = process.env.WA_BRIDGE_TOKEN || "";
  const port = process.env.PORT || 3000;

  if (!token) {
    // eslint-disable-next-line no-console
    console.warn("[wa-bridge] WARNING: WA_BRIDGE_TOKEN is not set — every request will be rejected with 401 until it is.");
  }

  const app = createApp(wa, token);
  app.listen(port, () => {
    // eslint-disable-next-line no-console
    console.log(`[wa-bridge] listening on :${port}`);
  });

  wa.start().catch((e) => {
    // eslint-disable-next-line no-console
    console.error("[wa-bridge] failed to start WhatsApp connection", e);
  });
}
