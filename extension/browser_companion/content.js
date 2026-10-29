// AIM-VR Browser Companion Content Script
// Fast DOM automation for React, Vue, Angular, and native HTML forms

chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  const { action, params } = request;
  try {
    if (action === "click") {
      const res = executeClick(params);
      sendResponse(res);
    } else if (action === "type") {
      const res = executeType(params);
      sendResponse(res);
    } else if (action === "query") {
      const res = executeQuery(params);
      sendResponse(res);
    } else if (action === "get_dom_tree") {
      const res = executeGetDomTree(params);
      sendResponse(res);
    } else if (action === "scroll") {
      const res = executeScroll(params);
      sendResponse(res);
    } else if (action === "eval") {
      const res = executeEval(params);
      sendResponse(res);
    } else {
      sendResponse({ status: "error", message: `Unknown browser action '${action}'` });
    }
  } catch (err) {
    sendResponse({ status: "error", message: err.message });
  }
  return true; // Keep channel open for async response
});

function findElement(selector, textMatch) {
  if (selector) {
    // Try standard CSS selector
    try {
      const el = document.querySelector(selector);
      if (el) return el;
    } catch (e) {}

    // Try XPath
    try {
      const xpathRes = document.evaluate(selector, document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null);
      if (xpathRes.singleNodeValue) return xpathRes.singleNodeValue;
    } catch (e) {}
  }

  // Text search fallback
  if (textMatch) {
    const q = textMatch.toLowerCase().trim();
    const candidates = Array.from(document.querySelectorAll("button, a, input, textarea, [role='button'], span, div, h1, h2, h3, p"));
    for (const el of candidates) {
      if ((el.innerText || el.textContent || "").toLowerCase().includes(q)) {
        return el;
      }
    }
  }

  return null;
}

function executeClick(params) {
  const { selector, text } = params;
  const el = findElement(selector, text);
  if (!el) {
    return { status: "error", message: `Element matching selector='${selector}' text='${text}' not found.` };
  }

  el.scrollIntoView({ behavior: "instant", block: "center", inline: "center" });

  const rect = el.getBoundingClientRect();
  const cx = rect.left + rect.width / 2;
  const cy = rect.top + rect.height / 2;

  // Dispatch full synthetic pointer/mouse event cascade
  const events = ["pointerdown", "mousedown", "pointerup", "mouseup", "click"];
  for (const evName of events) {
    const ev = new MouseEvent(evName, {
      bubbles: true,
      cancelable: true,
      view: window,
      clientX: cx,
      clientY: cy
    });
    el.dispatchEvent(ev);
  }

  if (typeof el.click === "function") {
    el.click();
  }

  return {
    status: "success",
    message: `Clicked element <${el.tagName.toLowerCase()}>`,
    bounds: [rect.left, rect.top, rect.width, rect.height]
  };
}

function executeType(params) {
  const { selector, text, value, clear_first = true } = params;
  const val = text !== undefined ? text : value;
  const el = findElement(selector);

  if (!el) {
    return { status: "error", message: `Input element matching '${selector}' not found.` };
  }

  el.scrollIntoView({ behavior: "instant", block: "center" });
  el.focus();

  if (clear_first) {
    setNativeValue(el, "");
  }
  setNativeValue(el, val || "");

  return {
    status: "success",
    message: `Typed text into <${el.tagName.toLowerCase()}>`,
    value: val
  };
}

function setNativeValue(element, value) {
  // Support React/Vue controlled inputs by grabbing prototype setter
  const prototype = Object.getPrototypeOf(element);
  const descriptor = Object.getOwnPropertyDescriptor(prototype, "value");
  if (descriptor && descriptor.set) {
    descriptor.set.call(element, value);
  } else {
    element.value = value;
  }
  element.dispatchEvent(new Event("input", { bubbles: true }));
  element.dispatchEvent(new Event("change", { bubbles: true }));
}

function executeQuery(params) {
  const { selector, text } = params;
  const el = findElement(selector, text);
  if (!el) {
    return { status: "not_found", count: 0 };
  }
  const rect = el.getBoundingClientRect();
  return {
    status: "found",
    count: 1,
    tag: el.tagName.toLowerCase(),
    text: (el.innerText || el.textContent || "").trim().substring(0, 150),
    bounds: [rect.left, rect.top, rect.width, rect.height],
    visible: rect.width > 0 && rect.height > 0
  };
}

function executeGetDomTree(params) {
  const limit = (params && params.limit) || 60;
  const selectors = "button, a[href], input, textarea, select, [role='button'], [role='link'], [tabindex='0']";
  const elements = Array.from(document.querySelectorAll(selectors));
  const result = [];

  for (const el of elements) {
    const rect = el.getBoundingClientRect();
    // Only elements in visible viewport
    if (rect.width > 4 && rect.height > 4 && rect.bottom > 0 && rect.right > 0 && rect.top < window.innerHeight && rect.left < window.innerWidth) {
      const text = (el.innerText || el.value || el.placeholder || el.getAttribute("aria-label") || "").trim().substring(0, 60);
      result.push({
        tag: el.tagName.toLowerCase(),
        type: el.type || el.getAttribute("role") || "",
        id: el.id || "",
        text: text,
        bounds: [Math.round(rect.left), Math.round(rect.top), Math.round(rect.width), Math.round(rect.height)]
      });
      if (result.length >= limit) break;
    }
  }

  return {
    status: "success",
    title: document.title,
    url: window.location.href,
    count: result.length,
    elements: result
  };
}

function executeScroll(params) {
  const { dx = 0, dy = 300 } = params;
  window.scrollBy({ left: dx, top: dy, behavior: "instant" });
  return { status: "success", scrollX: window.scrollX, scrollY: window.scrollY };
}

function executeEval(params) {
  const { script } = params;
  try {
    const res = eval(script);
    return { status: "success", result: res };
  } catch (e) {
    return { status: "error", message: e.message };
  }
}
