// Read WhatsApp channel posts with Baileys and save them as JSON for jobscraper.ingest.
//
//   node fetch_channel.js --channel "Jobs A" --link https://whatsapp.com/channel/XXXX --out ../data/jobs_a.json
//   node fetch_channel.js --channel "Jobs A" --link ... --out ... --since 2025-01-01
//   node fetch_channel.js --probe --link ...        # just print what the server returns (feasibility check)
//
// Read-only: never sends anything. First run shows a QR code to link the account (Linked devices).
// Unofficial API (against WhatsApp's ToS): use a secondary number if you care about the account.
import fs from "node:fs";
import path from "node:path";
import { parseArgs } from "node:util";
import qrcode from "qrcode-terminal";
import pino from "pino";
import makeWASocket, {
  DisconnectReason,
  fetchLatestBaileysVersion,
  getBinaryNodeChild,
  getBinaryNodeChildren,
  proto,
  useMultiFileAuthState,
} from "@whiskeysockets/baileys";

const { values: a } = parseArgs({
  options: {
    channel: { type: "string" },
    link: { type: "string" }, // https://whatsapp.com/channel/<code>, the bare code, or a ...@newsletter id
    out: { type: "string" },
    since: { type: "string", default: "2025-01-01" },
    batch: { type: "string", default: "100" },
    delay: { type: "string", default: "2500" }, // ms between requests
    follow: { type: "boolean", default: false }, // follow the channel first if the account doesn't
    probe: { type: "boolean", default: false },
    fresh: { type: "boolean", default: false }, // ignore an existing --out file
  },
});
if (!a.link || (!a.probe && !(a.channel && a.out))) {
  console.error("need --link, and --channel + --out (or --probe). See the header of this file.");
  process.exit(1);
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const AUTH_DIR = path.join(path.dirname(new URL(import.meta.url).pathname), "auth");

async function connect() {
  const { state, saveCreds } = await useMultiFileAuthState(AUTH_DIR);
  const { version } = await fetchLatestBaileysVersion();
  return new Promise((resolve, reject) => {
    const open = () => {
      const sock = makeWASocket({ version, auth: state, logger: pino({ level: "silent" }), syncFullHistory: false });
      sock.ev.on("creds.update", saveCreds);
      sock.ev.on("connection.update", ({ connection, lastDisconnect, qr }) => {
        if (qr) {
          console.log("Scan this QR in WhatsApp > Linked devices > Link a device:");
          qrcode.generate(qr, { small: true });
        }
        if (connection === "open") resolve(sock);
        if (connection === "close") {
          const code = lastDisconnect?.error?.output?.statusCode;
          if (code === DisconnectReason.loggedOut) reject(new Error("logged out; delete collector/auth and relink"));
          else open(); // includes the restart WhatsApp requires right after pairing (515)
        }
      });
    };
    open();
  });
}

function inviteCode(link) {
  const m = link.match(/channel\/([\w-]+)/);
  return m ? m[1] : link;
}

function textOf(msg) {
  const m = msg || {};
  return (
    m.conversation ||
    m.extendedTextMessage?.text ||
    m.imageMessage?.caption ||
    m.videoMessage?.caption ||
    m.documentMessage?.caption ||
    ""
  ).trim();
}

// The reply is a raw node: <messages><message server_id=.. t=..><plaintext>protobuf</plaintext></message>...
function parseMessages(result) {
  const container = getBinaryNodeChild(result, "messages") || result;
  const out = [];
  for (const node of getBinaryNodeChildren(container, "message")) {
    const plain = getBinaryNodeChild(node, "plaintext");
    if (!plain?.content) continue;
    const buf = typeof plain.content === "string" ? Buffer.from(plain.content, "binary") : Buffer.from(plain.content);
    let msg;
    try {
      msg = proto.Message.decode(buf);
    } catch {
      continue;
    }
    const obj = proto.Message.toObject(msg, { defaults: false });
    out.push({
      serverId: Number(node.attrs.server_id),
      ts: Number(node.attrs.t),
      text: textOf(obj),
      kind: Object.keys(obj).join("+") || "empty",
    });
  }
  return out;
}

// A request that never answers would hang the script silently, so give each one a deadline.
const withTimeout = (promise, ms, what) =>
  Promise.race([promise, new Promise((_, rej) => setTimeout(() => rej(new Error(`${what}: no reply in ${ms / 1000}s`)), ms))]);

// Compact view of a raw node, to see what the server really returned.
const shape = (n, depth = 0) =>
  n && typeof n === "object" && n.tag
    ? `<${n.tag} ${JSON.stringify(n.attrs ?? {})}${Array.isArray(n.content) && depth < 3 ? ">" + n.content.map((c) => shape(c, depth + 1)).join("") : n.content ? ` content=${n.content.length}B` : ""}>`
    : "";

// The server answers a `messages` query sent to s.whatsapp.net (the old `message_updates`
// query addressed to the channel itself is never answered). Paging goes backwards with `before`.
const fetchPage = async (jid, count, { since, after, before } = {}) => {
  const attrs = { type: "jid", jid, count: String(count) };
  if (since) attrs.since = String(since);
  if (after) attrs.after = String(after);
  if (before) attrs.before = String(before);
  const raw = await withTimeout(
    sock.query({ tag: "iq", attrs: { id: sock.generateMessageTag(), to: "s.whatsapp.net", type: "get", xmlns: "newsletter" }, content: [{ tag: "messages", attrs }] }),
    30000,
    "fetch messages"
  );
  const msgs = parseMessages(raw);
  if (!msgs.length) console.log("  empty/unparsed reply:", shape(raw) || JSON.stringify(raw)?.slice(0, 300));
  return msgs;
};

const day = (ts) => (Number.isFinite(ts) && ts > 0 ? new Date(ts * 1000).toISOString().slice(0, 10) : null);

function save(file, posts, channel) {
  const rows = [...posts.values()]
    .sort((x, y) => x.serverId - y.serverId)
    .map((p) => ({ channel, date: day(p.ts), text: p.text, id: p.serverId }));
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file + ".tmp", JSON.stringify(rows, null, 2));
  fs.renameSync(file + ".tmp", file);
  return rows;
}

const sock = await connect();
const meta = await withTimeout(sock.newsletterMetadata("invite", inviteCode(a.link)), 30000, "channel lookup");
if (!meta) throw new Error("channel not found for that link");
const jid = meta.id;
const name = meta.name?.text ?? meta.name ?? meta.thread_metadata?.name?.text ?? "?";
console.log(`channel: ${name} (${jid}), subscribers: ${meta.subscribers ?? meta.thread_metadata?.subscribers_count ?? "?"}, you: ${meta.viewer_metadata?.role ?? meta.viewer_metadata?.mute ?? "?"}`);
if (a.probe) console.log("metadata keys:", Object.keys(meta).join(", "), "| viewer:", JSON.stringify(meta.viewer_metadata), "| state:", JSON.stringify(meta.state));
if (a.follow) {
  console.log("following channel...");
  await withTimeout(sock.newsletterFollow(jid), 30000, "follow");
}

const batch = Number(a.batch);
const since = Math.floor(new Date(a.since).getTime() / 1000);

if (a.probe) {
  console.log("requesting newest ...");
  const newest = await fetchPage(jid, 5);
  console.log(`newest: ${newest.length} msgs`, newest.map((m) => `${m.serverId}@${m.ts ? day(m.ts) : "?"}`).join(" "));
  if (newest.length) {
    const oldestId = Math.min(...newest.map((m) => m.serverId));
    await sleep(Number(a.delay));
    console.log(`requesting 5 before ${oldestId} ...`);
    const older = await fetchPage(jid, 5, { before: oldestId });
    console.log(`older: ${older.length} msgs`, older.map((m) => `${m.serverId}@${m.ts ? day(m.ts) : "?"}`).join(" "));
    console.log("sample text:", JSON.stringify(newest[0].text.slice(0, 200)));
  }
  process.exit(0);
}

const posts = new Map(); // serverId -> post
if (!a.fresh && fs.existsSync(a.out)) {
  // Only entries this script wrote (they carry a server id); a file from the phone scraper has none.
  const saved = JSON.parse(fs.readFileSync(a.out, "utf8"));
  for (const r of saved.filter((r) => Number.isFinite(r.id))) posts.set(r.id, { serverId: r.id, ts: r.date ? Date.parse(r.date) / 1000 : NaN, text: r.text });
  console.log(`resuming with ${posts.size} saved posts` + (saved.length > posts.size ? ` (ignored ${saved.length - posts.size} entries without an id)` : ""));
}

let stopping = false;
process.on("SIGINT", () => (stopping = true)); // finish the current request, save, exit

// Page backwards from the newest post until --since is passed or nothing older comes back.
// `seen` holds every message id, including ones without text (images, reactions...), so those
// don't look "new" on every page; `before` always moves to the oldest id returned.
const seen = new Set(posts.keys());
let before = posts.size ? Math.min(...posts.keys()) : undefined;
while (!stopping) {
  const msgs = await fetchPage(jid, batch, { before });
  const fresh = msgs.filter((m) => !seen.has(m.serverId));
  const noText = {};
  for (const m of msgs) if (!m.text) noText[m.kind] = (noText[m.kind] || 0) + 1;
  if (msgs.length) {
    const ids = msgs.map((m) => m.serverId);
    const ts = msgs.map((m) => m.ts);
    console.log(`  page: ${msgs.length} msgs (${fresh.length} unseen), ids ${Math.min(...ids)}..${Math.max(...ids)}, ${day(Math.min(...ts))}..${day(Math.max(...ts))}, without text: ${JSON.stringify(noText)}`);
  }
  if (!fresh.length) break;
  for (const m of fresh) {
    seen.add(m.serverId);
    if (m.text) posts.set(m.serverId, m);
  }
  const oldest = Math.min(...fresh.map((m) => m.serverId));
  if (before !== undefined && oldest >= before) break; // no progress; avoid looping forever
  before = oldest;
  const rows = save(a.out, posts, a.channel);
  console.log(`${rows.length} posts, back to ${rows[0]?.date}`);
  if (fresh.every((m) => m.ts && m.ts < since)) break;
  await sleep(Number(a.delay));
}
const rows = save(a.out, posts, a.channel);
console.log(`saved ${rows.length} posts to ${a.out}${stopping ? " (interrupted; run again to resume)" : ""}`);
process.exit(0);
