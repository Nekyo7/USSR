import { createReadStream, existsSync } from "node:fs";
import { readFile } from "node:fs/promises";
import http from "node:http";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const publicDir = path.join(__dirname, "public");
const demoTelemetryPath = path.join(__dirname, "data", "demo-telemetry.ndjson");

const mimeTypes = {
  ".html": "text/html; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".js": "application/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".svg": "image/svg+xml"
};

function sendFile(res, filePath) {
  const ext = path.extname(filePath);
  const contentType = mimeTypes[ext] || "application/octet-stream";
  res.writeHead(200, { "Content-Type": contentType });
  createReadStream(filePath).pipe(res);
}

function notFound(res) {
  res.writeHead(404, { "Content-Type": "text/plain; charset=utf-8" });
  res.end("Not found");
}

function streamDemoTelemetry(res) {
  res.writeHead(200, {
    "Content-Type": "text/event-stream; charset=utf-8",
    "Cache-Control": "no-cache",
    Connection: "keep-alive"
  });

  let frames = [];
  let index = 0;

  const raw = existsSync(demoTelemetryPath)
    ? readFile(demoTelemetryPath, "utf8")
    : Promise.resolve("");

  raw
    .then((text) => {
      frames = text
        .split("\n")
        .map((line) => line.trim())
        .filter(Boolean);

      if (!frames.length) {
        frames = [
          JSON.stringify({
            ts: Date.now(),
            unitId: "ALPHA-01",
            battV: 12.4,
            battPct: 86,
            solarW: 38,
            loadW: 24,
            tempC: 31.5,
            humidity: 42,
            vibration: 0.12,
            currentA: 1.9,
            signalRssi: -63,
            gpsLat: 28.6139,
            gpsLng: 77.209,
            headingDeg: 68,
            motionKph: 12,
            enclosureOpen: 0,
            smokePpm: 2,
            mode: "PATROL",
            threatTag: "LOW"
          })
        ];
      }

      const timer = setInterval(() => {
        const payload = JSON.parse(frames[index % frames.length]);
        payload.ts = Date.now();
        res.write(`data: ${JSON.stringify(payload)}\n\n`);
        index += 1;
      }, 900);

      reqCleanup(res, timer);
    })
    .catch((error) => {
      res.write(`event: error\ndata: ${JSON.stringify({ message: error.message })}\n\n`);
      res.end();
    });
}

function reqCleanup(res, timer) {
  const cleanup = () => clearInterval(timer);
  res.on("close", cleanup);
  res.on("error", cleanup);
}

const server = http.createServer((req, res) => {
  const url = new URL(req.url, "http://localhost");

  if (url.pathname === "/api/health") {
    res.writeHead(200, { "Content-Type": "application/json; charset=utf-8" });
    res.end(JSON.stringify({ ok: true, app: "apis-expo-ui" }));
    return;
  }

  if (url.pathname === "/api/demo-stream") {
    streamDemoTelemetry(res);
    return;
  }

  let filePath = path.join(publicDir, url.pathname === "/" ? "index.html" : url.pathname);
  if (!filePath.startsWith(publicDir)) {
    notFound(res);
    return;
  }

  if (!existsSync(filePath)) {
    notFound(res);
    return;
  }

  sendFile(res, filePath);
});

const port = process.env.PORT || 4173;
server.listen(port, "127.0.0.1", () => {
  console.log(`APIS Expo UI running at http://127.0.0.1:${port}`);
});
