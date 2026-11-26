// Test driver for site/gander-log.js. Reads a job as JSON on stdin:
//   { logs: [{ pieces: ["text", ...], year: 2026 }], english: true, size: 30000,
//     separate: false, chunk: 0, record: { forever: { id: [from, to] } },
//     starts: ["the first characters of a file", ...] }
// and prints { data, blocks, summary, unread, ids } as JSON. Each piece is
// read by a new reader that carries on from the last one, as the page does
// for a log that grew. With separate, each log is read by itself and the
// results are merged, as the page does for a folder of logs. With chunk, the
// text arrives that many characters at a time, as it does from a large file.
// record is which logs the blocks came from; starts are named as the page
// names a log (ids).
"use strict";
const path = require("path");
const GanderLog = require(path.join(__dirname, "..", "..", "..", "..", "site", "gander-log.js"));

let input = "";
process.stdin.setEncoding("utf8");
process.stdin.on("data", (chunk) => { input += chunk; });
process.stdin.on("end", async () => {
  const job = JSON.parse(input);
  const data = GanderLog.newData();
  const unread = [];
  for (const log of job.logs) {
    const mine = job.separate ? GanderLog.newData() : data;
    let ctx = {};
    for (const piece of log.pieces) {
      const reader = new GanderLog.Reader(mine, ctx, log.year);
      if (job.chunk) {
        for (let i = 0; i < piece.length; i += job.chunk) reader.feedText(piece.slice(i, i + job.chunk));
        reader.finish();
        unread.push(reader.partial);
      } else {
        reader.feed(piece.split("\n"));
      }
      ctx = reader.ctx;
    }
    if (job.separate) GanderLog.merge(data, mine);
  }
  const options = { english: job.english !== false };
  if (job.size) options.size = job.size;
  if (job.record) options.logs = job.record;
  const ids = [];
  for (const start of job.starts || []) ids.push(await GanderLog.logId(new TextEncoder().encode(start)));
  process.stdout.write(JSON.stringify({
    data: data,
    blocks: GanderLog.blocks(data, options),
    summary: GanderLog.summary(data),
    unread: unread,
    ids: ids,
  }));
});
