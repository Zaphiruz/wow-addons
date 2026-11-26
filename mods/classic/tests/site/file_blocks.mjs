// Test driver for worker/gander-worker.mjs. Reads a JSON list of submission
// blocks (texts) on stdin, sends each through the Worker with GitHub faked,
// and prints for each: { status, body } where body is the text of the issue
// the Worker would have opened (null if it refused).
import worker from "../../../../worker/gander-worker.mjs";

let input = "";
process.stdin.setEncoding("utf8");
for await (const chunk of process.stdin) input += chunk;

const ORIGIN = "https://page.example";
const out = [];
for (const block of JSON.parse(input)) {
  let filed = null;
  const env = {
    GITHUB_TOKEN: "test-token", SENDER_SALT: "test-salt", REPO: "Someone/some-repo", ALLOWED_ORIGIN: ORIGIN,
    fetch: async (url, init = {}) => {
      if ((init.method || "GET") === "GET") return new Response("[]", { status: 200 });
      filed = JSON.parse(init.body);
      return new Response(JSON.stringify({ number: 1, html_url: "https://github.com/Someone/some-repo/issues/1" }), { status: 201 });
    },
  };
  const response = await worker.fetch(new Request("https://worker.example/", {
    method: "POST",
    headers: { "Content-Type": "application/json", Origin: ORIGIN, "CF-Connecting-IP": "203.0.113.7" },
    body: JSON.stringify({ block }),
  }), env);
  out.push({ status: response.status, body: filed ? filed.body : null, labels: filed ? filed.labels : null });
}
process.stdout.write(JSON.stringify(out));
