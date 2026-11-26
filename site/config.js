// The address of the Worker that takes submissions (see worker/README.md).
// While this is empty the page can't send by itself: it hands the player
// blocks to paste into the GitHub form instead.
window.GANDER_SEND_URL = "https://gander-data.zaphiruz.workers.dev/";

// The database's record of how far each combat log has been read, so the
// page starts a log where the database stopped and nothing is counted twice.
window.GANDER_LOGS_URL = "https://raw.githubusercontent.com/Zaphiruz/wow-addons/main/mods/classic/data/gander_logs.json";
