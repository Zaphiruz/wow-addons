// Tests for the Worker that takes submissions from the page and files them as
// issues. GitHub is faked: no request leaves this machine.
// Run: node --test worker/test/
import assert from "node:assert/strict";
import { test } from "node:test";
import worker, { tidy } from "../gander-worker.mjs";

const ORIGIN = "https://zaphiruz.github.io";
const ENV = { GITHUB_TOKEN: "test-token-value", SENDER_SALT: "test-salt", REPO: "Someone/some-repo", ALLOWED_ORIGIN: ORIGIN };
const NOW = Date.parse("2026-11-26T12:00:00Z");

const BLOCK = {
  format: 1, game: "forever", locale: "enUS",
  mobs: {
    "3238": {
      name: "Stormhide",
      levels: { "22": { at: 1795396923, v: { spd: 2, ty: "Beast", z: "The Barrens", dmin: 30.5 } }, "-1": { at: 1795396999, v: { spd: 2 } } },
      spells: { "5401": { n: 4, spawns: 2, at: "2026-11-24", build: "1.60.1" } },
    },
  },
  spells: { "5401": "Lizard Bolt" },
  instances: { "48": { minutes: 24.7, name: "Blackfathom Deeps" } },
};

// A stand-in for GitHub: remembers every request, and answers with the
// issues it was given.
function github(issues = [], fail = null) {
  const calls = [];
  const fetcher = async (url, init = {}) => {
    calls.push({ url: String(url), method: init.method || "GET", headers: init.headers || {}, body: init.body });
    if (fail) return new Response(JSON.stringify({ message: "Bad credentials for test-token-value" }), { status: fail });
    if ((init.method || "GET") === "GET") return new Response(JSON.stringify(issues), { status: 200 });
    return new Response(JSON.stringify({ number: 41, html_url: "https://github.com/Someone/some-repo/issues/41" }), { status: 201 });
  };
  return { calls, fetcher };
}

function post(payload, { origin = ORIGIN, ip = "203.0.113.7", raw = null } = {}) {
  return new Request("https://worker.example/", {
    method: "POST",
    headers: { "Content-Type": "application/json", Origin: origin, "CF-Connecting-IP": ip },
    body: raw === null ? JSON.stringify(payload) : raw,
  });
}

async function send(payload, options = {}, hub = github(), env = ENV) {
  const response = await worker.fetch(post(payload, options), { ...env, fetch: hub.fetcher, now: () => NOW });
  return { response, answer: await response.json(), hub };
}

function filed(hub) {
  const call = hub.calls.find((c) => c.method === "POST");
  return call ? JSON.parse(call.body) : null;
}

function blockIn(issue) {
  return JSON.parse(issue.body.slice(issue.body.indexOf("{"), issue.body.lastIndexOf("}") + 1));
}

function earlier(hours, sender) {
  return { created_at: new Date(NOW - hours * 3600 * 1000).toISOString(), body: `### Data\n\n{"format":1,"sender":"${sender}"}` };
}

test("a submission becomes an issue with the data label", async () => {
  const { response, answer, hub } = await send({ block: JSON.stringify(BLOCK) });
  assert.equal(response.status, 200);
  assert.deepEqual(answer, { ok: true, number: 41, url: "https://github.com/Someone/some-repo/issues/41" });
  assert.equal(response.headers.get("Access-Control-Allow-Origin"), ORIGIN);
  const create = hub.calls.find((c) => c.method === "POST");
  assert.equal(create.url, "https://api.github.com/repos/Someone/some-repo/issues");
  assert.equal(create.headers.Authorization, "Bearer test-token-value");
  const issue = filed(hub);
  assert.deepEqual(issue.labels, ["gander-data"]);
  assert.equal(issue.title, "Gander data from the page");
  const sent = blockIn(issue);
  const { sender, ...rest } = sent;
  assert.deepEqual(rest, BLOCK);
  assert.match(sender, /^[A-Za-z0-9_-]{1,64}$/);
});

test("the sender stamp tells networks apart without giving the address away", async () => {
  const first = blockIn(filed((await send({ block: JSON.stringify(BLOCK) }, { ip: "203.0.113.7" })).hub));
  const again = blockIn(filed((await send({ block: JSON.stringify(BLOCK) }, { ip: "203.0.113.7" })).hub));
  const other = blockIn(filed((await send({ block: JSON.stringify(BLOCK) }, { ip: "198.51.100.9" })).hub));
  assert.equal(first.sender, again.sender);
  assert.notEqual(first.sender, other.sender);
  const body = filed((await send({ block: JSON.stringify(BLOCK) }, { ip: "203.0.113.7" })).hub).body;
  assert.ok(!body.includes("203.0.113.7"));
  const salted = blockIn(filed((await send({ block: JSON.stringify(BLOCK) }, { ip: "203.0.113.7" }, github(),
    { ...ENV, SENDER_SALT: "another-salt" })).hub));
  assert.notEqual(first.sender, salted.sender, "the stamp must depend on the secret salt");
});

test("a sender stamp from the outside is thrown away", async () => {
  const { hub } = await send({ block: JSON.stringify({ ...BLOCK, sender: "someone-else" }) });
  assert.notEqual(blockIn(filed(hub)).sender, "someone-else");
});

test("only plain data reaches the issue", async () => {
  const nasty = {
    format: 1, game: "forever", junk: "<script>alert(1)</script>", sender: "x",
    mobs: {
      "3238": {
        name: "[click](https://evil.example) @someone",
        extra: "![image](https://evil.example/x.png)",
        levels: { "22": { at: 1795396923, v: { spd: 2, ty: "<b>Beast</b>", z: "The Barrens", "bad key!": 1, deep: { a: 1 } } }, "99x": { at: 1, v: { spd: 1 } } },
        spells: { "5401": { n: 4, spawns: 2, at: "2026-11-24", build: "1.60.1", note: "#1 @you" }, "abc": { n: 1, at: "2026-11-24" } },
      },
      "not-a-mob": { levels: { "1": { at: 1, v: { spd: 1 } } } },
    },
    spells: { "5401": "Lizard Bolt", "5402": "`code` https://evil.example" },
    instances: { "48": { minutes: 24.7, name: "@everyone" } },
  };
  const { response, hub } = await send({ block: JSON.stringify(nasty) });
  assert.equal(response.status, 200);
  const body = filed(hub).body;
  for (const bad of ["evil.example", "@someone", "@you", "@everyone", "<script", "<b>", "![", "`code`", "#1", "junk", "extra", "deep"]) {
    assert.ok(!body.includes(bad), `${bad} reached the issue`);
  }
  const sent = blockIn(filed(hub));
  assert.deepEqual(sent.mobs, {
    "3238": { levels: { "22": { at: 1795396923, v: { spd: 2, z: "The Barrens" } } },
              spells: { "5401": { n: 4, spawns: 2, at: "2026-11-24", build: "1.60.1" } } },
  });
  assert.deepEqual(sent.spells, { "5401": "Lizard Bolt" });
  assert.deepEqual(sent.instances, { "48": { minutes: 24.7 } });
});

test("tidy keeps a good block whole", () => {
  assert.deepEqual(tidy(BLOCK), BLOCK);
  assert.deepEqual(tidy({ format: 1, game: "classic", instances: { "389": { minutes: 3 } } }),
    { format: 1, game: "classic", mobs: {}, spells: {}, instances: { "389": { minutes: 3 } } });
});

test("tidy keeps the dungeons a mob was logged in, as ids only", () => {
  const cast = { "5401": { n: 1, spawns: 1, at: "2026-11-24" } };
  const sent = tidy({ format: 1, game: "forever", mobs: {
    "3238": { spells: cast, in: ["48", "33"] },
    "3239": { spells: cast, in: ["Blackfathom Deeps", "@someone", 48, null, "0", "48"] },
    "3240": { spells: cast, in: "48" },
    "3241": { spells: cast, in: Array.from({ length: 60 }, (_, i) => String(i + 1)) },
  } });
  assert.deepEqual(sent.mobs["3238"].in, ["48", "33"]);
  assert.deepEqual(sent.mobs["3239"].in, ["48"]);
  assert.equal("in" in sent.mobs["3240"], false);
  assert.equal(sent.mobs["3241"].in.length, 20);
});

test("tidy keeps the record of which combat logs a block came from", () => {
  const logs = { "0123456789abcdef": [0, 5000], "fedcba9876543210": [120, 121] };
  assert.deepEqual(tidy({ ...BLOCK, logs }), { ...BLOCK, logs });
  assert.deepEqual(tidy({ ...BLOCK, logs, part: 2, parts: 3 }), { ...BLOCK, logs, part: 2, parts: 3 });
  assert.equal("logs" in tidy(BLOCK), false);
  assert.equal("part" in tidy({ ...BLOCK, part: 2, parts: 3 }), false, "a part means nothing without logs");
});

test("a damaged record of logs refuses the whole block", () => {
  // Dropping only the record would let the same casts be counted twice.
  const id = "0123456789abcdef";
  const bad = [
    {}, "everything", [[0, 5]], { xyz: [0, 5] }, { [id.toUpperCase()]: [0, 5] }, { [id]: [5, 5] }, { [id]: [-1, 5] },
    { [id]: [0, 2 ** 41] }, { [id]: "0-5" }, { [id]: [0, 5, 9] }, { [id]: [0.5, 5] }, { [id]: [true, 5] },
    { [id]: [0, "<b>5</b>"] },
  ];
  for (const logs of bad) assert.equal(tidy({ ...BLOCK, logs }), null, JSON.stringify(logs));
  for (const more of [{ part: 0 }, { part: 3, parts: 2 }, { parts: 99 }, { part: "1" }, { parts: 1.5 }]) {
    assert.equal(tidy({ ...BLOCK, logs: { [id]: [0, 5] }, ...more }), null, JSON.stringify(more));
  }
  const many = {};
  for (let i = 0; i < 301; i++) many[i.toString(16).padStart(16, "0")] = [0, 5];
  assert.equal(tidy({ ...BLOCK, logs: many }), null, "too many logs");
});

test("what isn't a block is refused, and GitHub never hears of it", async () => {
  const cases = [
    [{ block: "not json" }, 400],
    [{ block: JSON.stringify([1, 2]) }, 400],
    [{ block: JSON.stringify({ format: 2, game: "forever", mobs: BLOCK.mobs }) }, 400],
    [{ block: JSON.stringify({ format: 1, game: "retail", mobs: BLOCK.mobs }) }, 400],
    [{ block: JSON.stringify({ format: 1, game: "forever", mobs: {} }) }, 400],
    [{ block: 12 }, 400],
    [{}, 400],
  ];
  for (const [payload, status] of cases) {
    const { response, answer, hub } = await send(payload);
    assert.equal(response.status, status, JSON.stringify(payload).slice(0, 60));
    assert.equal(answer.ok, false);
    assert.ok(answer.error.length > 10);
    assert.equal(hub.calls.length, 0);
  }
  const broken = await send(null, { raw: "{ this is not json" });
  assert.equal(broken.response.status, 400);
  const huge = await send(null, { raw: JSON.stringify({ block: "x".repeat(200000) }) });
  assert.equal(huge.response.status, 413);
  assert.equal(huge.hub.calls.length, 0);
});

test("another site's page can't use it", async () => {
  const { response, hub } = await send({ block: JSON.stringify(BLOCK) }, { origin: "https://evil.example" });
  assert.equal(response.status, 403);
  assert.equal(hub.calls.length, 0);
});

test("the browser's question before sending is answered", async () => {
  const response = await worker.fetch(new Request("https://worker.example/", { method: "OPTIONS", headers: { Origin: ORIGIN } }), ENV);
  assert.equal(response.status, 204);
  assert.equal(response.headers.get("Access-Control-Allow-Origin"), ORIGIN);
  assert.match(response.headers.get("Access-Control-Allow-Methods"), /POST/);
  assert.match(response.headers.get("Access-Control-Allow-Headers"), /Content-Type/i);
});

test("a look at the address says whether it is set up", async () => {
  const up = await worker.fetch(new Request("https://worker.example/"), ENV);
  assert.deepEqual(await up.json(), { ok: true, service: "gander-data", ready: true, logs: true });
  const down = await worker.fetch(new Request("https://worker.example/"), { REPO: "Someone/some-repo" });
  assert.deepEqual(await down.json(), { ok: true, service: "gander-data", ready: false, logs: true });
});

test("without its secrets it says so and files nothing", async () => {
  const hub = github();
  const response = await worker.fetch(post({ block: JSON.stringify(BLOCK) }), { REPO: "Someone/some-repo", ALLOWED_ORIGIN: ORIGIN, fetch: hub.fetcher });
  assert.equal(response.status, 503);
  assert.equal(hub.calls.length, 0);
});

test("one sender can't flood the list", async () => {
  const mine = blockIn(filed((await send({ block: JSON.stringify(BLOCK) })).hub)).sender;
  const full = Array.from({ length: 30 }, () => earlier(2, mine));
  const refused = await send({ block: JSON.stringify(BLOCK) }, {}, github(full));
  assert.equal(refused.response.status, 429);
  assert.match(refused.answer.error, /tomorrow/);
  assert.equal(filed(refused.hub), null);
  // Yesterday's don't count, and neither do other senders'.
  const old = Array.from({ length: 30 }, () => earlier(30, mine)).concat(Array.from({ length: 40 }, () => earlier(1, "someone-else")));
  const allowed = await send({ block: JSON.stringify(BLOCK) }, {}, github(old));
  assert.equal(allowed.response.status, 200);
});

test("everyone together can't flood it either", async () => {
  const busy = Array.from({ length: 100 }, (_, i) => earlier(3, "sender-" + i));
  const refused = await send({ block: JSON.stringify(BLOCK) }, {}, github(busy));
  assert.equal(refused.response.status, 429);
  assert.equal(filed(refused.hub), null);
});

test("when GitHub fails the sender is told, without the token", async () => {
  const { response, answer } = await send({ block: JSON.stringify(BLOCK) }, {}, github([], 401));
  assert.equal(response.status, 502);
  assert.equal(answer.ok, false);
  assert.ok(!JSON.stringify(answer).includes("test-token-value"));
});
