// The door for Gander data sent from the page (site/): a Cloudflare Worker
// that takes one submission block and files it as an issue with the
// "gander-data" label, so players don't need a GitHub account. From there the
// "Gander data" workflow checks it like any other submission.
//
// What it guards against:
// - Text. Only ids, numbers, dates and plain names reach the issue: tidy()
//   rebuilds the block from the fields the database has and drops the rest,
//   so nobody can post links, mentions or formatting under the owner's name.
//   The real checks are still gander_submit.py's.
// - Floods. One sender and all senders together are capped per day, counted
//   from the issues themselves, so there is nothing to store.
// - Other sites. Only the page's own address may call it from a browser.
//
// It knows who sent what only as a stamp: the sender's network address
// scrambled with a secret, so two submissions can be told apart (a second
// sender confirms a first) without the address ever being written down.
//
// Settings (wrangler.toml, or the Worker's settings page):
//   REPO            the repository to file issues in, "owner/name"
//   ALLOWED_ORIGIN  the page's address, "https://zaphiruz.github.io"
// Secrets (set by the repository's owner, never in a file):
//   GITHUB_TOKEN    a token that can only write issues in that repository
//   SENDER_SALT     any long random text

const LABEL = "gander-data";
const TITLE = "Gander data from the page";
const MAX_REQUEST = 80000;   // characters in a request
const SENDER_CAP = 30;       // submissions from one sender in a day
const TOTAL_CAP = 100;       // submissions from everyone in a day (one page of GitHub's list)
const DAY = 24 * 3600 * 1000;

const GAMES = ["forever", "classic"];
const ID = /^[1-9]\d{0,7}$/;
const LEVEL = /^(-1|[1-9]\d?)$/;
const KEY = /^[a-z][a-z0-9]{0,7}$/;
const DATE = /^\d{4}-\d{2}-\d{2}$/;
const BUILD = /^\d{1,3}\.\d{1,3}\.\d{1,3}$/;
const LOCALE = /^[A-Za-z]{2,8}$/;
const LOG_ID = /^[0-9a-f]{16}$/;
const MAX_LOGS = 300;        // combat logs one block may be from
const MAX_PARTS = 50;        // blocks one send may be split into
const MAX_BYTES = 2 ** 40;   // no combat log is a terabyte
const MAX_PLACES = 20;       // dungeons one mob may be listed in
// Plain words, as gander_submit.py's good_name: letters, digits, spaces and a
// little punctuation. Nothing that could be a link, a mention or formatting.
const WORDS = /^[\p{L}\p{N} '\-.,":()!]+$/u;
const LETTER = /\p{L}/u;

function isObject(value) {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isNumber(value) {
  return typeof value === "number" && Number.isFinite(value);
}

function isCount(value) {
  return Number.isInteger(value) && value > 0 && value <= 1e9;
}

function goodName(text, limit) {
  return typeof text === "string" && text.length > 0 && text.length <= limit && text === text.trim() &&
    !text.includes("  ") && LETTER.test(text) && WORDS.test(text);
}

// The block again, with only what the database can hold. Returns null if
// that leaves nothing.
export function tidy(sub) {
  if (!isObject(sub) || sub.format !== 1 || !GAMES.includes(sub.game)) return null;
  const out = { format: 1, game: sub.game };
  if (typeof sub.locale === "string" && LOCALE.test(sub.locale)) out.locale = sub.locale;
  out.mobs = {};
  out.spells = {};
  out.instances = {};
  const cast = new Set();

  for (const [id, mob] of Object.entries(isObject(sub.mobs) ? sub.mobs : {}).slice(0, 5000)) {
    if (!ID.test(id) || !isObject(mob)) continue;
    const kept = {};
    if (goodName(mob.name, 40)) kept.name = mob.name;
    const levels = {};
    for (const [level, seen] of Object.entries(isObject(mob.levels) ? mob.levels : {})) {
      if (!LEVEL.test(level) || !isObject(seen) || !isNumber(seen.at) || !isObject(seen.v)) continue;
      const values = {};
      for (const [key, value] of Object.entries(seen.v)) {
        if (KEY.test(key) && (isNumber(value) || goodName(value, 40))) values[key] = value;
      }
      if (Object.keys(values).length) levels[level] = { at: seen.at, v: values };
    }
    const spells = {};
    for (const [spell, seen] of Object.entries(isObject(mob.spells) ? mob.spells : {})) {
      if (!ID.test(spell) || !isObject(seen) || !isCount(seen.n) || typeof seen.at !== "string" || !DATE.test(seen.at)) continue;
      const one = { n: seen.n, spawns: isCount(seen.spawns) ? seen.spawns : 1, at: seen.at };
      if (typeof seen.build === "string" && BUILD.test(seen.build)) one.build = seen.build;
      spells[spell] = one;
      cast.add(spell);
    }
    if (Object.keys(levels).length) kept.levels = levels;
    if (Object.keys(spells).length) kept.spells = spells;
    // The dungeons it was logged in: instance IDs, never names.
    const places = [...new Set((Array.isArray(mob.in) ? mob.in : []).filter((place) => typeof place === "string" && ID.test(place)))];
    if (places.length) kept.in = places.slice(0, MAX_PLACES);
    if (kept.levels || kept.spells) out.mobs[id] = kept;
  }
  for (const [spell, name] of Object.entries(isObject(sub.spells) ? sub.spells : {})) {
    if (ID.test(spell) && cast.has(spell) && goodName(name, 60)) out.spells[spell] = name;
  }
  for (const [id, entry] of Object.entries(isObject(sub.instances) ? sub.instances : {}).slice(0, 500)) {
    if (!ID.test(id) || !isObject(entry) || !isNumber(entry.minutes) || entry.minutes <= 0) continue;
    out.instances[id] = { minutes: entry.minutes };
    if (goodName(entry.name, 40)) out.instances[id].name = entry.name;
  }
  if (!Object.keys(out.mobs).length && !Object.keys(out.instances).length) return null;
  if ("logs" in sub) {
    const record = tidyLogs(sub);
    if (!record) return null;
    Object.assign(out, record);
  }
  return out;
}

function isWhole(value, low, high) {
  return Number.isInteger(value) && value >= low && value <= high;
}

// Which combat logs a block came from, and which bytes of each: the checker
// uses it to count no part of a log twice. A record that isn't right refuses
// the whole block, as gander_submit.py's clean_logs does: passing the block
// on without it would let the same casts be counted again.
function tidyLogs(sub) {
  if (!isObject(sub.logs)) return null;
  const spans = Object.entries(sub.logs);
  if (!spans.length || spans.length > MAX_LOGS) return null;
  const logs = {};
  for (const [id, span] of spans) {
    if (!LOG_ID.test(id) || !Array.isArray(span) || span.length !== 2 ||
        !isWhole(span[0], 0, MAX_BYTES) || !isWhole(span[1], 1, MAX_BYTES) || span[0] >= span[1]) return null;
    logs[id] = [span[0], span[1]];
  }
  const record = { logs };
  for (const key of ["part", "parts"]) {
    if (!(key in sub)) continue;
    if (!isWhole(sub[key], 1, MAX_PARTS)) return null;
    record[key] = sub[key];
  }
  if ((record.part || 1) > (record.parts || 1)) return null;
  return record;
}

// A sender's network address, scrambled with the secret salt.
async function stampFor(salt, address) {
  const text = new TextEncoder();
  const key = await crypto.subtle.importKey("raw", text.encode(salt), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const mac = new Uint8Array(await crypto.subtle.sign("HMAC", key, text.encode("gander-sender:" + address)));
  return Array.from(mac.slice(0, 10), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

function headersFor(env) {
  return {
    "Access-Control-Allow-Origin": env.ALLOWED_ORIGIN || "",
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Max-Age": "86400",
    "Vary": "Origin",
    "Cache-Control": "no-store",
  };
}

function answer(env, status, body) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { ...headersFor(env), "Content-Type": "application/json; charset=utf-8" },
  });
}

function refuse(env, status, error) {
  return answer(env, status, { ok: false, error });
}

async function github(env, path, init = {}) {
  const call = env.fetch || fetch;
  return call(`https://api.github.com/repos/${env.REPO}${path}`, {
    ...init,
    headers: {
      Authorization: `Bearer ${env.GITHUB_TOKEN}`,
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
      "User-Agent": "gander-data-worker",
      ...(init.body ? { "Content-Type": "application/json" } : {}),
    },
  });
}

async function submit(request, env) {
  if (!env.GITHUB_TOKEN || !env.SENDER_SALT || !env.REPO) {
    return refuse(env, 503, "Sending isn't set up yet. Use the GitHub form for now.");
  }
  if (!env.ALLOWED_ORIGIN || request.headers.get("Origin") !== env.ALLOWED_ORIGIN) {
    return refuse(env, 403, "This only takes submissions from the GanderData page.");
  }
  const text = await request.text();
  if (text.length > MAX_REQUEST) return refuse(env, 413, "That is too much for one submission. Send it in smaller blocks.");
  let block = null;
  try {
    const payload = JSON.parse(text);
    block = tidy(JSON.parse(payload.block));
  } catch (e) {
    block = null;
  }
  if (!block) return refuse(env, 400, "That isn't a Gander data block, or nothing in it could be used.");

  const now = env.now ? env.now() : Date.now();
  const stamp = await stampFor(env.SENDER_SALT, request.headers.get("CF-Connecting-IP") || "unknown");
  block.sender = stamp;

  const recent = await github(env, `/issues?labels=${LABEL}&state=all&sort=created&direction=desc&per_page=100`);
  if (!recent.ok) return refuse(env, 502, "Couldn't reach the database just now. Try again in a few minutes.");
  const today = (await recent.json()).filter((issue) => now - Date.parse(issue.created_at) < DAY);
  const mine = today.filter((issue) => typeof issue.body === "string" && issue.body.includes(`"sender":"${stamp}"`));
  if (mine.length >= SENDER_CAP || today.length >= TOTAL_CAP) {
    return refuse(env, 429, "The database has had a lot sent to it today. Your data is safe on your computer: send it tomorrow.");
  }

  const created = await github(env, "/issues", {
    method: "POST",
    body: JSON.stringify({ title: TITLE, labels: [LABEL], body: "### Data\n\n```text\n" + JSON.stringify(block) + "\n```\n" }),
  });
  if (!created.ok) return refuse(env, 502, "Couldn't reach the database just now. Try again in a few minutes.");
  const issue = await created.json();
  return answer(env, 200, { ok: true, number: issue.number, url: issue.html_url });
}

export default {
  async fetch(request, env) {
    env = env || {};
    try {
      if (request.method === "OPTIONS") return new Response(null, { status: 204, headers: headersFor(env) });
      if (request.method === "POST") return await submit(request, env);
      if (request.method === "GET") {
        // "logs" says this version passes on the record of combat logs.
        return answer(env, 200, {
          ok: true, service: "gander-data", ready: Boolean(env.GITHUB_TOKEN && env.SENDER_SALT && env.REPO), logs: true,
        });
      }
      return refuse(env, 405, "Send submissions with POST.");
    } catch (e) {
      return refuse(env, 500, "Something went wrong on our side. Try again in a few minutes.");
    }
  },
};
