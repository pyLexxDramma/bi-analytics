import express from "express";
import crypto from "crypto";

const app = express();
app.disable("x-powered-by");

const WEB_PORT = Number(process.env.WEB_PORT || 4098);
const OPENCODE_URL = process.env.OPENCODE_URL || "http://opencode:4096";
const WEB_AUTH_TOKEN = (process.env.WEB_AUTH_TOKEN || "").trim();
const EMBED_ALLOWED_ORIGINS = (process.env.EMBED_ALLOWED_ORIGINS || "")
  .split(",")
  .map((value) => value.trim())
  .filter(Boolean);
const MAX_MESSAGE_LENGTH = 4000;
const rateLimits = new Map();
const API_PREFIX = "/api/v1";

app.use(express.json({ limit: "32kb" }));
app.use((req, res, next) => {
  const requestId = req.headers["x-request-id"] || crypto.randomUUID();
  req.requestId = String(requestId);
  res.setHeader("X-Request-Id", req.requestId);
  res.setHeader("X-Content-Type-Options", "nosniff");
  res.setHeader("Referrer-Policy", "no-referrer");
  res.setHeader("Cross-Origin-Opener-Policy", "same-origin");
  res.setHeader("Cross-Origin-Resource-Policy", "same-origin");
  res.setHeader("Permissions-Policy", "geolocation=(), microphone=(), camera=()");
  if (EMBED_ALLOWED_ORIGINS.length > 0) {
    res.setHeader("Content-Security-Policy", `frame-ancestors 'self' ${EMBED_ALLOWED_ORIGINS.join(" ")}`);
  } else {
    res.setHeader("X-Frame-Options", "SAMEORIGIN");
  }
  next();
});
app.use(express.static("public", { index: "index.html" }));

function isRateLimited(ip, action) {
  const now = Date.now();
  const key = `${ip}:${action}`;
  const current = rateLimits.get(key);
  const windowMs = 60_000;
  const limit = action === "chat" ? 30 : 15;

  if (!current || now - current.windowStart > windowMs) {
    rateLimits.set(key, { count: 1, windowStart: now });
    return false;
  }

  current.count += 1;
  if (current.count > limit) {
    return true;
  }
  return false;
}

function getClientIp(req) {
  const forwarded = req.headers["x-forwarded-for"];
  if (typeof forwarded === "string" && forwarded.length > 0) {
    return forwarded.split(",")[0].trim();
  }
  return req.socket.remoteAddress || "unknown";
}

function requireApiToken(req, res, next) {
  if (!WEB_AUTH_TOKEN) {
    return next();
  }

  const authorization = req.headers.authorization || "";
  const token = authorization.startsWith("Bearer ") ? authorization.slice(7).trim() : "";
  if (!token || token !== WEB_AUTH_TOKEN) {
    return sendError(res, 401, "UNAUTHORIZED", "Unauthorized");
  }
  return next();
}

function enforceJsonPost(req, res, next) {
  if (req.method !== "POST") {
    return next();
  }

  if (!req.is("application/json")) {
    return sendError(res, 415, "UNSUPPORTED_MEDIA_TYPE", "Content-Type должен быть application/json");
  }
  return next();
}

async function fetchAny(url, options = {}) {
  const ac = new AbortController();
  const t = setTimeout(() => ac.abort(), 30000);

  try {
    const r = await fetch(url, { ...options, signal: ac.signal });
    const rawText = await r.text();

    // Пытаемся распарсить JSON, но если не получилось — вернём rawText
    let json = null;
    if (rawText) {
      try { json = JSON.parse(rawText); } catch {}
    }

    return {
      ok: r.ok,
      status: r.status,
      rawText,
      json
    };
  } finally {
    clearTimeout(t);
  }
}

function extractText(parts) {
  if (!Array.isArray(parts)) return "";
  return parts
    .filter(p => p && p.type === "text" && typeof p.text === "string" && !p.ignored)
    .map(p => p.text)
    .join("");
}

function sendSuccess(res, data = {}, status = 200) {
  return res.status(status).json({ ok: true, data });
}

function sendError(res, status, code, message, details = null) {
  const payload = {
    ok: false,
    error: {
      code,
      message
    }
  };
  if (details) {
    payload.error.details = details;
  }
  return res.status(status).json(payload);
}

app.get(`${API_PREFIX}/health`, async (req, res) => {
  const r = await fetchAny(`${OPENCODE_URL}/global/health`);
  if (!r.ok) {
    return sendError(res, 502, "UPSTREAM_HEALTHCHECK_FAILED", "OpenCode healthcheck failed", {
      upstreamStatus: r.status,
      upstreamBody: r.json ?? r.rawText
    });
  }
  return sendSuccess(res, r.json ?? { rawText: r.rawText });
});

app.use(API_PREFIX, requireApiToken);
app.use(API_PREFIX, enforceJsonPost);

app.post(`${API_PREFIX}/sessions`, async (req, res) => {
  const ip = getClientIp(req);
  if (isRateLimited(ip, "session")) {
    return sendError(res, 429, "RATE_LIMITED", "Слишком много запросов на создание сессий. Попробуй позже.");
  }

  const r = await fetchAny(`${OPENCODE_URL}/session`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title: "Web session" })
  });

  if (!r.ok) {
    return sendError(res, 502, "UPSTREAM_SESSION_FAILED", "OpenCode /session failed", {
      upstreamStatus: r.status,
      upstreamBody: r.json ?? r.rawText
    });
  }

  const id = r.json?.id;
  if (!id) {
    return sendError(res, 500, "UPSTREAM_INVALID_PAYLOAD", "OpenCode вернул ответ без json.id", {
      upstreamStatus: r.status,
      upstreamBody: r.json ?? r.rawText
    });
  }

  return sendSuccess(res, { sessionId: id });
});

app.post(`${API_PREFIX}/chats/:sessionId/messages`, async (req, res) => {
  const sessionId = req.params.sessionId;
  const message = req.body?.message;
  const ip = getClientIp(req);
  if (isRateLimited(ip, "chat")) {
    return sendError(res, 429, "RATE_LIMITED", "Слишком много запросов в чат. Попробуй позже.");
  }

  if (!sessionId || !message) {
    return sendError(res, 400, "VALIDATION_ERROR", "sessionId и message обязательны");
  }

  const sessionIdValue = String(sessionId).trim();
  const messageValue = String(message).trim();
  if (!sessionIdValue) {
    return sendError(res, 400, "VALIDATION_ERROR", "Некорректный sessionId");
  }

  if (!messageValue) {
    return sendError(res, 400, "VALIDATION_ERROR", "Пустое сообщение отправлять нельзя");
  }

  if (messageValue.length > MAX_MESSAGE_LENGTH) {
    return sendError(res, 400, "VALIDATION_ERROR", `Слишком длинное сообщение. Максимум ${MAX_MESSAGE_LENGTH} символов.`);
  }

  // POST /session/:id/message (по докам возвращает { info, parts })
  const r = await fetchAny(`${OPENCODE_URL}/session/${encodeURIComponent(sessionIdValue)}/message`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      parts: [{ type: "text", text: messageValue }]
    })
  });

  if (!r.ok) {
    return sendError(res, 502, "UPSTREAM_MESSAGE_FAILED", "OpenCode /message failed", {
      upstreamStatus: r.status,
      upstreamBody: r.json ?? r.rawText
    });
  }

  const reply = extractText(r.json?.parts) || "";
  return sendSuccess(res, { reply, raw: r.json ?? { rawText: r.rawText } });
});

app.get(`${API_PREFIX}/chats/:sessionId/messages`, requireApiToken, async (req, res) => {
  const sessionId = String(req.params.sessionId || "").trim();
  const limitRaw = Number(req.query.limit || 50);
  const limit = Number.isFinite(limitRaw) ? Math.max(1, Math.min(200, Math.floor(limitRaw))) : 50;

  if (!sessionId) {
    return sendError(res, 400, "VALIDATION_ERROR", "Некорректный sessionId");
  }

  const r = await fetchAny(
    `${OPENCODE_URL}/session/${encodeURIComponent(sessionId)}/message?limit=${encodeURIComponent(String(limit))}`,
    { method: "GET" }
  );

  if (!r.ok) {
    return sendError(res, 502, "UPSTREAM_MESSAGES_FETCH_FAILED", "OpenCode messages fetch failed", {
      upstreamStatus: r.status,
      upstreamBody: r.json ?? r.rawText
    });
  }

  return sendSuccess(res, { messages: r.json?.data ?? r.json ?? [] });
});

// Legacy compatibility routes
app.get("/api/health", async (req, res) => {
  const r = await fetchAny(`${OPENCODE_URL}/global/health`);
  if (!r.ok) {
    return res.status(502).json({ error: "OpenCode healthcheck failed" });
  }
  return res.json(r.json ?? { rawText: r.rawText });
});

app.post("/api/session", requireApiToken, enforceJsonPost, async (req, res) => {
  const r = await fetchAny(`http://127.0.0.1:${WEB_PORT}/api/v1/sessions`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...(req.headers.authorization ? { Authorization: req.headers.authorization } : {}) },
    body: "{}"
  });
  if (!r.ok) {
    return res.status(r.status).json({ error: r.json?.error?.message || "Session create failed" });
  }
  return res.json({ sessionId: r.json?.data?.sessionId });
});

app.post("/api/chat", requireApiToken, enforceJsonPost, async (req, res) => {
  const { sessionId, message } = req.body || {};
  const sid = encodeURIComponent(String(sessionId || "").trim());
  const r = await fetchAny(`http://127.0.0.1:${WEB_PORT}/api/v1/chats/${sid}/messages`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...(req.headers.authorization ? { Authorization: req.headers.authorization } : {}) },
    body: JSON.stringify({ message })
  });
  if (!r.ok) {
    return res.status(r.status).json({ error: r.json?.error?.message || "Chat failed" });
  }
  return res.json({ reply: r.json?.data?.reply ?? "" });
});

app.listen(WEB_PORT, "0.0.0.0", () => {
  console.log(`Web UI: http://0.0.0.0:${WEB_PORT}`);
  console.log(`Proxying OpenCode: ${OPENCODE_URL}`);
  if (EMBED_ALLOWED_ORIGINS.length > 0) {
    console.log(`Embedding allowed for: ${EMBED_ALLOWED_ORIGINS.join(", ")}`);
  }
  if (WEB_AUTH_TOKEN) {
    console.log("API token auth: enabled");
  }
});