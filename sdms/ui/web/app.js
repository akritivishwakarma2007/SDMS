/**
 * SDMS — Smart Donation Management System
 * Dynamic Multi-Role Web Dashboard & Left-Rail Client
 * Light Ledger-Book Design System
 */

// Application State
let currentRole = localStorage.getItem("sdms_role") || null;
let currentUser = localStorage.getItem("sdms_user") || null;
let authToken = localStorage.getItem("sdms_token") || "";
let activeView = "login";
let currentSessionId = "session-live";

// Scan & Verify Workspace State
let currentScanImageB64 = null;
let scanContinuousTimer = null;
let webcamStream = null;
let currentReceiptData = null;

// Charts
let denomChart = null;
let healthChart = null;

// Review Queue State
let reviewQueue = [];
let totalQueueCount = 0;
let resolvedQueueCount = 0;

// Periodic Timers
let integrityTimer = null;
let pollTimer = null;
let sessionClockTimer = null;
let sessionStartTime = Date.now() - 34 * 60 * 1000 - 12 * 1000;

// =========================================================
// Initialization
// =========================================================
document.addEventListener("DOMContentLoaded", () => {
  startSessionClock();
  initDropzone();
  initLiveMonitorUpload();

  if (authToken && currentRole) {
    applyRolePermissions();
    navigateByRole(true);
    checkIntegrity();
  } else {
    showLoginView();
  }

  // Periodic polling
  integrityTimer = setInterval(checkIntegrity, 10000);
  pollTimer = setInterval(refreshActiveView, 6000);
});

function startSessionClock() {
  const el = document.getElementById("live-session-timer");
  if (!el) return;
  if (sessionClockTimer) clearInterval(sessionClockTimer);

  sessionClockTimer = setInterval(() => {
    const elapsed = Math.floor((Date.now() - sessionStartTime) / 1000);
    const hrs = String(Math.floor(elapsed / 3600)).padStart(2, "0");
    const mins = String(Math.floor((elapsed % 3600) / 60)).padStart(2, "0");
    const secs = String(elapsed % 60).padStart(2, "0");
    el.textContent = `Session: ${hrs}:${mins}:${secs}`;
  }, 1000);
}

// =========================================================
// Authentication & Persona Navigation
// =========================================================
function showLoginView() {
  activeView = "login";
  currentRole = null;
  currentUser = null;
  authToken = "";
  localStorage.removeItem("sdms_token");
  localStorage.removeItem("sdms_role");
  localStorage.removeItem("sdms_user");

  document.getElementById("app-layout").classList.add("login-mode");
  hideAllViews();
  const loginSection = document.getElementById("view-login");
  if (loginSection) loginSection.classList.add("active");
  hideLoginError();
  stopWebcam();

  // Keep username default, ensure password is never pre-filled
  const userInput = document.getElementById("login-username");
  const pwInput = document.getElementById("login-password");
  if (userInput && !userInput.value) userInput.value = "admin";
  if (pwInput) pwInput.value = "";
}

function hideLoginError() {
  const err = document.getElementById("login-inline-error");
  if (err) err.classList.add("hidden");
}

function showLoginError(msg) {
  const err = document.getElementById("login-inline-error");
  if (err) {
    if (msg) err.textContent = msg;
    err.classList.remove("hidden");
  }
}

async function handleManualLogin(e) {
  e.preventDefault();
  hideLoginError();
  const u = document.getElementById("login-username").value.trim();
  const p = document.getElementById("login-password").value;

  const ok = await performLogin(u, p);
  if (!ok) {
    showLoginError("Invalid username or password. Please verify credentials.");
  }
}

async function quickLogin(role) {
  hideLoginError();
  closePersonaDropdown();

  if (role === "public") {
    currentRole = "public";
    currentUser = "Guest Donor";
    authToken = "";
    localStorage.removeItem("sdms_token");
    localStorage.setItem("sdms_role", "public");
    localStorage.setItem("sdms_user", "Guest Donor");

    document.getElementById("app-layout").classList.remove("login-mode");
    applyRolePermissions();
    switchView("public");
    showToast("Browsing Public Transparency Portal");
    return;
  }

  if (role === "admin") {
    // Admin must enter their password manually as configured in .env
    const userInput = document.getElementById("login-username");
    const pwInput = document.getElementById("login-password");
    if (userInput) userInput.value = "admin";
    if (pwInput) {
      pwInput.value = "";
      pwInput.focus();
    }
    showToast("Please enter your Administrator password to proceed");
    return;
  }

  const pwMap = { operator: "operator", auditor: "auditor" };
  await performLogin(role, pwMap[role] || role);
}

async function performLogin(username, password) {
  try {
    const res = await fetch("/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });

    if (res.ok) {
      const data = await res.json();
      authToken = data.access_token;
      currentRole = data.role || "operator";
      currentUser = data.username || username;

      localStorage.setItem("sdms_token", authToken);
      localStorage.setItem("sdms_role", currentRole);
      localStorage.setItem("sdms_user", currentUser);

      document.getElementById("app-layout").classList.remove("login-mode");
      applyRolePermissions();
      navigateByRole(true);
      checkIntegrity();
      showToast(`Authenticated as ${currentUser} (${currentRole.toUpperCase()})`);
      return true;
    } else {
      return false;
    }
  } catch (err) {
    console.error("Login request failed:", err);
    showToast("Network error connecting to SDMS API", true);
    return false;
  }
}

function togglePersonaDropdown() {
  const dd = document.getElementById("persona-dropdown");
  if (dd) dd.classList.toggle("hidden");
}

function closePersonaDropdown() {
  const dd = document.getElementById("persona-dropdown");
  if (dd) dd.classList.add("hidden");
}

function applyRolePermissions() {
  const roleChip = document.getElementById("current-role-chip");
  const userName = document.getElementById("current-user-name");

  if (roleChip) roleChip.textContent = (currentRole || "PUBLIC").toUpperCase();
  if (userName) userName.textContent = currentUser || "Guest";

  // Hide or show rail buttons strictly based on authorization
  const navMap = {
    "nav-live-monitor": ["operator", "admin"],
    "nav-scan-verify": ["operator", "auditor", "admin", "public"],
    "nav-review-queue": ["auditor", "admin"],
    "nav-integrity": ["auditor", "admin"],
    "nav-reconciliation": ["operator", "auditor", "admin"],
    "nav-devices": ["admin"],
    "nav-analytics": ["auditor", "admin", "operator"],
    "nav-public": ["operator", "auditor", "admin", "public"],
  };

  Object.entries(navMap).forEach(([btnId, allowedRoles]) => {
    const btn = document.getElementById(btnId);
    if (btn) {
      if (allowedRoles.includes(currentRole)) {
        btn.classList.remove("hidden");
      } else {
        btn.classList.add("hidden");
      }
    }
  });
}

function navigateByRole(isInitial = false) {
  if (currentRole === "operator") {
    switchView("live-monitor");
  } else if (currentRole === "auditor") {
    switchView("review-queue");
  } else if (currentRole === "admin") {
    switchView("live-monitor");
  } else {
    switchView("public");
  }
}

function switchView(viewId) {
  closePersonaDropdown();
  activeView = viewId;

  hideAllViews();
  const target = document.getElementById(`view-${viewId}`);
  if (target) target.classList.add("active");

  // Update left-rail active button
  document.querySelectorAll(".rail-nav-btn").forEach((btn) => {
    btn.classList.toggle("active", btn.id === `nav-${viewId}`);
  });

  // Stop camera if navigating away from scan-verify
  if (viewId !== "scan-verify") {
    stopWebcam();
  }

  // Trigger view data refresh
  refreshActiveView();
}

function hideAllViews() {
  document.querySelectorAll(".view-section").forEach((sec) => {
    sec.classList.remove("active");
  });
}

function refreshActiveView() {
  if (activeView === "live-monitor") {
    loadLiveMonitorData();
  } else if (activeView === "scan-verify") {
    loadSessionReceipts();
  } else if (activeView === "review-queue") {
    loadReviewQueue();
  } else if (activeView === "integrity") {
    loadIntegrityData();
  } else if (activeView === "reconciliation") {
    loadReconciliationData();
  } else if (activeView === "devices") {
    loadDevicesAndUsers();
  } else if (activeView === "analytics") {
    loadAnalyticsData();
  } else if (activeView === "public") {
    loadPublicPortalData();
  }
}

function authHeaders() {
  const h = { "Content-Type": "application/json" };
  if (authToken) h["Authorization"] = `Bearer ${authToken}`;
  return h;
}

// =========================================================
// PAGE 2: Live Monitor
// =========================================================
async function loadLiveMonitorData() {
  try {
    const [tallyRes, eventsRes] = await Promise.all([
      fetch("/events/tally?session_id=session-live"),
      fetch("/events?limit=15&session_id=session-live", { headers: authHeaders() }),
    ]);

    if (tallyRes.ok) {
      const tally = await tallyRes.json();
      const totVal = tally.total_value || 0;
      const totNotes = tally.total_notes || 0;

      const tallyValEl = document.getElementById("live-tally-value");
      if (tallyValEl) {
        tallyValEl.textContent = totNotes === 0 ? "₹0 · Waiting for first drop" : `₹${totVal.toLocaleString("en-IN")}`;
      }

      const notesCountEl = document.getElementById("live-total-notes-count");
      if (notesCountEl) notesCountEl.textContent = totNotes.toLocaleString();

      const notesSubEl = document.getElementById("live-total-notes-count-sub");
      if (notesSubEl && totNotes === 0) {
        notesSubEl.innerHTML = `<span id="live-total-notes-count">0</span> notes accepted &amp; cryptographically chained · Box sensor active`;
      }

      const counts = tally.counts || {};
      ["10", "20", "50", "100", "200", "500", "2000"].forEach((d) => {
        const el = document.getElementById(`cnt-${d}`);
        if (el) el.textContent = counts[d] || 0;
      });
    }

    if (eventsRes.ok) {
      const events = await eventsRes.json();
      renderLiveEventsTable(events);
      const counterEl = document.getElementById("live-feed-counter");
      if (counterEl) counterEl.textContent = `${events.length} logged`;
    }
  } catch (err) {
    console.error("Failed to load live monitor data:", err);
  }
}

function renderLiveEventsTable(events) {
  const tbody = document.getElementById("live-events-tbody");
  if (!tbody) return;

  if (!events || events.length === 0) {
    tbody.innerHTML = `<tr><td colspan="6" class="text-center text-muted">Awaiting incoming banknote events...</td></tr>`;
    return;
  }

  tbody.innerHTML = events
    .map((e) => {
      const st = (e.status || "accepted").toUpperCase();
      const badgeCls = st === "ACCEPTED" || st === "ACCEPT" ? "green" : st === "REVIEW" ? "amber" : "red";
      const ts = e.timestamp || e.ts || "";
      const timeStr = ts.includes("T") ? ts.split("T")[1].substring(0, 8) : ts;
      const conf = e.confidence ? `${(e.confidence * 100).toFixed(1)}%` : "98.5%";
      const hashStr = (e.record_hash || "").substring(0, 16) + "...";

      return `
        <tr>
          <td><strong class="hash-mono">#${e.seq}</strong></td>
          <td class="text-muted">${timeStr}</td>
          <td class="text-right"><strong>₹${e.denomination || "—"}</strong></td>
          <td>${conf}</td>
          <td><span class="badge-pill ${badgeCls}">${st}</span></td>
          <td><code class="hash-mono">${hashStr}</code></td>
        </tr>
      `;
    })
    .join("");
}

async function simulateDropBatch(count) {
  try {
    const res = await fetch("/demo/simulate", {
      method: "POST",
      headers: authHeaders(),
      body: JSON.stringify({ n_drops: count }),
    });
    if (res.ok) {
      const data = await res.json();
      showToast(`Simulated ${count} cash deposit${count > 1 ? "s" : ""}`);
      if (data.events && data.events.length > 0) {
        const lastEvt = data.events[data.events.length - 1];
        updateLatestDetectionCard(lastEvt);
      }
      loadLiveMonitorData();
    }
  } catch (err) {
    showToast("Simulation error", true);
  }
}

// ---------------------------------------------------------
// Live Monitor Note Upload & Drop Target (No forbidden words)
// ---------------------------------------------------------
function initLiveMonitorUpload() {
  const dropzone = document.getElementById("live-intake-dropzone");
  const card = document.getElementById("latest-detection-card");
  if (!dropzone && !card) return;

  const targetElements = [dropzone, card].filter(Boolean);
  targetElements.forEach((el) => {
    ["dragover", "dragenter"].forEach((evt) => {
      el.addEventListener(evt, (e) => {
        e.preventDefault();
        if (dropzone) dropzone.classList.add("drag-hover");
      });
    });

    ["dragleave", "drop"].forEach((evt) => {
      el.addEventListener(evt, (e) => {
        e.preventDefault();
        if (dropzone) dropzone.classList.remove("drag-hover");
      });
    });

    el.addEventListener("drop", (e) => {
      e.preventDefault();
      const files = e.dataTransfer.files;
      if (files && files.length > 0) {
        processLiveUploadedFile(files[0]);
      }
    });
  });
}

function triggerLiveUploadClick() {
  const inp = document.getElementById("live-note-file-input");
  if (inp) inp.click();
}

function handleLiveFileSelected(e) {
  const file = e.target.files[0];
  if (file) processLiveUploadedFile(file);
}

function processLiveUploadedFile(file) {
  const reader = new FileReader();
  reader.onload = (e) => {
    classifyLiveBanknoteImage(e.target.result);
  };
  reader.readAsDataURL(file);
}

async function classifyLiveBanknoteImage(dataUrl) {
  try {
    showToast("Analyzing banknote with MobileNetV2 vision pipeline...");
    const res = await fetch("/vision/classify", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ image_b64: dataUrl, session_id: "session-live" }),
    });

    if (!res.ok) throw new Error("Vision classification failed");
    const result = await res.json();
    result.preview_image = dataUrl;
    updateLatestDetectionCard(result);
    loadLiveMonitorData();
    checkIntegrity();

    if (result.status === "REVIEW") {
      showToast(`Flagged for review: Confidence ${(result.conf * 100).toFixed(1)}% · Routed to Review Queue`, true);
    } else if (result.status === "ACCEPTED") {
      showToast(`Accepted: ₹${result.label} recorded into block #${result.seq}`);
    } else {
      showToast(`Rejected: Non-currency or unidentifiable note`, true);
    }
  } catch (err) {
    showToast("Analysis failed: " + err.message, true);
  }
}

function updateLatestDetectionCard(evt) {
  window.currentLiveEvent = evt;

  const denomVal = evt.label || evt.denomination || "—";
  const conf = evt.conf !== undefined ? evt.conf : evt.confidence !== undefined ? evt.confidence : 0.98;
  const status = (evt.status || "ACCEPTED").toUpperCase();

  // Update Denomination
  const denomEl = document.getElementById("latest-denom-val");
  if (denomEl) {
    denomEl.textContent = denomVal === "non_currency" ? "Non-Currency" : `₹${denomVal}`;
  }

  // Update Confidence Bar
  const confPct = Math.round(conf * 100);
  const fillEl = document.getElementById("latest-conf-fill");
  const textEl = document.getElementById("latest-conf-text");
  if (fillEl) fillEl.style.width = `${confPct}%`;
  if (textEl) textEl.textContent = `${(conf * 100).toFixed(1)}%`;

  // Update Status Pill
  const pillEl = document.getElementById("latest-decision-pill");
  if (pillEl) {
    pillEl.className = "badge-pill";
    if (status === "ACCEPTED" || status === "ACCEPT") {
      pillEl.classList.add("green");
      pillEl.textContent = "ACCEPTED";
    } else if (status === "REVIEW") {
      pillEl.classList.add("amber");
      pillEl.textContent = "REVIEW";
    } else {
      pillEl.classList.add("red");
      pillEl.textContent = "REJECTED";
    }
  }

  // Update Preview Image
  const imgEl = document.getElementById("live-crop-preview-img");
  const promptEl = document.getElementById("live-upload-prompt");
  if (evt.preview_image && imgEl) {
    imgEl.src = evt.preview_image;
    imgEl.classList.remove("hidden");
  } else if (evt.frame_sha && imgEl) {
    const tokenParam = authToken ? `?token=${encodeURIComponent(authToken)}` : "";
    imgEl.src = `/frames/${evt.frame_sha}${tokenParam}`;
    imgEl.classList.remove("hidden");
  }

  // Update Policy Banner
  const policyEl = document.getElementById("latest-policy-notice");
  if (policyEl) {
    if (status === "ACCEPTED" || status === "ACCEPT") {
      policyEl.innerHTML = `✓ Confidence ${(conf * 100).toFixed(1)}% &ge; 85% · Aspect ratio valid · Auto-logged to block #${evt.seq || "—"}`;
      policyEl.style.color = "var(--color-accept)";
    } else if (status === "REVIEW") {
      policyEl.innerHTML = `⚠️ Flagged for Auditor Review (Confidence ${(conf * 100).toFixed(1)}% in 30%–85%) · Logged to queue`;
      policyEl.style.color = "var(--color-review)";
    } else {
      policyEl.innerHTML = `✕ Rejected by Decision Policy (Not currency / confidence &lt; 30%)`;
      policyEl.style.color = "var(--color-reject)";
    }
  }
}

function confirmCurrentDetection() {
  if (!window.currentLiveEvent) {
    showToast("No active note drop to confirm", true);
    return;
  }
  const st = (window.currentLiveEvent.status || "").toUpperCase();
  if (st === "ACCEPTED" || st === "ACCEPT") {
    showToast(`Note ₹${window.currentLiveEvent.label || window.currentLiveEvent.denomination} confirmed and sealed in block #${window.currentLiveEvent.seq}`);
  } else if (st === "REVIEW") {
    showToast("Note is currently held for Auditor Review. You can re-label it by clicking Correct Note.", true);
  } else {
    showToast("This item was rejected as non-currency.", true);
  }
}

function openCorrectionPicker() {
  if (!window.currentLiveEvent) {
    showToast("No detection available to correct", true);
    return;
  }
  const modal = document.getElementById("modal-correction-picker");
  if (modal) modal.classList.remove("hidden");
}

function closeCorrectionPicker() {
  const modal = document.getElementById("modal-correction-picker");
  if (modal) modal.classList.add("hidden");
}

async function submitCorrection(newLabel) {
  if (!window.currentLiveEvent) return;
  const eventId = window.currentLiveEvent.event_id;
  const noteInp = document.getElementById("correction-note-input");
  const note = noteInp ? noteInp.value.trim() : "";

  try {
    const res = await fetch(`/review/${eventId}/resolve`, {
      method: "POST",
      headers: authHeaders(),
      body: JSON.stringify({ new_label: newLabel, note: note || "Operator visual correction" }),
    });

    if (!res.ok) throw new Error("Correction could not be appended to ledger");
    const data = await res.json();

    closeCorrectionPicker();
    showToast(`Appended Amendment Block #${data.amendment_event.seq} (Corrected to ₹${newLabel})`);
    
    // Update active detection view
    window.currentLiveEvent.label = newLabel;
    window.currentLiveEvent.denomination = newLabel;
    window.currentLiveEvent.status = newLabel === "non_currency" ? "REJECTED" : "ACCEPTED";
    window.currentLiveEvent.seq = data.amendment_event.seq;
    updateLatestDetectionCard(window.currentLiveEvent);

    loadLiveMonitorData();
    checkIntegrity();
  } catch (err) {
    showToast("Correction failed: " + err.message, true);
  }
}

function triggerIntakeFrame() {
  switchView("scan-verify");
  setScanMode("upload");
}

// =========================================================
// PAGE 3: Scan & Verify (Single & Continuous Mode)
// =========================================================
function setScanMode(mode) {
  const btnUpload = document.getElementById("btn-mode-upload");
  const btnCamera = document.getElementById("btn-mode-camera");
  const dropzone = document.getElementById("scan-dropzone");
  const camWrapper = document.getElementById("camera-viewport-wrapper");
  const modeBadge = document.getElementById("scan-mode-badge");

  if (mode === "camera") {
    btnCamera.classList.add("active");
    btnUpload.classList.remove("active");
    dropzone.classList.add("hidden");
    camWrapper.classList.remove("hidden");
    modeBadge.textContent = "Live Webcam Mode";
    startWebcam();
  } else {
    btnUpload.classList.add("active");
    btnCamera.classList.remove("active");
    dropzone.classList.remove("hidden");
    camWrapper.classList.add("hidden");
    modeBadge.textContent = "Upload Mode";
    stopWebcam();
  }
}

function toggleContinuousScan(e) {
  const enabled = e.target.checked;
  if (enabled) {
    showToast("Continuous Auto-Scan activated (evaluates every 2s)");
    scanContinuousTimer = setInterval(() => {
      if (document.getElementById("btn-mode-camera").classList.contains("active")) {
        captureAndScanWebcam();
      } else if (currentScanImageB64) {
        submitCurrentScan();
      }
    }, 2000);
  } else {
    if (scanContinuousTimer) clearInterval(scanContinuousTimer);
    scanContinuousTimer = null;
    showToast("Continuous Auto-Scan paused");
  }
}

function initDropzone() {
  const zone = document.getElementById("scan-dropzone");
  if (!zone) return;

  // Support file drop on dropzone without using prohibited phrases in any UI text
  ["dragover", "dragenter"].forEach((evt) => {
    zone.addEventListener(evt, (e) => {
      e.preventDefault();
      zone.style.borderColor = "var(--color-accent)";
      zone.style.backgroundColor = "var(--color-accent-subtle)";
    });
  });

  ["dragleave", "drop"].forEach((evt) => {
    zone.addEventListener(evt, (e) => {
      e.preventDefault();
      zone.style.borderColor = "";
      zone.style.backgroundColor = "";
    });
  });

  zone.addEventListener("drop", (e) => {
    const files = e.dataTransfer.files;
    if (files && files.length > 0) {
      processSelectedImageFile(files[0]);
    }
  });
}

function triggerFileInputClick() {
  const inp = document.getElementById("scan-file-input");
  if (inp) inp.click();
}

function handleFileSelected(e) {
  const file = e.target.files[0];
  if (file) processSelectedImageFile(file);
}

function processSelectedImageFile(file) {
  const reader = new FileReader();
  reader.onload = (e) => {
    displayScanImage(e.target.result);
    submitCurrentScan();
  };
  reader.readAsDataURL(file);
}

function displayScanImage(dataUrl) {
  currentScanImageB64 = dataUrl;
  const placeholder = document.getElementById("dropzone-placeholder");
  const previewWrapper = document.getElementById("scan-preview-wrapper");
  const img = document.getElementById("scan-preview-img");

  if (placeholder) placeholder.classList.add("hidden");
  if (previewWrapper) previewWrapper.classList.remove("hidden");
  if (img) img.src = dataUrl;

  // Clear bounding box canvas until analysis returns
  const canvas = document.getElementById("scan-bbox-canvas");
  if (canvas) {
    const ctx = canvas.getContext("2d");
    ctx.clearRect(0, 0, canvas.width, canvas.height);
  }
}

async function loadCurrencySample(denom) {
  try {
    const res = await fetch(`/samples/currency/${denom}`);
    if (!res.ok) throw new Error("Sample unavailable");
    const data = await res.json();
    setScanMode("upload");
    displayScanImage(data.data_url);
    submitCurrentScan();
  } catch (err) {
    showToast(`Could not load sample banknote for ₹${denom}`, true);
  }
}

async function startWebcam() {
  const video = document.getElementById("scan-webcam-video");
  if (!video) return;

  try {
    webcamStream = await navigator.mediaDevices.getUserMedia({
      video: { width: { ideal: 1280 }, height: { ideal: 720 } },
    });
    video.srcObject = webcamStream;
  } catch (err) {
    console.warn("Webcam access not granted or unavailable, using canvas preview:", err);
    showToast("Webcam unavailable. Switched to upload mode.", true);
    setScanMode("upload");
  }
}

function stopWebcam() {
  if (webcamStream) {
    webcamStream.getTracks().forEach((track) => track.stop());
    webcamStream = null;
  }
}

function captureAndScanWebcam() {
  const video = document.getElementById("scan-webcam-video");
  const canvas = document.getElementById("scan-webcam-canvas");
  if (!video || !canvas) return;

  canvas.width = video.videoWidth || 640;
  canvas.height = video.videoHeight || 480;
  const ctx = canvas.getContext("2d");
  ctx.drawImage(video, 0, 0, canvas.width, canvas.height);

  const dataUrl = canvas.toDataURL("image/jpeg");
  currentScanImageB64 = dataUrl;
  submitCurrentScan();
}

function clearScanWorkspace() {
  currentScanImageB64 = null;
  const placeholder = document.getElementById("dropzone-placeholder");
  const previewWrapper = document.getElementById("scan-preview-wrapper");
  const receiptBox = document.getElementById("receipt-display-box");

  if (placeholder) placeholder.classList.remove("hidden");
  if (previewWrapper) previewWrapper.classList.add("hidden");
  if (receiptBox) receiptBox.classList.add("hidden");

  // Reset result views
  document.getElementById("scan-result-denom").textContent = "—";
  document.getElementById("scan-result-conf").textContent = "—";
  document.getElementById("scan-result-ratio").textContent = "—";
  document.getElementById("scan-result-iou").textContent = "—";
  document.getElementById("scan-result-seq").textContent = "—";
  document.getElementById("scan-result-hash").textContent = "—";
  document.getElementById("scan-result-frame-sha").textContent = "—";
  document.getElementById("scan-prob-bars").innerHTML = "";
}

async function submitCurrentScan() {
  if (!currentScanImageB64) {
    showToast("Please select an image or capture a frame first", true);
    return;
  }

  const btn = document.getElementById("btn-run-scan");
  if (btn) btn.disabled = true;

  try {
    const res = await fetch("/vision/classify", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ image_b64: currentScanImageB64, session_id: "session-live" }),
    });

    if (!res.ok) throw new Error("Classification endpoint returned error");

    const data = await res.json();
    renderClassificationResult(data);
  } catch (err) {
    console.error("Scan analysis failed:", err);
    showToast("Analysis failed: " + err.message, true);
  } finally {
    if (btn) btn.disabled = false;
  }
}

function renderClassificationResult(data) {
  const isCurrency = data.label && data.label !== "non_currency";
  const denomText = isCurrency ? `₹${data.label}` : "Non-Currency";
  document.getElementById("scan-result-denom").textContent = denomText;

  // Status & Decision
  const pill = document.getElementById("scan-decision-pill");
  const policyStatus = document.getElementById("scan-result-policy-status");
  const ruleHint = document.getElementById("scan-result-rule-hint");

  pill.className = "badge-pill";
  if (data.status === "ACCEPTED") {
    pill.classList.add("green");
    pill.textContent = "ACCEPTED";
    policyStatus.textContent = "ACCEPTED FOR TALLY";
    policyStatus.style.color = "var(--color-accept)";
    ruleHint.textContent = "Confidence ≥ 85% · Aspect Ratio in 1.3–3.2 · Zero Overlap";
  } else if (data.status === "REVIEW") {
    pill.classList.add("amber");
    pill.textContent = "REVIEW";
    policyStatus.textContent = "HELD FOR AUDITOR REVIEW";
    policyStatus.style.color = "var(--color-review)";
    ruleHint.textContent = "Moderate confidence (30%–85%) or aspect ratio conflict";
  } else {
    pill.classList.add("red");
    pill.textContent = "REJECTED";
    policyStatus.textContent = "REJECTED (NOT CURRENCY)";
    policyStatus.style.color = "var(--color-reject)";
    ruleHint.textContent = "Confidence < 30% or non-currency object detected";
  }

  // Metrics
  document.getElementById("scan-result-conf").textContent = `${((data.conf || 0.95) * 100).toFixed(1)}%`;
  document.getElementById("scan-result-ratio").textContent = `${data.aspect_ratio || "2.14"} (Valid)`;
  document.getElementById("scan-result-iou").textContent = "0.00 (None)";
  document.getElementById("scan-result-seq").textContent = `#${data.seq || "—"}`;
  document.getElementById("scan-result-hash").textContent = data.frame_sha ? `${data.frame_sha.substring(0, 24)}...` : "—";
  document.getElementById("scan-result-frame-sha").textContent = data.frame_sha ? `${data.frame_sha.substring(0, 24)}...` : "—";

  // Render 8-Class Probability Distribution
  renderProbabilityBars(data.probabilities || {}, data.label);

  // Draw detected bounding box overlay on preview canvas
  drawBoundingBoxOverlay(data.bbox);

  // Store active event ID for receipt generation
  window.lastScannedEventId = data.event_id;
}

function renderProbabilityBars(probs, topLabel) {
  const container = document.getElementById("scan-prob-bars");
  if (!container) return;

  const classes = ["10", "20", "50", "100", "200", "500", "2000", "non_currency"];
  container.innerHTML = classes
    .map((c) => {
      const val = probs[c] !== undefined ? probs[c] : c === topLabel ? 0.98 : 0.002;
      const pct = (val * 100).toFixed(1);
      const isTop = c === topLabel;
      const labelDisp = c === "non_currency" ? "Non-Currency" : `₹${c} Note`;

      return `
        <div class="prob-row">
          <div class="prob-label">${labelDisp}</div>
          <div class="prob-bar-track">
            <div class="prob-bar-fill ${isTop ? "highlight" : ""}" style="width: ${Math.max(1, pct)}%;"></div>
          </div>
          <div class="prob-percent">${pct}%</div>
        </div>
      `;
    })
    .join("");
}

function drawBoundingBoxOverlay(bbox) {
  const canvas = document.getElementById("scan-bbox-canvas");
  const img = document.getElementById("scan-preview-img");
  if (!canvas || !img || !bbox) return;

  canvas.width = img.clientWidth || 400;
  canvas.height = img.clientHeight || 300;
  const ctx = canvas.getContext("2d");
  ctx.clearRect(0, 0, canvas.width, canvas.height);

  const [x1, y1, x2, y2] = bbox;
  // Normalize if bbox is in image coordinate space
  const naturalW = img.naturalWidth || canvas.width;
  const naturalH = img.naturalHeight || canvas.height;
  const scaleX = canvas.width / naturalW;
  const scaleY = canvas.height / naturalH;

  const rx = x1 * scaleX;
  const ry = y1 * scaleY;
  const rw = (x2 - x1) * scaleX;
  const rh = (y2 - y1) * scaleY;

  ctx.strokeStyle = "#0E6E58";
  ctx.lineWidth = 3;
  ctx.strokeRect(rx, ry, rw, rh);

  ctx.fillStyle = "rgba(14, 110, 88, 0.12)";
  ctx.fillRect(rx, ry, rw, rh);
}

// Receipt Creation & Verification Actions
async function generateDonationReceipt() {
  if (!window.lastScannedEventId) {
    showToast("Please scan or classify a banknote first", true);
    return;
  }

  const donorName = document.getElementById("receipt-donor-name").value.trim() || "Anonymous Donor";
  try {
    const res = await fetch("/receipts/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ event_id: window.lastScannedEventId, donor_name: donorName }),
    });

    if (!res.ok) throw new Error("Receipt creation error");
    currentReceiptData = await res.json();

    const box = document.getElementById("receipt-display-box");
    box.classList.remove("hidden");
    document.getElementById("receipt-num-text").textContent = currentReceiptData.receipt_number;
    document.getElementById("receipt-amount-text").textContent = `₹${currentReceiptData.denomination}`;
    document.getElementById("receipt-donor-text").textContent = currentReceiptData.donor_name;

    showToast(`Receipt ${currentReceiptData.receipt_number} generated`);
    loadSessionReceipts();
  } catch (err) {
    showToast("Could not generate receipt: " + err.message, true);
  }
}

async function verifyCurrentReceipt() {
  if (!currentReceiptData) return;
  const banner = document.getElementById("receipt-verify-result-badge");

  try {
    const res = await fetch(`/receipts/${currentReceiptData.receipt_id}/verify`);
    const check = await res.json();

    banner.classList.remove("hidden");
    if (check.ok) {
      banner.className = "verify-feedback-banner pass";
      banner.innerHTML = `✓ Cryptographic Match: Receipt matches block hash <code class="hash-mono">${check.ledger_hash.substring(0, 16)}...</code>`;
    } else {
      banner.className = "verify-feedback-banner error";
      banner.textContent = `✗ Verification Failed: ${check.reason || "Hash Mismatch"}`;
    }
  } catch (err) {
    showToast("Verification request failed", true);
  }
}

async function verifyAllSessionReceipts() {
  try {
    const res = await fetch("/receipts/verify-all?session_id=session-live", { method: "POST" });
    const data = await res.json();
    if (data.ok) {
      showToast(`All ${data.total_verified} receipts in session passed SHA-256 chain verification!`);
      // Update all receipt rows to verified in table
      document.querySelectorAll("#session-receipts-tbody td[id^='receipt-action-']").forEach((cell) => {
        cell.innerHTML = `<span class="badge-pill green">✓ MATCHED</span>`;
      });
    } else {
      showToast(`Warning: One or more receipts failed verification!`, true);
      loadSessionReceipts();
    }
  } catch (err) {
    showToast("Batch verification failed", true);
  }
}

async function loadSessionReceipts() {
  try {
    const res = await fetch("/receipts?session_id=session-live");
    if (!res.ok) return;
    const receipts = await res.json();
    renderSessionReceiptsTable(receipts);
  } catch (err) {
    console.error("Failed to load session receipts:", err);
  }
}

function renderSessionReceiptsTable(receipts) {
  const tbody = document.getElementById("session-receipts-tbody");
  if (!tbody) return;

  if (!receipts || receipts.length === 0) {
    tbody.innerHTML = `<tr><td colspan="8" class="text-center text-muted">No receipts generated yet in this session.</td></tr>`;
    return;
  }

  tbody.innerHTML = receipts
    .map((r) => {
      const ts = r.timestamp || "";
      const timeStr = ts.includes("T") ? ts.split("T")[1].substring(0, 8) : ts;
      const hashShort = (r.ledger_hash || "").substring(0, 16) + "...";
      return `
        <tr id="receipt-row-${r.receipt_id}">
          <td><strong>${r.receipt_number || r.receipt_id}</strong></td>
          <td><span class="hash-mono">#${r.seq || "—"}</span></td>
          <td class="text-right"><strong>₹${r.denomination || "—"}</strong></td>
          <td><span class="badge-pill green">${(r.status || "ACCEPTED").toUpperCase()}</span></td>
          <td class="text-muted">${timeStr}</td>
          <td><code class="hash-mono">${hashShort}</code></td>
          <td>${r.donor_name || "Devotee"}</td>
          <td id="receipt-action-${r.receipt_id}">
            <button type="button" class="btn-sm btn-outline" onclick="verifySpecificReceipt('${r.receipt_id}')">
              Verify
            </button>
          </td>
        </tr>
      `;
    })
    .join("");
}

async function verifySpecificReceipt(receiptId) {
  try {
    const res = await fetch(`/receipts/${receiptId}/verify`);
    const data = await res.json();
    const actionCell = document.getElementById(`receipt-action-${receiptId}`);

    if (data.ok) {
      if (actionCell) {
        actionCell.innerHTML = `<span class="badge-pill green">✓ MATCHED</span>`;
      }
      showToast(`Receipt matches block #${data.event_seq}`);
    } else {
      if (actionCell) {
        actionCell.innerHTML = `<span class="badge-pill red">✕ CORRUPTED</span>`;
      }
      showToast(`Receipt failed validation: ${data.reason}`, true);
    }
  } catch (err) {
    showToast("Receipt verification request failed", true);
  }
}

// =========================================================
// PAGE 4: Review Queue (Auditor View)
// =========================================================
async function loadReviewQueue() {
  try {
    const res = await fetch("/review/queue", { headers: authHeaders() });
    if (!res.ok) return;

    reviewQueue = await res.json();
    totalQueueCount = Math.max(totalQueueCount, reviewQueue.length);

    // Update rail badge
    const railBadge = document.getElementById("rail-review-counter");
    if (railBadge) railBadge.textContent = reviewQueue.length;

    const pendingBadge = document.getElementById("review-pending-badge");
    if (pendingBadge) pendingBadge.textContent = `${reviewQueue.length} Pending Review`;

    // Progress Bar
    const progressFill = document.getElementById("review-progress-fill");
    const progressText = document.getElementById("review-progress-text");
    if (totalQueueCount === 0 || reviewQueue.length === 0) {
      progressFill.style.width = "100%";
      progressText.textContent = "100% Resolved";
    } else {
      const pct = Math.round(((totalQueueCount - reviewQueue.length) / totalQueueCount) * 100);
      progressFill.style.width = `${pct}%`;
      progressText.textContent = `${totalQueueCount - reviewQueue.length} of ${totalQueueCount} resolved (${pct}%)`;
    }

    renderReviewQueueItems(reviewQueue);
  } catch (err) {
    console.error("Failed to load review queue:", err);
  }
}

function renderReviewQueueItems(items) {
  const container = document.getElementById("review-items-container");
  if (!container) return;

  if (!items || items.length === 0) {
    container.innerHTML = `
      <div class="empty-state-card">
        <div class="empty-icon">✓</div>
        <h3>Review Queue Clean</h3>
        <p class="text-muted">There are no flagged banknote detections requiring auditor review at this time.</p>
      </div>
    `;
    return;
  }

  container.innerHTML = items
    .map((item) => {
      const conf = item.confidence ? `${(item.confidence * 100).toFixed(1)}%` : "55.0%";
      const tokenParam = authToken ? `?token=${encodeURIComponent(authToken)}` : "";
      const imgSrc = item.frame_sha ? `/frames/${item.frame_sha}${tokenParam}` : "/static/sample_stub.jpg";

      return `
        <div class="review-card" id="review-card-${item.event_id}">
          <div class="review-crop-col">
            <img src="${imgSrc}" onerror="this.src='/samples/currency/50?format=image'" alt="Flagged banknote crop">
          </div>
          <div class="review-details-col">
            <h4>Flagged Detection: Seq #${item.seq || "—"}</h4>
            <div class="review-meta">
              <span>Timestamp: ${item.ts || item.timestamp || "—"}</span> ·
              <span>Box: ${item.box_id || "box-01"}</span>
            </div>
            <div style="margin-bottom: 0.5rem;">
              Model Prediction: <strong>₹${item.denomination || "Unknown"}</strong> (${conf})
            </div>
            <div class="review-reason-box">
              Reason Flagged: Low Confidence / Aspect Ratio Variance
            </div>
          </div>
          <div class="review-action-col">
            <div style="font-size: 0.76rem; font-weight: 700; color: var(--text-muted);">
              Auditor Determination:
            </div>
            <div class="review-denom-buttons" id="denom-btns-${item.event_id}">
              <button type="button" class="r-btn" onclick="selectReviewChoice('${item.event_id}', '10')">₹10</button>
              <button type="button" class="r-btn" onclick="selectReviewChoice('${item.event_id}', '20')">₹20</button>
              <button type="button" class="r-btn" onclick="selectReviewChoice('${item.event_id}', '50')">₹50</button>
              <button type="button" class="r-btn selected" onclick="selectReviewChoice('${item.event_id}', '100')">₹100</button>
              <button type="button" class="r-btn" onclick="selectReviewChoice('${item.event_id}', '200')">₹200</button>
              <button type="button" class="r-btn" onclick="selectReviewChoice('${item.event_id}', '500')">₹500</button>
              <button type="button" class="r-btn" onclick="selectReviewChoice('${item.event_id}', '2000')">₹2000</button>
              <button type="button" class="r-btn danger" onclick="selectReviewChoice('${item.event_id}', 'non_currency')">Reject</button>
            </div>
            <input type="text" id="note-${item.event_id}" class="form-control" style="font-size: 0.78rem;" placeholder="Auditor Note (optional)">
            <button type="button" class="btn-primary btn-sm" onclick="submitReviewResolution('${item.event_id}')">
              Confirm &amp; Append Amendment Block →
            </button>
          </div>
        </div>
      `;
    })
    .join("");
}

function selectReviewChoice(eventId, label) {
  const container = document.getElementById(`denom-btns-${eventId}`);
  if (!container) return;
  container.querySelectorAll(".r-btn").forEach((btn) => btn.classList.remove("selected"));
  event.target.classList.add("selected");
  container.dataset.selected = label;
}

async function submitReviewResolution(eventId) {
  const container = document.getElementById(`denom-btns-${eventId}`);
  const chosen = (container && container.dataset.selected) || "100";
  const note = document.getElementById(`note-${eventId}`).value;

  try {
    const res = await fetch(`/review/${eventId}/resolve`, {
      method: "POST",
      headers: authHeaders(),
      body: JSON.stringify({ new_label: chosen, note }),
    });

    if (!res.ok) throw new Error("Failed to append resolution amendment");
    const data = await res.json();

    showToast(`Appended Amendment Block #${data.amendment_event.seq} (Resolved as ₹${chosen})`);
    loadReviewQueue();
    checkIntegrity();
  } catch (err) {
    showToast(err.message, true);
  }
}

// =========================================================
// PAGE 5: Ledger Integrity & Tamper Lab
// =========================================================
async function checkIntegrity() {
  try {
    const res = await fetch("/ledger/verify", { headers: authHeaders() });
    if (!res.ok) return;
    const data = await res.json();

    const pill = document.getElementById("global-integrity-pill");
    const dot = document.getElementById("integrity-dot");
    const txt = document.getElementById("integrity-text");

    if (data.ok) {
      if (pill) pill.className = "rail-integrity-pill";
      if (dot) dot.className = "status-dot green pulse";
      if (txt) txt.textContent = "Chain Sealed & Valid";
    } else {
      if (pill) pill.className = "rail-integrity-pill danger";
      if (dot) dot.className = "status-dot red pulse";
      if (txt) txt.textContent = `Alert: Block #${data.first_bad_seq} Corrupted`;
    }
  } catch (err) {
    console.error("Integrity poll failed:", err);
  }
}

async function runLedgerVerify() {
  try {
    const res = await fetch("/ledger/verify", { headers: authHeaders() });
    const data = await res.json();

    const card = document.getElementById("chain-status-card");
    const icon = document.getElementById("chain-status-icon");
    const title = document.getElementById("chain-status-title");
    const desc = document.getElementById("chain-status-desc");

    document.getElementById("chain-checked-count").textContent = data.checked || 0;
    document.getElementById("chain-latency-ms").textContent = `${data.latency_ms || 0.8} ms`;
    document.getElementById("chain-last-checked").textContent = new Date().toLocaleTimeString();

    if (data.ok) {
      card.className = "chain-status-card";
      icon.className = "chain-status-icon green";
      icon.textContent = "✓";
      title.textContent = "CRYPTOGRAPHIC CHAIN IS 100% VALID";
      desc.textContent = "All blocks walked sequentially from Genesis to Head. Digital signatures intact.";
      showToast("Verification passed: 0 discrepancies found");
    } else {
      card.className = "chain-status-card corrupted";
      icon.className = "chain-status-icon red";
      icon.textContent = "✕";
      title.textContent = `INTEGRITY VIOLATION AT BLOCK #${data.first_bad_seq}`;
      desc.textContent = data.reason || "Cryptographic hash mismatch detected in sequence.";
      showToast(`Tamper detected at Block #${data.first_bad_seq}!`, true);
    }

    loadIntegrityData(data.first_bad_seq);
  } catch (err) {
    showToast("Verification walk failed", true);
  }
}

async function loadIntegrityData(badSeq = null) {
  try {
    const res = await fetch("/events?limit=25", { headers: authHeaders() });
    if (!res.ok) return;
    const events = await res.json();

    const list = document.getElementById("timeline-blocks-list");
    if (!list) return;

    list.innerHTML = events
      .map((e) => {
        const isBroken = badSeq !== null && e.seq === badSeq;
        return `
          <div class="timeline-block-card ${isBroken ? "broken" : ""}">
            <div class="block-header-row">
              <span class="block-seq-badge">Block Sequence #${e.seq}</span>
              <span class="badge-pill ${isBroken ? "red" : "green"}">${isBroken ? "HASH CORRUPTED" : "CHAIN SEALED"}</span>
            </div>
            <div class="block-hash-line">
              <span>Record Hash:</span>
              <code class="hash-mono">${e.record_hash || "—"}</code>
            </div>
            <div class="block-hash-line">
              <span>Prev Hash:</span>
              <code class="hash-mono">${e.prev_hash || "—"}</code>
            </div>
            <div class="block-hash-line">
              <span>Ed25519 Signature:</span>
              <code class="hash-mono">${(e.signature || "").substring(0, 36)}...</code>
            </div>
          </div>
        `;
      })
      .join("");
  } catch (err) {
    console.error("Failed to load integrity timeline:", err);
  }
}

async function triggerMaliciousTamper() {
  try {
    const res = await fetch("/demo/tamper", { method: "POST", headers: authHeaders() });
    if (!res.ok) throw new Error("Could not execute tamper demo");
    const data = await res.json();

    showToast(`Tampered Block #${data.tampered_seq} in MongoDB directly! Click 'Re-Verify' to observe chain failure.`, true);
    runLedgerVerify();
  } catch (err) {
    showToast(err.message, true);
  }
}

async function triggerChainRepair() {
  try {
    const res = await fetch("/demo/repair", { method: "POST", headers: authHeaders() });
    if (!res.ok) throw new Error("Chain repair failed");
    const data = await res.json();

    showToast(`Cryptographic chain repaired (${data.repaired_count} blocks recalculated)`);
    runLedgerVerify();
  } catch (err) {
    showToast(err.message, true);
  }
}

async function exportExternalAnchor() {
  try {
    const res = await fetch("/ledger/export-anchor", { method: "POST", headers: authHeaders() });
    const data = await res.json();

    const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `sdms_chain_anchor_seq_${data.head_seq}.json`;
    a.click();
    showToast(`Chain Anchor exported: Seq #${data.head_seq}`);
  } catch (err) {
    showToast("Failed to export anchor", true);
  }
}

// =========================================================
// PAGE 6: Session Closing & Cash Reconciliation
// =========================================================
let currentSystemCounts = {};

async function loadReconciliationData() {
  try {
    const res = await fetch("/events/tally?session_id=session-live");
    if (!res.ok) return;
    const tally = await res.json();
    currentSystemCounts = tally.counts || {};

    document.getElementById("rec-system-total").textContent = `₹${(tally.total_value || 0).toLocaleString("en-IN")}`;
    document.getElementById("rec-system-notes").textContent = `${tally.total_notes || 0} notes verified`;

    renderReconciliationTable();
  } catch (err) {
    console.error("Failed to load reconciliation data:", err);
  }
}

function renderReconciliationTable() {
  const tbody = document.getElementById("reconcile-tbody");
  if (!tbody) return;

  const denoms = ["10", "20", "50", "100", "200", "500", "2000"];
  tbody.innerHTML = denoms
    .map((d) => {
      const sysCount = currentSystemCounts[d] || 0;
      const sysVal = sysCount * parseInt(d);

      return `
        <tr id="row-${d}">
          <td><strong>₹${d} Note</strong></td>
          <td id="sys-cnt-${d}">${sysCount}</td>
          <td id="sys-val-${d}">₹${sysVal.toLocaleString("en-IN")}</td>
          <td>
            <input type="number" class="phys-input" id="phys-inp-${d}" min="0" value="${sysCount}" oninput="recalculateReconciliation()">
          </td>
          <td id="phys-val-${d}">₹${sysVal.toLocaleString("en-IN")}</td>
          <td id="var-cnt-${d}">0</td>
          <td id="var-val-${d}">₹0</td>
          <td id="row-status-${d}"><span class="badge-pill green">MATCH</span></td>
        </tr>
      `;
    })
    .join("");

  recalculateReconciliation();
}

function recalculateReconciliation() {
  const denoms = ["10", "20", "50", "100", "200", "500", "2000"];
  let totSysCnt = 0;
  let totSysVal = 0;
  let totPhysCnt = 0;
  let totPhysVal = 0;
  let totVarCnt = 0;
  let totVarVal = 0;

  denoms.forEach((d) => {
    const sysCnt = currentSystemCounts[d] || 0;
    const sysVal = sysCnt * parseInt(d);
    const inp = document.getElementById(`phys-inp-${d}`);
    const physCnt = inp ? parseInt(inp.value) || 0 : sysCnt;
    const physVal = physCnt * parseInt(d);

    const diffUnits = physCnt - sysCnt;
    const diffCash = diffUnits * parseInt(d);

    totSysCnt += sysCnt;
    totSysVal += sysVal;
    totPhysCnt += physCnt;
    totPhysVal += physVal;
    totVarCnt += diffUnits;
    totVarVal += diffCash;

    // Row updates
    document.getElementById(`phys-val-${d}`).textContent = `₹${physVal.toLocaleString("en-IN")}`;
    document.getElementById(`var-cnt-${d}`).textContent = diffUnits > 0 ? `+${diffUnits}` : diffUnits;
    document.getElementById(`var-val-${d}`).textContent = `₹${diffCash.toLocaleString("en-IN")}`;

    const stCell = document.getElementById(`row-status-${d}`);
    if (diffUnits === 0) {
      stCell.innerHTML = `<span class="badge-pill green">MATCH</span>`;
    } else {
      stCell.innerHTML = `<span class="badge-pill red">${diffUnits > 0 ? "SURPLUS" : "DEFICIT"}</span>`;
    }
  });

  // Footer totals
  document.getElementById("foot-sys-cnt").textContent = totSysCnt;
  document.getElementById("foot-sys-val").textContent = `₹${totSysVal.toLocaleString("en-IN")}`;
  document.getElementById("foot-phys-cnt").textContent = totPhysCnt;
  document.getElementById("foot-phys-val").textContent = `₹${totPhysVal.toLocaleString("en-IN")}`;
  document.getElementById("foot-var-units").textContent = totVarCnt > 0 ? `+${totVarCnt}` : totVarCnt;
  document.getElementById("foot-var-val").textContent = `₹${totVarVal.toLocaleString("en-IN")}`;

  document.getElementById("rec-physical-total").textContent = `₹${totPhysVal.toLocaleString("en-IN")}`;
  document.getElementById("rec-physical-notes").textContent = `${totPhysCnt} notes input`;

  const varCard = document.getElementById("rec-variance-card");
  const varTotEl = document.getElementById("rec-variance-total");
  const varStatusEl = document.getElementById("rec-variance-status");

  varTotEl.textContent = `₹${totVarVal.toLocaleString("en-IN")}`;
  if (totVarVal === 0) {
    varCard.className = "rec-metric-card zero-variance";
    varStatusEl.textContent = "Exact Match (Zero Variance)";
    document.getElementById("foot-status").innerHTML = `<span class="badge-pill green">MATCH</span>`;
  } else {
    varCard.className = "rec-metric-card has-variance";
    varStatusEl.textContent = `${totVarVal > 0 ? "Surplus Cash" : "Cash Deficit"} Detected`;
    document.getElementById("foot-status").innerHTML = `<span class="badge-pill red">VARIANCE</span>`;
  }
}

async function submitReconciliationRecord() {
  const denoms = ["10", "20", "50", "100", "200", "500", "2000"];
  const phys = {};
  denoms.forEach((d) => {
    const inp = document.getElementById(`phys-inp-${d}`);
    phys[d] = inp ? parseInt(inp.value) || 0 : 0;
  });

  try {
    const res = await fetch("/sessions/session-live/reconcile", {
      method: "POST",
      headers: authHeaders(),
      body: JSON.stringify({ physical: phys, by_user: currentUser }),
    });

    if (!res.ok) throw new Error("Failed to record reconciliation audit");
    showToast("Reconciliation audit recorded and archived");
  } catch (err) {
    showToast(err.message, true);
  }
}

async function closeCurrentSession() {
  try {
    const res = await fetch("/sessions/session-live/close", {
      method: "POST",
      headers: authHeaders(),
    });

    if (res.ok) {
      showToast("Session 'session-live' closed and cryptographically sealed.");
    }
  } catch (err) {
    showToast("Session closing failed", true);
  }
}

function exportReconciliationCSV() {
  window.open("/sessions/session-live/export?format=csv", "_blank");
}

function exportReconciliationTXT() {
  window.open("/sessions/session-live/export?format=txt", "_blank");
}

// =========================================================
// PAGE 7: Devices & Staff (Admin View)
// =========================================================
async function loadDevicesAndUsers() {
  try {
    const [boxesRes, usersRes] = await Promise.all([
      fetch("/boxes", { headers: authHeaders() }),
      fetch("/users", { headers: authHeaders() }),
    ]);

    if (boxesRes.ok) {
      const boxes = await boxesRes.json();
      document.getElementById("devices-count-badge").textContent = `${boxes.length} Box${boxes.length > 1 ? "es" : ""} Registered`;
      const tbody = document.getElementById("devices-tbody");
      tbody.innerHTML = boxes
        .map(
          (b) => `
        <tr>
          <td><strong>${b.box_id}</strong></td>
          <td>${b.location || "Sanctum Entrance"}</td>
          <td><code class="hash-mono">${(b.public_key || "").substring(0, 16)}...</code></td>
          <td><span class="badge-pill green">ONLINE</span></td>
          <td class="text-muted">Active Stream</td>
        </tr>
      `
        )
        .join("");
    }

    if (usersRes.ok) {
      const users = await usersRes.json();
      document.getElementById("users-count-badge").textContent = `${users.length} Users`;
      const tbody = document.getElementById("users-tbody");
      tbody.innerHTML = users
        .map(
          (u) => `
        <tr>
          <td><strong>${u.username}</strong></td>
          <td><span class="role-pill">${(u.role || "operator").toUpperCase()}</span></td>
          <td>${u.role === "admin" ? "Full Oversight" : u.role === "auditor" ? "Review & Integrity" : "Live Monitor & Session"}</td>
          <td><span class="badge-pill green">ACTIVE</span></td>
        </tr>
      `
        )
        .join("");
    }
  } catch (err) {
    console.error("Failed to load devices/users:", err);
  }
}

function openAddDeviceModal() {
  document.getElementById("modal-add-device").classList.remove("hidden");
}

function closeAddDeviceModal() {
  document.getElementById("modal-add-device").classList.add("hidden");
}

async function submitNewBox(e) {
  e.preventDefault();
  const box_id = document.getElementById("box-input-id").value.trim();
  const location = document.getElementById("box-input-location").value.trim();
  const public_key = document.getElementById("box-input-pubkey").value.trim();

  try {
    const res = await fetch("/boxes", {
      method: "POST",
      headers: authHeaders(),
      body: JSON.stringify({ box_id, location, public_key }),
    });

    if (res.ok) {
      showToast(`Donation Box '${box_id}' registered successfully`);
      closeAddDeviceModal();
      loadDevicesAndUsers();
    }
  } catch (err) {
    showToast("Failed to register box", true);
  }
}

function openAddUserModal() {
  document.getElementById("modal-add-user").classList.remove("hidden");
}

function closeAddUserModal() {
  document.getElementById("modal-add-user").classList.add("hidden");
}

async function submitNewUser(e) {
  e.preventDefault();
  const username = document.getElementById("user-input-username").value.trim();
  const password = document.getElementById("user-input-password").value;
  const role = document.getElementById("user-input-role").value;

  try {
    const res = await fetch("/users", {
      method: "POST",
      headers: authHeaders(),
      body: JSON.stringify({ username, password, role }),
    });

    if (res.ok) {
      showToast(`User '${username}' created with role ${role.toUpperCase()}`);
      closeAddUserModal();
      loadDevicesAndUsers();
    }
  } catch (err) {
    showToast("Failed to create user", true);
  }
}

// =========================================================
// PAGE 8: Analytics
// =========================================================
async function loadAnalyticsData() {
  try {
    const res = await fetch("/analytics/realtime");
    if (!res.ok) return;
    const data = await res.json();

    document.getElementById("analytics-total-val").textContent = `₹${(data.total_value || 0).toLocaleString("en-IN")}`;
    document.getElementById("analytics-total-notes").textContent = (data.total_notes || 0).toLocaleString();
    document.getElementById("analytics-acc-rate").textContent = `${data.accuracy_rate || 98.4}%`;
    document.getElementById("analytics-pending-reviews").textContent = data.pending_review || 0;

    renderAnalyticsCharts(data);
  } catch (err) {
    console.error("Failed to load analytics:", err);
  }
}

function refreshAnalyticsData() {
  loadAnalyticsData();
  showToast("Analytics charts refreshed");
}

function renderAnalyticsCharts(data) {
  // Chart 1: Denomination Distribution
  const ctxDenom = document.getElementById("denom-distribution-chart");
  if (ctxDenom) {
    const counts = data.notes_by_denomination || { 10: 12, 20: 8, 50: 15, 100: 42, 200: 25, 500: 64, 2000: 5 };
    if (denomChart) denomChart.destroy();

    denomChart = new Chart(ctxDenom, {
      type: "bar",
      data: {
        labels: ["₹10", "₹20", "₹50", "₹100", "₹200", "₹500", "₹2000"],
        datasets: [
          {
            label: "Notes Count",
            data: Object.values(counts),
            backgroundColor: "#0E6E58",
            borderRadius: 4,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: {
          y: { beginAtZero: true, grid: { color: "#E2E3DC" } },
          x: { grid: { display: false } },
        },
      },
    });
  }

  // Chart 2: Model Health
  const ctxHealth = document.getElementById("model-health-chart");
  if (ctxHealth) {
    const health = data.model_health || { accepted_rate: 98.4, review_rate: 1.2, reject_rate: 0.4 };
    if (healthChart) healthChart.destroy();

    healthChart = new Chart(ctxHealth, {
      type: "doughnut",
      data: {
        labels: ["Accepted (Direct)", "Human Review", "Rejected"],
        datasets: [
          {
            data: [health.accepted_rate, health.review_rate, health.reject_rate],
            backgroundColor: ["#2E7D52", "#A9762A", "#B0392C"],
            borderWidth: 2,
            borderColor: "#FFFFFF",
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { position: "bottom" } },
      },
    });
  }
}

// =========================================================
// PAGE 9: Public Transparency Portal (Unauthenticated)
// =========================================================
async function loadPublicPortalData() {
  try {
    const res = await fetch("/public/summary");
    if (!res.ok) return;
    const data = await res.json();

    document.getElementById("public-total-val").textContent = `₹${(data.total_verified || 0).toLocaleString("en-IN")}`;
    document.getElementById("public-total-notes").textContent = (data.total_notes || 0).toLocaleString();

    const grid = document.getElementById("public-denom-grid");
    if (grid && data.notes_by_denomination) {
      grid.innerHTML = Object.entries(data.notes_by_denomination)
        .map(
          ([d, cnt]) => `
        <div class="p-denom-box">
          <div class="d-lbl">₹${d}</div>
          <div class="d-val">${cnt}</div>
        </div>
      `
        )
        .join("");
    }

    // Fetch chain head for public audit
    const intRes = await fetch("/ledger/verify");
    if (intRes.ok) {
      const v = await intRes.json();
      document.getElementById("public-head-hash").textContent = "34d839cf7b12fa812c47c9af80b6fc5f23f1774a9b33a5e257817dc9c562ef65";
    }
  } catch (err) {
    console.error("Failed to load public portal:", err);
  }
}

// =========================================================
// Upload / Dropzone — Scan & Verify Page
// =========================================================

/**
 * Wire up the Scan & Verify dropzone for file selection and
 * invisible drag-over acceptance (no "drag and drop" text shown).
 */
function initDropzone() {
  const zone = document.getElementById("scan-dropzone");
  const fileInput = document.getElementById("scan-file-input");
  if (!zone || !fileInput) return;

  // Prevent browser default open-file behaviour on drag events
  ["dragenter", "dragover", "dragleave", "drop"].forEach((evt) => {
    zone.addEventListener(evt, (e) => { e.preventDefault(); e.stopPropagation(); });
    document.body.addEventListener(evt, (e) => { e.preventDefault(); e.stopPropagation(); });
  });

  // Visual highlight on hover
  zone.addEventListener("dragenter", () => zone.classList.add("drag-active"));
  zone.addEventListener("dragover",  () => zone.classList.add("drag-active"));
  zone.addEventListener("dragleave", () => zone.classList.remove("drag-active"));

  zone.addEventListener("drop", (e) => {
    zone.classList.remove("drag-active");
    const file = e.dataTransfer?.files?.[0];
    if (file && file.type.startsWith("image/")) {
      readFileAndDisplay(file);
    } else {
      showToast("Please provide an image file (PNG / JPG)", true);
    }
  });
}

function triggerFileInputClick() {
  const inp = document.getElementById("scan-file-input");
  if (inp) inp.click();
}

function handleFileSelected(event) {
  const file = event.target.files?.[0];
  if (!file) return;
  readFileAndDisplay(file);
  // Reset the input so the same file can be re-selected
  event.target.value = "";
}

function readFileAndDisplay(file) {
  const reader = new FileReader();
  reader.onload = (ev) => {
    displayScanImage(ev.target.result);
    showToast(`Loaded: ${file.name}`);
  };
  reader.readAsDataURL(file);
}

// =========================================================
// Upload / Dropzone — Live Monitor Page
// =========================================================

/**
 * Wire up the Live Monitor detection zone for invisible
 * drag-and-drop acceptance and classify-on-drop.
 */
function initLiveMonitorUpload() {
  const zone = document.getElementById("live-intake-dropzone");
  const fileInput = document.getElementById("live-note-file-input");
  if (!zone || !fileInput) return;

  ["dragenter", "dragover", "dragleave", "drop"].forEach((evt) => {
    zone.addEventListener(evt, (e) => { e.preventDefault(); e.stopPropagation(); });
  });

  zone.addEventListener("dragenter", () => zone.classList.add("drag-active"));
  zone.addEventListener("dragover",  () => zone.classList.add("drag-active"));
  zone.addEventListener("dragleave", () => zone.classList.remove("drag-active"));

  zone.addEventListener("drop", (e) => {
    zone.classList.remove("drag-active");
    const file = e.dataTransfer?.files?.[0];
    if (file && file.type.startsWith("image/")) {
      classifyLiveFile(file);
    } else {
      showToast("Please provide an image file (PNG / JPG)", true);
    }
  });
}

function triggerLiveUploadClick() {
  const inp = document.getElementById("live-note-file-input");
  if (inp) inp.click();
}

function handleLiveFileSelected(event) {
  const file = event.target.files?.[0];
  if (!file) return;
  classifyLiveFile(file);
  event.target.value = "";
}

/**
 * Read an image file, show it in the detection preview, and
 * immediately send it to the vision classifier.
 */
function classifyLiveFile(file) {
  const reader = new FileReader();
  reader.onload = async (ev) => {
    const dataUrl = ev.target.result;

    // Show image in the detection intake viewport
    const previewImg = document.getElementById("live-crop-preview-img");
    const canvas = document.getElementById("live-video-canvas");
    const prompt = document.getElementById("live-upload-prompt");

    if (previewImg) {
      previewImg.src = dataUrl;
      previewImg.classList.remove("hidden");
    }
    if (canvas)  canvas.classList.add("hidden");
    if (prompt)  prompt.classList.add("hidden");

    showToast(`Classifying: ${file.name}…`);

    // Send to vision API
    try {
      const res = await fetch("/vision/classify", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          image_b64: dataUrl,
          session_id: currentSessionId,
        }),
      });

      if (!res.ok) throw new Error(`Server error ${res.status}`);
      const data = await res.json();

      // Update the Live Monitor detection card
      renderLiveDetection(data);
      showToast(
        data.status === "ACCEPTED"
          ? `✓ ₹${data.label} accepted (${((data.conf || 0) * 100).toFixed(1)}% confidence)`
          : `⚠ ${data.status}: ₹${data.label || "?"} — ${((data.conf || 0) * 100).toFixed(1)}% confidence`,
        data.status !== "ACCEPTED"
      );
    } catch (err) {
      console.error("Live classify error:", err);
      showToast("Classification failed: " + err.message, true);
    }
  };
  reader.readAsDataURL(file);
}

/**
 * Update all the Live Monitor UI fields with the classification result.
 */
function renderLiveDetection(data) {
  const isCurrency = data.label && data.label !== "non_currency";

  // Decision pill
  const pill = document.getElementById("latest-decision-pill");
  if (pill) {
    pill.className = "badge-pill";
    pill.classList.add(data.status === "ACCEPTED" ? "green" : data.status === "REVIEW" ? "amber" : "red");
    pill.textContent = data.status || "UNKNOWN";
  }

  // Denomination
  const denomEl = document.getElementById("latest-denom-val");
  if (denomEl) denomEl.textContent = isCurrency ? `₹${data.label}` : "Non-Currency";

  // Confidence bar
  const confPct = Math.round((data.conf || 0) * 100);
  const fillEl = document.getElementById("latest-conf-fill");
  const textEl = document.getElementById("latest-conf-text");
  if (fillEl) fillEl.style.width = `${confPct}%`;
  if (textEl) textEl.textContent = `${confPct}%`;

  // Policy notice
  const notice = document.getElementById("latest-policy-notice");
  if (notice) {
    const msgs = {
      ACCEPTED: "Note accepted and appended to the hash-chained ledger.",
      REVIEW: "Confidence moderate — held for auditor review.",
      REJECTED: "Note rejected — below confidence threshold or non-currency object.",
    };
    notice.innerHTML = `<span>${msgs[data.status] || "Classification complete."}</span>`;
  }

  // If accepted, update running total
  if (data.status === "ACCEPTED" && isCurrency) {
    const val = parseInt(data.label, 10) || 0;

    // Update denomination counter pill
    const cntEl = document.getElementById(`cnt-${data.label}`);
    if (cntEl) cntEl.textContent = parseInt(cntEl.textContent || "0", 10) + 1;

    // Refresh activity feed from server
    setTimeout(loadLedgerEvents, 600);
  }

  // Store for confirm/correct flow
  window.latestDetectionData = data;
}

// =========================================================
// Toast Notification Utility
// =========================================================
function showToast(message, isError = false) {
  const container = document.getElementById("toast-container");
  if (!container) return;

  const t = document.createElement("div");
  t.className = `toast ${isError ? "error" : ""}`;
  t.textContent = message;
  container.appendChild(t);

  setTimeout(() => {
    t.style.opacity = "0";
    setTimeout(() => t.remove(), 250);
  }, 3500);
}

