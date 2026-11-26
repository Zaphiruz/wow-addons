// The page: takes the block Gander made and the combat logs a player
// chooses, reads the logs with gander-log.js, shows what was found and sends
// it. Text from a log is only ever put on the page as text, never as HTML.
(function () {
  "use strict";

  var SEND_URL = window.GANDER_SEND_URL || "";   // the Worker; empty means "send by hand"
  var FORM = "https://github.com/Zaphiruz/wow-addons/issues/new?template=gander-data.yml";
  var STORE = "gander-logs-v1";      // which logs this browser has sent, and how far into each
  var REMEMBERED = 300;              // logs to remember at most
  var LOG_NAME = /^WoWCombatLog.*\.txt$/i;
  var CHUNK = 4 * 1024 * 1024;       // bytes read at a time
  var DEPTH = 4;                     // folders deep to look in a dropped folder

  var items = [];                    // the logs chosen in this visit
  var blocks = [];                   // what there is to send: { text, title, copied, delivered }
  var busy = false;                  // reading logs
  var sending = false;
  var pasting = false;               // a pasted block is on its way
  var sentPages = [];                // the blocks from Gander sent in this visit

  // The database's record of how far each combat log has been read, by
  // anyone. It is what stops a log being counted twice.
  var LOGS_URL = window.GANDER_LOGS_URL || "";
  var FRESH = 3600 * 1000;           // how long this browser's own note of a send is believed over the record
  var MAX_LOGS = 250;                // logs in one send (the checker takes 300 in a block)
  // Does what we send reach the checker with its record of logs? By hand it
  // does. Through the Worker, only if the Worker says it passes it on.
  var knowsLogs = !SEND_URL;
  var asked = null;

  function $(id) { return document.getElementById(id); }

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function some(n, one, many) { return n + " " + (n === 1 ? one : many); }

  // ---- what this browser has sent ----
  function load() {
    try {
      var saved = JSON.parse(localStorage.getItem(STORE) || "{}");
      return saved && typeof saved === "object" ? saved : {};
    } catch (e) {
      return {};
    }
  }

  function save(saved) {
    var names = Object.keys(saved).sort(function (a, b) { return (saved[a].at || 0) - (saved[b].at || 0); });
    while (names.length > REMEMBERED) delete saved[names.shift()];
    try {
      localStorage.setItem(STORE, JSON.stringify(saved));
      return true;
    } catch (e) {
      return false;
    }
  }

  // ---- what the database has had ----
  function askWorker() {
    if (!asked) {
      asked = !SEND_URL ? Promise.resolve() : fetch(SEND_URL).then(function (response) {
        return response.json();
      }).then(function (answer) {
        knowsLogs = !!(answer && answer.logs);
      }, function () { /* an older Worker, or none: carry on without */ });
    }
    return asked;
  }

  // The record, or null if it can't be had just now.
  function fetchRecord() {
    if (!LOGS_URL) return Promise.resolve(null);
    return fetch(LOGS_URL, { cache: "no-store" }).then(function (response) {
      return response.ok ? response.json() : null;
    }).then(function (record) {
      return record && record.logs && typeof record.logs === "object" ? record : null;
    }, function () {
      return null;
    });
  }

  // ---- reading ----
  // Feed a reader the bytes of a file from one place to another, a piece at
  // a time. Gives the place after the last whole line.
  function scan(file, from, to, reader, doing) {
    var decoder = new TextDecoder("utf-8");
    var position = from, last = from;
    function next() {
      if (position >= to) return Promise.resolve(last);
      return file.slice(position, Math.min(position + CHUNK, to)).arrayBuffer().then(function (buffer) {
        var bytes = new Uint8Array(buffer);
        if (!bytes.length) return last;   // the file is shorter than it said
        var newline = bytes.lastIndexOf(10);
        if (newline !== -1) last = position + newline + 1;
        position += bytes.length;
        reader.feedText(decoder.decode(bytes, { stream: true }));
        $("status").textContent = doing + " " + file.name + ": " +
          Math.round(100 * Math.min(position, to) / Math.max(to, 1)) + "%";
        return next();
      });
    }
    return next();
  }

  // Work out where to start reading a log: after what the database has had.
  //
  // The record is the truth about that, whoever sent it and from where. This
  // browser's own note of what it sent is believed over the record only for
  // a while after a send, while the record catches up; after that, a note
  // that is ahead of the record means the send never arrived, and the log is
  // read again from where the record stops.
  function place(item, record) {
    var file = item.file, mine = item.mine;
    return file.slice(0, 4096).arrayBuffer().then(function (buffer) {
      return GanderLog.logId(new Uint8Array(buffer));
    }).then(function (id) {
      item.id = id;
      var local = mine ? mine.offset : 0;
      var entry = id && record && Object.prototype.hasOwnProperty.call(record.logs, id) ? record.logs[id] : null;
      var had = entry && typeof entry.to === "number" && entry.to > 0 ? Math.min(entry.to, file.size) : 0;
      var fresh = !!mine && Date.now() - (mine.at || 0) < FRESH;
      item.start = record && knowsLogs && !fresh ? had : Math.max(local, had);
      // Which dungeon the log is in by then is known from this browser's
      // note, if the note is from before that place. If not, walk there.
      if (local <= item.start) {
        item.walkFrom = local;
        item.ctx = (mine && mine.ctx) || {};
      } else {
        item.walkFrom = 0;
        item.ctx = {};
      }
      var twin = id && items.filter(function (other) {
        return other !== item && other.id === id && other.status !== "bad";
      })[0];
      if (twin) {
        item.status = "skip";
        item.what = "The same log as " + twin.file.name;
        item.done = true;
      } else if (item.start > 0 && item.start >= file.size) {
        item.status = "skip";
        item.what = had >= file.size ? "The database already has this log" : "Already sent from this browser";
        item.done = true;
      }
    });
  }

  // Read a log from where it should start. Whole lines only: the game may
  // still be writing the last one.
  function readLog(item) {
    var file = item.file;
    var year = new Date(file.lastModified || Date.now()).getFullYear();
    var walked = Promise.resolve(item.ctx);
    if (item.walkFrom < item.start) {
      var walker = new GanderLog.Reader(GanderLog.newData(), item.ctx, year);
      walked = scan(file, item.walkFrom, item.start, walker, "Finding the place in").then(function () {
        return walker.ctx;
      });
    }
    return walked.then(function (ctx) {
      var data = GanderLog.newData();
      var reader = new GanderLog.Reader(data, ctx, year);
      return scan(file, item.start, file.size, reader, "Reading").then(function (last) {
        reader.finish();
        item.end = last;
        item.data = data;
        item.ctx = reader.ctx;
        item.lines = reader.lines;
      });
    });
  }

  function describe(item) {
    var found = GanderLog.summary(item.data);
    if (item.lines === 0) return item.start ? ["skip", "Nothing new in it since last time"] : ["bad", "This isn't a combat log"];
    if (!item.ctx.game || !/^(forever|classic)$/.test(item.ctx.game)) {
      return ["bad", "Not a Classic Era or Forever log"];
    }
    if (!found.length) return ["skip", "Nothing for the database in it"];
    var parts = [];
    found.forEach(function (game) {
      game.instances.forEach(function (instance) {
        parts.push((instance.name || "A dungeon") + ", " + Math.max(1, Math.round(instance.minutes)) + " min");
      });
      if (!game.instances.length) parts.push(item.ctx.instance_name || "Open world");
      parts.push(game.mobs ? "casts for " + some(game.mobs, "mob", "mobs") : "no casts");
    });
    return ["new", (item.start ? "New since last time: " : "") + parts.join(" \u00b7 ")];
  }

  // One send holds so many logs. The rest wait for the next one.
  function holdBack() {
    var count = {};
    items.forEach(function (item) {
      if (item.status !== "new") return;
      var game = item.ctx.game;
      count[game] = (count[game] || 0) + 1;
      if (count[game] > MAX_LOGS) {
        item.status = "skip";
        item.what = "Next time: " + MAX_LOGS + " logs go in one send. Drop the folder again after this one";
        item.done = true;
      }
    });
  }

  function addFiles(files) {
    if (busy || sending) return Promise.resolve();
    var saved = load();
    var fresh = [];
    Array.prototype.forEach.call(files, function (file) {
      if (!LOG_NAME.test(file.name)) return;
      if (fresh.some(function (item) { return item.file.name === file.name; })) return;
      // Chosen again in the same visit: it may have grown, so look at it afresh.
      items = items.filter(function (item) { return item.file.name !== file.name; });
      var before = saved[file.name];
      var item = { file: file, start: 0, ctx: {}, status: "wait", what: "Waiting", mine: null };
      if (before && typeof before.offset === "number" && before.offset <= file.size) item.mine = before;
      items.push(item);
      fresh.push(item);
    });
    if (!fresh.length) {
      $("status").textContent = files.length
        ? "No combat logs in what you chose. They are named WoWCombatLog-(date).txt."
        : "";
      return Promise.resolve();
    }
    items.sort(function (a, b) { return a.file.name < b.file.name ? -1 : 1; });
    busy = true;
    $("thanks").hidden = true;
    render();
    $("status").textContent = "Asking the database which logs it has...";
    var record = null;
    var chain = askWorker().then(fetchRecord).then(function (found) { record = found; });
    fresh.forEach(function (item) {
      chain = chain.then(function () {
        return place(item, record);
      }).then(function () {
        if (item.done) return render();
        return readLog(item).then(function () {
          var result = describe(item);
          item.status = result[0];
          item.what = result[1];
          render();
        });
      }).then(null, function () {
        item.status = "bad";
        item.what = "Couldn't read this file";
        render();
      });
    });
    return chain.then(function () {
      holdBack();
      busy = false;
      $("status").textContent = record || !LOGS_URL ? "" :
        "Couldn't ask the database which logs it has, so this went by what this browser remembers.";
      render();
    });
  }

  // ---- the block pasted from Gander ----
  // The pasted text if it is a block, "" if the box is empty, null if it
  // is something else.
  function statsBlock() {
    var text = $("stats-box").value.trim();
    if (!SEND_URL || !text || pasting) return "";
    try {
      var sub = JSON.parse(text);
      if (sub && sub.format === 1 && /^(forever|classic)$/.test(sub.game) && typeof sub.mobs === "object") return text;
    } catch (e) { /* not a block */ }
    return null;
  }

  // ---- showing ----
  function fromLogs() {
    var data = GanderLog.newData();
    items.forEach(function (item) { if (item.status === "new") GanderLog.merge(data, item.data); });
    return data;
  }

  // Which bytes of which logs the data is from, for each game: it goes in
  // the blocks, and the database's record moves on by it.
  function spans() {
    var out = {};
    items.forEach(function (item) {
      if (item.status !== "new" || !item.id || !(item.end > item.start)) return;
      var game = item.ctx.game;
      out[game] = out[game] || {};
      out[game][item.id] = [item.start, item.end];
    });
    return out;
  }

  function render() {
    var list = $("list");
    list.textContent = "";
    list.hidden = !items.length;
    items.forEach(function (item) {
      var row = el("li", item.status);
      row.appendChild(el("span", "name", item.file.name));
      row.appendChild(el("span", "what", item.what));
      list.appendChild(row);
    });
    renderBlocks();
  }

  function renderBlocks() {
    var data = fromLogs();
    var logBlocks = busy ? [] : GanderLog.blocks(data, { english: !$("not-english").checked, logs: spans() });
    var stats = statsBlock();
    $("stats-note").textContent = stats === null
      ? "That doesn't look like the block from /gander send. Copy all of it, from { to }."
      : "";

    var old = {};
    blocks.forEach(function (block) { old[block.text] = block; });
    blocks = [];
    if (stats) blocks.push({ text: stats, title: "Stats from Gander", stats: true });
    logBlocks.forEach(function (text, i) {
      blocks.push({ text: text, title: logBlocks.length > 1
        ? "Combat logs, block " + (i + 1) + " of " + logBlocks.length : "Combat logs" });
    });
    blocks.forEach(function (block) {
      if (old[block.text]) { block.copied = old[block.text].copied; block.delivered = old[block.text].delivered; }
    });

    $("send").hidden = !blocks.length;
    if (!blocks.length) return;

    var mobs = 0, runs = 0, parts = [];
    GanderLog.summary(data).forEach(function (game) { mobs += game.mobs; runs += game.instances.length; });
    if (stats) parts.push("your stats from Gander");
    if (logBlocks.length) {
      parts.push("casts for " + some(mobs, "mob", "mobs") + (runs ? " and time in " + some(runs, "dungeon", "dungeons") : ""));
    }
    $("total").textContent = "Ready to send: " + parts.join(", and ") + ". That is " +
      some(blocks.length, "block", "blocks") + ".";

    $("auto").hidden = !SEND_URL;
    $("manual").open = !SEND_URL || $("manual").open;
    $("manual-title").textContent = SEND_URL ? "See exactly what will be sent, or send it by hand" : "Send by hand";

    var holder = $("blocks");
    holder.textContent = "";
    blocks.forEach(function (block, i) {
      var card = el("div", "block");
      card.appendChild(el("h3", "", block.title));
      var box = el("textarea");
      box.readOnly = true;
      box.value = block.text;
      box.setAttribute("aria-label", block.title + ": exactly what will be sent");
      card.appendChild(box);
      var row = el("p", "buttons");
      var copy = el("button", "", "Copy");
      copy.type = "button";
      var done = el("span", "done", block.delivered ? "Sent." : "");
      copy.addEventListener("click", function () {
        copyText(box).then(function (ok) {
          done.textContent = ok ? "Copied. Now paste it into the form." : "Select the text and copy it yourself.";
          blocks[i].copied = true;
          wake();
        });
      });
      var link = el("a", "", "Open the GitHub form");
      link.href = FORM;
      link.target = "_blank";
      link.rel = "noopener";
      row.appendChild(copy);
      row.appendChild(link);
      row.appendChild(done);
      card.appendChild(row);
      holder.appendChild(card);
    });
    wake();
  }

  // "I sent it" only works once every block has been copied.
  function wake() {
    $("sent").disabled = blocks.some(function (block) { return !block.copied && !block.delivered; });
  }

  function copyText(box) {
    box.focus();
    box.select();
    if (navigator.clipboard && navigator.clipboard.writeText) {
      return navigator.clipboard.writeText(box.value).then(function () { return true; }, function () {
        return oldCopy();
      });
    }
    return Promise.resolve(oldCopy());
  }

  function oldCopy() {
    try {
      return document.execCommand("copy");
    } catch (e) {
      return false;
    }
  }

  // Everything is sent: remember how far each log was read, and start over.
  function finish(message) {
    var saved = load();
    var now = Date.now();
    items.forEach(function (item) {
      if (item.status === "new" || (item.status === "skip" && !item.done)) {
        saved[item.file.name] = { offset: item.end, ctx: item.ctx, at: now };
      }
    });
    var hadLogs = items.some(function (item) { return item.status === "new"; });
    var kept = save(saved);
    items = [];
    blocks = [];
    $("stats-box").value = "";
    $("paste-note").textContent = "";
    render();
    if (hadLogs && kept) {
      message += " This browser will skip those logs next time, so you can drop the whole folder again after " +
        "your next session.";
    } else if (hadLogs) {
      message += " This browser couldn't remember which logs were sent, so it will offer them again next time. " +
        "Sending something twice does no harm.";
    }
    $("thanks").textContent = message;
    $("thanks").hidden = false;
  }

  // ---- sending by itself ----
  function post(text) {
    return fetch(SEND_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ block: text }),
    }).then(function (response) {
      return response.json().then(function (answer) {
        if (response.ok && answer && answer.ok) return;
        throw new Error(answer && answer.error ? answer.error : "The database didn't take it. Try again in a few minutes.");
      }, function () {
        throw new Error("The database didn't answer properly. Try again in a few minutes.");
      });
    }, function () {
      throw new Error("Couldn't reach the database. Check your connection and try again.");
    });
  }

  function sendAll() {
    if (sending || busy || !blocks.length) return;
    sending = true;
    $("go").disabled = true;
    var todo = blocks.filter(function (block) { return !block.delivered; });
    var hadStats = blocks.some(function (block) { return block.stats; });
    var count = 0;
    var chain = Promise.resolve();
    todo.forEach(function (block) {
      chain = chain.then(function () {
        count += 1;
        $("go-note").textContent = "Sending " + count + " of " + todo.length + "...";
        return post(block.text).then(function () {
          block.delivered = true;
          if (block.stats) sentPages.push(block.text);
        });
      });
    });
    chain.then(function () {
      sending = false;
      $("go").disabled = false;
      $("go-note").textContent = "";
      finish("Sent. Thank you." + (hadStats
        ? " Click \"I sent it\" in Gander, and if it shows another page, paste that one here too." : ""));
    }, function (error) {
      sending = false;
      $("go").disabled = false;
      $("go-note").textContent = error.message + (count > 1 ? " The blocks before this one did arrive." : "");
      renderBlocks();
    });
  }

  // ---- choosing and dropping ----
  // ---- a pasted block goes at once ----
  // One paste for each page of /gander send, with nothing to press in
  // between. If it can't be sent, the block stays in the box and the Send
  // button below takes over.
  function sendPasted() {
    var text = statsBlock();
    $("paste-note").textContent = "";
    if (!text || sending) { renderBlocks(); return Promise.resolve(); }
    var next = ' Click "I sent it" in Gander, and if it shows another page, paste that one here.';
    if (sentPages.indexOf(text) !== -1) {
      $("stats-box").value = "";
      renderBlocks();
      $("paste-note").textContent = "You already sent that page." + next;
      return Promise.resolve();
    }
    sending = true;
    pasting = true;
    $("go").disabled = true;
    renderBlocks();
    $("paste-note").textContent = "Sending...";
    function done(message) {
      sending = false;
      pasting = false;
      $("go").disabled = false;
      renderBlocks();
      $("paste-note").textContent = message;
    }
    return post(text).then(function () {
      sentPages.push(text);
      if ($("stats-box").value.trim() === text) $("stats-box").value = "";
      done((sentPages.length > 1 ? "Sent: that makes " + sentPages.length + " pages. Thank you." : "Sent. Thank you.") + next);
    }, function (error) {
      done(error.message + " Your block is still in the box: press Send below to try again.");
    });
  }

  function entryFiles(entry, depth) {
    if (entry.isFile) {
      if (!LOG_NAME.test(entry.name)) return Promise.resolve([]);
      return new Promise(function (resolve) {
        entry.file(function (file) { resolve([file]); }, function () { resolve([]); });
      });
    }
    if (!entry.isDirectory || depth <= 0) return Promise.resolve([]);
    var reader = entry.createReader();
    var found = [];
    return new Promise(function (resolve) {
      (function more() {
        reader.readEntries(function (entries) {
          if (!entries.length) {
            Promise.all(found).then(function (lists) { resolve([].concat.apply([], lists)); });
            return;
          }
          entries.forEach(function (child) { found.push(entryFiles(child, depth - 1)); });
          more();
        }, function () { resolve([]); });
      })();
    });
  }

  function dropped(event) {
    var transfer = event.dataTransfer;
    var entries = [];
    Array.prototype.forEach.call(transfer.items || [], function (item) {
      var entry = item.webkitGetAsEntry ? item.webkitGetAsEntry() : null;
      if (entry) entries.push(entry);
    });
    if (!entries.length) return Promise.resolve(transfer.files || []);
    return Promise.all(entries.map(function (entry) { return entryFiles(entry, DEPTH); })).then(function (lists) {
      return [].concat.apply([], lists);
    });
  }

  function start() {
    $("stats").hidden = !SEND_URL;
    askWorker();
    var drop = $("drop");
    ["dragenter", "dragover"].forEach(function (name) {
      drop.addEventListener(name, function (event) {
        event.preventDefault();
        drop.classList.add("over");
      });
    });
    drop.addEventListener("dragleave", function () { drop.classList.remove("over"); });
    drop.addEventListener("drop", function (event) {
      event.preventDefault();
      drop.classList.remove("over");
      dropped(event).then(function (files) {
        if (!files.length) {
          $("status").textContent = "No combat logs in what you dropped. They are named WoWCombatLog-(date).txt.";
        } else {
          addFiles(files);
        }
      });
    });
    // A file dropped beside the box must not replace the page.
    ["dragover", "drop"].forEach(function (name) {
      window.addEventListener(name, function (event) { event.preventDefault(); });
    });
    $("pick-files").addEventListener("click", function () { $("files").click(); });
    $("pick-folder").addEventListener("click", function () { $("folder").click(); });
    ["files", "folder"].forEach(function (id) {
      $(id).addEventListener("change", function () {
        addFiles(this.files);
        this.value = "";
      });
    });
    $("not-english").addEventListener("change", renderBlocks);
    $("stats-box").addEventListener("input", function () {
      $("thanks").hidden = true;
      $("paste-note").textContent = "";
      renderBlocks();
    });
    $("stats-box").addEventListener("paste", function (event) {
      var text = event.clipboardData && event.clipboardData.getData("text");
      if (!SEND_URL || !text) return;   // let the browser paste as usual
      event.preventDefault();
      this.value = text;                // a paste replaces what was in the box
      $("thanks").hidden = true;
      sendPasted();
    });
    $("go").addEventListener("click", sendAll);
    $("sent").addEventListener("click", function () { finish("Thank you."); });
    $("forget").addEventListener("click", function () {
      try { localStorage.removeItem(STORE); } catch (e) { /* nothing was kept */ }
      items = [];
      render();
      $("status").textContent = "Forgotten. Every log will be offered again.";
    });
  }

  window.GanderPage = { addFiles: addFiles, sendPasted: sendPasted };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
  else start();
})();
