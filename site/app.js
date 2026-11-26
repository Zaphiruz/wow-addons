// The page: takes the combat logs a player chooses, reads them with
// gander-log.js, shows what was found and hands over the blocks to send.
// Text from a log is only ever put on the page as text, never as HTML.
(function () {
  "use strict";

  var FORM = "https://github.com/Zaphiruz/wow-addons/issues/new?template=gander-data.yml";
  var STORE = "gander-logs-v1";      // which logs this browser has sent, and how far into each
  var REMEMBERED = 300;              // logs to remember at most
  var LOG_NAME = /^WoWCombatLog.*\.txt$/i;
  var CHUNK = 4 * 1024 * 1024;       // bytes read at a time
  var DEPTH = 4;                     // folders deep to look in a dropped folder

  var items = [];                    // the logs chosen in this visit
  var copied = [];                   // which blocks have been copied
  var busy = false;

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

  // ---- reading ----
  // Read a log from where this browser stopped last time. Whole lines only:
  // the game may still be writing the last one.
  function readLog(item) {
    var file = item.file;
    var data = GanderLog.newData();
    var reader = new GanderLog.Reader(data, item.ctx, new Date(file.lastModified || Date.now()).getFullYear());
    var decoder = new TextDecoder("utf-8");
    var position = item.start;
    item.end = item.start;

    function next() {
      if (position >= file.size) {
        reader.finish();
        item.data = data;
        item.ctx = reader.ctx;
        item.lines = reader.lines;
        return Promise.resolve();
      }
      return file.slice(position, position + CHUNK).arrayBuffer().then(function (buffer) {
        var bytes = new Uint8Array(buffer);
        var newline = bytes.lastIndexOf(10);
        if (newline !== -1) item.end = position + newline + 1;
        position += bytes.length;
        reader.feedText(decoder.decode(bytes, { stream: true }));
        $("status").textContent = "Reading " + file.name + ": " +
          Math.round(100 * Math.min(position, file.size) / Math.max(file.size, 1)) + "%";
        return next();
      });
    }
    return next();
  }

  function describe(item) {
    var found = GanderLog.summary(item.data);
    if (item.lines === 0) return ["bad", "This isn't a combat log"];
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
    return ["new", (item.start ? "New since last time: " : "") + parts.join(" · ")];
  }

  function addFiles(files) {
    if (busy) return Promise.resolve();
    var saved = load();
    var fresh = [];
    Array.prototype.forEach.call(files, function (file) {
      if (!LOG_NAME.test(file.name)) return;
      if (fresh.some(function (item) { return item.file.name === file.name; })) return;
      // Chosen again in the same visit: it may have grown, so look at it afresh.
      items = items.filter(function (item) { return item.file.name !== file.name; });
      var before = saved[file.name];
      var item = { file: file, start: 0, ctx: {}, status: "wait", what: "Waiting" };
      if (before && typeof before.offset === "number" && before.offset <= file.size) {
        item.start = before.offset;
        item.ctx = before.ctx || {};
      }
      if (item.start > 0 && item.start === file.size) {
        item.status = "skip";
        item.what = "Already sent from this browser";
        item.done = true;
      }
      items.push(item);
      fresh.push(item);
    });
    if (!fresh.length) {
      $("status").textContent = files.length
        ? "No new combat logs in what you chose. They are named WoWCombatLog-(date).txt."
        : "";
      return Promise.resolve();
    }
    items.sort(function (a, b) { return a.file.name < b.file.name ? -1 : 1; });
    busy = true;
    $("thanks").hidden = true;
    render();
    var chain = Promise.resolve();
    fresh.forEach(function (item) {
      if (item.done) return;
      chain = chain.then(function () { return readLog(item); }).then(function () {
        var result = describe(item);
        item.status = result[0];
        item.what = result[1];
        render();
      }, function () {
        item.status = "bad";
        item.what = "Couldn't read this file";
        render();
      });
    });
    return chain.then(function () {
      busy = false;
      $("status").textContent = "";
      render();
    });
  }

  // ---- showing ----
  function toSend() {
    var data = GanderLog.newData();
    items.forEach(function (item) { if (item.status === "new") GanderLog.merge(data, item.data); });
    return data;
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
    var data = toSend();
    var blocks = busy ? [] : GanderLog.blocks(data, { english: !$("not-english").checked });
    var holder = $("blocks");
    holder.textContent = "";
    copied = blocks.map(function () { return false; });
    $("send").hidden = !blocks.length;
    if (!blocks.length) return;

    var mobs = 0, runs = 0;
    GanderLog.summary(data).forEach(function (game) { mobs += game.mobs; runs += game.instances.length; });
    $("total").textContent = "Found: casts for " + some(mobs, "mob", "mobs") +
      (runs ? ", and time in " + some(runs, "dungeon", "dungeons") : "") +
      ". That makes " + some(blocks.length, "block", "blocks") + " to send.";

    blocks.forEach(function (text, i) {
      var card = el("div", "block");
      card.appendChild(el("h3", "", blocks.length > 1 ? "Block " + (i + 1) + " of " + blocks.length : "Your block"));
      var box = el("textarea");
      box.readOnly = true;
      box.value = text;
      box.setAttribute("aria-label", "Block " + (i + 1) + ": exactly what will be sent");
      card.appendChild(box);
      var row = el("p", "buttons");
      var copy = el("button", "", "Copy");
      copy.type = "button";
      var done = el("span", "done", "");
      copy.addEventListener("click", function () {
        copyText(box).then(function (ok) {
          done.textContent = ok ? "Copied. Now paste it into the form." : "Select the text and copy it yourself.";
          copied[i] = true;
          $("sent").disabled = copied.indexOf(false) !== -1;
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
    $("sent").disabled = true;
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

  // The player says the blocks are sent: remember how far each log was read.
  function markSent() {
    var saved = load();
    var now = Date.now();
    items.forEach(function (item) {
      if (item.status === "new" || (item.status === "skip" && !item.done)) {
        saved[item.file.name] = { offset: item.end, ctx: item.ctx, at: now };
      }
    });
    var kept = save(saved);
    items = [];
    render();
    $("thanks").hidden = false;
    if (!kept) {
      $("thanks").textContent = "Thank you. This browser couldn't remember which logs were sent, so it will " +
        "offer them again next time. Sending something twice does no harm.";
    }
  }

  // ---- choosing and dropping ----
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
    $("sent").addEventListener("click", markSent);
    $("forget").addEventListener("click", function () {
      try { localStorage.removeItem(STORE); } catch (e) { /* nothing was kept */ }
      items = [];
      render();
      $("status").textContent = "Forgotten. Every log will be offered again.";
    });
  }

  window.GanderPage = { addFiles: addFiles };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
  else start();
})();
