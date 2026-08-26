"use strict";
/**
 * Owns the single Baileys (WhatsApp Web multi-device protocol) connection
 * for this clinic's WhatsApp number. No browser/Chromium involved — Baileys
 * talks the protocol directly over a websocket, the same thing that happens
 * behind the scenes when you open web.whatsapp.com and scan the QR code.
 *
 * Session credentials (produced once the QR is scanned) are written to
 * SESSION_DIR on disk so the connection survives restarts/redeploys without
 * needing to re-scan every time — until WhatsApp itself invalidates the
 * session (phone unlinked, "log out of all devices", prolonged inactivity,
 * or WhatsApp flags the number for automated-looking traffic). That's a
 * known, accepted risk of this approach (see reminders app docs) — there is
 * no officially supported alternative when not using the paid Meta Cloud
 * API.
 *
 * This module exposes a small, testable surface (getStatus/getQrPngBuffer/
 * sendText/logout) — src/server.js never touches Baileys directly.
 */
const path = require("path");
const fs = require("fs");
const QRCode = require("qrcode");
const pino = require("pino");

const SESSION_DIR = process.env.SESSION_DIR || path.join(__dirname, "..", ".session");

let sock = null;
let currentQrString = null;
let connectionState = "disconnected"; // "disconnected" | "connecting" | "waiting_for_qr" | "connected"
let connectedPhone = null;
let lastError = null;

function log(...args) {
  // eslint-disable-next-line no-console
  console.log(new Date().toISOString(), "[wa-bridge]", ...args);
}

async function start() {
  // Lazy-require so this file can be unit-tested (routing/auth logic) in an
  // environment without the real baileys package installed/network access.
  const baileys = require("@whiskeysockets/baileys");
  const makeWASocket = baileys.default || baileys.makeWASocket;
  const { useMultiFileAuthState, DisconnectReason, fetchLatestBaileysVersion } = baileys;

  fs.mkdirSync(SESSION_DIR, { recursive: true });
  const { state, saveCreds } = await useMultiFileAuthState(SESSION_DIR);
  const { version } = await fetchLatestBaileysVersion();

  connectionState = "connecting";
  sock = makeWASocket({
    version,
    auth: state,
    logger: pino({ level: "warn" }),
    printQRInTerminal: false,
    browser: ["Mays Clinic Reminders", "Chrome", "1.0"],
  });

  sock.ev.on("creds.update", saveCreds);

  sock.ev.on("connection.update", (update) => {
    const { connection, lastDisconnect, qr } = update;

    if (qr) {
      currentQrString = qr;
      connectionState = "waiting_for_qr";
      log("new QR issued — scan it from WhatsApp > Linked Devices");
    }

    if (connection === "open") {
      currentQrString = null;
      connectionState = "connected";
      connectedPhone = (sock.user && sock.user.id) ? sock.user.id.split(":")[0] : null;
      lastError = null;
      log("connected as", connectedPhone);
    }

    if (connection === "close") {
      connectionState = "disconnected";
      const statusCode = lastDisconnect && lastDisconnect.error && lastDisconnect.error.output
        ? lastDisconnect.error.output.statusCode
        : null;
      const loggedOut = statusCode === DisconnectReason.loggedOut;
      lastError = lastDisconnect && lastDisconnect.error ? String(lastDisconnect.error.message || lastDisconnect.error) : null;
      log("connection closed", { statusCode, loggedOut, lastError });

      if (loggedOut) {
        // The phone unlinked this device (or WhatsApp force-logged it out) —
        // the saved session is no longer valid. Wipe it so the next start()
        // issues a fresh QR instead of retrying with dead credentials.
        fs.rmSync(SESSION_DIR, { recursive: true, force: true });
        connectedPhone = null;
      } else {
        // Any other disconnect (network blip, server restart, etc.) —
        // reconnect automatically using the still-valid saved session.
        setTimeout(() => { start().catch((e) => log("reconnect failed", e)); }, 3000);
      }
    }
  });
}

function getStatus() {
  return {
    state: connectionState,
    connected: connectionState === "connected",
    phone: connectedPhone,
    last_error: lastError,
  };
}

async function getQrPngBuffer() {
  if (!currentQrString) return null;
  return QRCode.toBuffer(currentQrString, { width: 320, margin: 1 });
}

function toJid(phoneDigitsOnly) {
  return `${phoneDigitsOnly}@s.whatsapp.net`;
}

async function sendText(phoneDigitsOnly, message) {
  if (connectionState !== "connected" || !sock) {
    const err = new Error("WhatsApp session is not connected — scan the QR code first");
    err.code = "NOT_CONNECTED";
    throw err;
  }
  const jid = toJid(phoneDigitsOnly);
  const result = await sock.sendMessage(jid, { text: message });
  return { message_id: (result && result.key && result.key.id) || null };
}

async function logout() {
  if (sock) {
    try { await sock.logout(); } catch (e) { log("logout error (ignored)", e); }
  }
  fs.rmSync(SESSION_DIR, { recursive: true, force: true });
  connectionState = "disconnected";
  connectedPhone = null;
  currentQrString = null;
}

module.exports = { start, getStatus, getQrPngBuffer, sendText, logout, toJid };
