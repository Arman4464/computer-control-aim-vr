// AIM-VR Browser Companion Service Worker
const BRIDGE_URL = "http://127.0.0.1:9224";
let isPolling = false;

async function sendRegister() {
  try {
    const [tab] = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
    await fetch(`${BRIDGE_URL}/register`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        status: "alive",
        tab: tab ? { id: tab.id, title: tab.title, url: tab.url } : null
      })
    });
  } catch (err) {
    // Bridge server might not be running yet, retry silently
  }
}

async function pollCommands() {
  if (isPolling) return;
  isPolling = true;

  while (true) {
    try {
      const res = await fetch(`${BRIDGE_URL}/poll`);
      if (res.ok) {
        const cmd = await res.json();
        if (cmd && cmd.id && cmd.action) {
          handleCommand(cmd);
        }
      }
    } catch (e) {
      // Bridge server offline, wait 2s before retry
      await new Promise(r => setTimeout(r, 2000));
    }
    await new Promise(r => setTimeout(r, 150));
  }
}

async function handleCommand(cmd) {
  try {
    const [tab] = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
    if (!tab || !tab.id) {
      postResponse(cmd.id, { status: "error", message: "No active browser tab found." });
      return;
    }

    chrome.tabs.sendMessage(tab.id, cmd, (response) => {
      if (chrome.runtime.lastError) {
        postResponse(cmd.id, {
          status: "error",
          message: chrome.runtime.lastError.message || "Failed to reach content script in active tab."
        });
      } else {
        postResponse(cmd.id, response || { status: "success" });
      }
    });
  } catch (err) {
    postResponse(cmd.id, { status: "error", message: err.message });
  }
}

async function postResponse(cmdId, result) {
  try {
    await fetch(`${BRIDGE_URL}/response`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id: cmdId, result: result })
    });
  } catch (err) {
    console.error("Failed to post response to AIM-VR bridge:", err);
  }
}

// Start polling and registration
sendRegister();
setInterval(sendRegister, 10000);
pollCommands();
