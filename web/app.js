const API = "/api/v1";

const state = {
  sessionId: null,
  file: null,
  aadhaarFront: null,
  aadhaarBack: null,
  documentKind: "aadhaar",
  stream: null,
  captureTimer: null,
  sendingFrame: false,
  snapshot: null,
  records: [],
  auth: null,
  csrfToken: sessionStorage.getItem("drishti_csrf"),
  continuityGraph: null,
};

let graphResizeObserver;

const $ = (selector) => document.querySelector(selector);
const elements = {
  alert: $("#alert"),
  input: $("#document-input"),
  drop: $("#drop-zone"),
  fileLabel: $("#file-label"),
  preview: $("#document-preview"),
  placeholder: $("#preview-placeholder"),
  analyze: $("#analyze-button"),
  aadhaarFields: $("#aadhaar-upload-fields"),
  travelField: $("#travel-upload-field"),
  aadhaarFrontInput: $("#aadhaar-front-input"),
  aadhaarBackInput: $("#aadhaar-back-input"),
  aadhaarFrontLabel: $("#aadhaar-front-label"),
  aadhaarBackLabel: $("#aadhaar-back-label"),
  aadhaarPreviews: $("#aadhaar-previews"),
  aadhaarFrontPreview: $("#aadhaar-front-preview"),
  aadhaarBackPreview: $("#aadhaar-back-preview"),
  documentPanel: $("#document-panel"),
  facePanel: $("#face-panel"),
  decisionPanel: $("#decision-panel"),
  cameraButton: $("#camera-button"),
  skipFace: $("#skip-face-button"),
  video: $("#camera"),
  canvas: $("#capture-canvas"),
  cameraState: $("#camera-state"),
  instruction: $("#face-instruction"),
  captureQuality: $("#capture-quality"),
  captureQualityLabel: $("#capture-quality-label"),
  captureProgress: $("#capture-progress"),
  qualityGuidance: $("#quality-guidance"),
  identity: $("#identity-summary"),
  history: $("#history-list"),
  recordSearch: $("#record-search"),
  statusFilter: $("#status-filter"),
  recordCount: $("#record-count"),
  auditPanel: $("#audit-panel"),
  auditList: $("#audit-list"),
  loginGate: $("#login-gate"),
  loginForm: $("#login-form"),
  loginUsername: $("#login-username"),
  loginPassword: $("#login-password"),
  loginError: $("#login-error"),
  activeCheckpoint: $("#active-checkpoint"),
  checkpointDisplay: $("#checkpoint-display"),
  movement: $("#movement"),
  lane: $("#lane"),
  continuityPanel: $("#continuity-panel"),
  inspectionPanel: $("#inspection-panel"),
  dispositionPanel: $("#disposition-panel"),
  dispositionReason: $("#disposition-reason"),
  dispositionNotes: $("#disposition-notes"),
};

function showError(error) {
  const detail = error?.detail;
  const message = typeof detail === "string"
    ? detail
    : detail?.message || detail?.code || error?.message || "The hosted analysis did not complete. Retry once; if this persists, use the Render demo URL shown in the project README.";
  elements.alert.textContent = message.replaceAll("_", " ");
  elements.alert.hidden = false;
}

function clearError() {
  elements.alert.hidden = true;
  elements.alert.textContent = "";
}

async function request(path, options = {}) {
  const headers = new Headers(options.headers || {});
  const method = (options.method || "GET").toUpperCase();
  if (state.csrfToken && !["GET", "HEAD", "OPTIONS"].includes(method)) {
    headers.set("X-CSRF-Token", state.csrfToken);
  }
  const response = await fetch(path, { ...options, headers });
  if (!response.ok) {
    let payload;
    try { payload = await response.json(); } catch { payload = { message: response.statusText }; }
    if (response.status === 401 && path !== `${API}/auth/login`) showLogin();
    throw payload;
  }
  if (response.status === 204) return null;
  return response.json();
}

function showLogin() {
  state.auth = null;
  elements.loginGate.hidden = false;
  elements.loginPassword.value = "";
}

function renderOfficer(payload) {
  state.auth = payload;
  const officer = payload.officer;
  const checkpoints = payload.checkpoints || state.auth.checkpoints || [];
  state.auth.checkpoints = checkpoints;
  $("#officer-name").textContent = officer.display_name;
  $("#officer-role").textContent = `${officer.role} · ${officer.username}`;
  $("#delete-screening-button").hidden = officer.role !== "ADMIN";
  $("#history-section").hidden = officer.role !== "ADMIN";
  elements.auditPanel.hidden = officer.role !== "ADMIN";
  elements.activeCheckpoint.innerHTML = checkpoints.map((checkpoint) =>
    `<option value="${escapeHtml(checkpoint.code)}">${escapeHtml(checkpoint.name)}</option>`
  ).join("");
  elements.activeCheckpoint.value = officer.active_checkpoint.code;
  $("#active-post-location").textContent = officer.active_checkpoint.location;
  elements.checkpointDisplay.value = `${officer.active_checkpoint.name} · ${officer.active_checkpoint.code}`;
  elements.loginGate.hidden = true;
}

async function login(event) {
  event.preventDefault();
  const button = $("#login-button");
  button.disabled = true;
  elements.loginError.hidden = true;
  try {
    const payload = await request(`${API}/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        username: elements.loginUsername.value.trim(),
        password: elements.loginPassword.value,
      }),
    });
    state.csrfToken = payload.csrf_token;
    sessionStorage.setItem("drishti_csrf", state.csrfToken);
    renderOfficer(payload);
    elements.loginPassword.value = "";
    request(`${API}/warmup`, { method: "POST" }).catch(() => {});
    loadHistory();
  } catch (error) {
    elements.loginError.textContent = error?.detail?.code === "INVALID_OFFICER_CREDENTIALS"
      ? "Username or password was not accepted."
      : "Officer authentication is unavailable.";
    elements.loginError.hidden = false;
  } finally { button.disabled = false; }
}

async function restoreSession() {
  try {
    const payload = await request(`${API}/auth/me`);
    if (!state.csrfToken) {
      await request(`${API}/auth/logout`, { method: "POST" }).catch(() => {});
      showLogin();
      return;
    }
    renderOfficer(payload);
    request(`${API}/warmup`, { method: "POST" }).catch(() => {});
    loadHistory();
  } catch { showLogin(); }
}

async function changeCheckpoint() {
  const previous = state.auth?.officer?.active_checkpoint?.code;
  elements.activeCheckpoint.disabled = true;
  try {
    const payload = await request(`${API}/auth/active-checkpoint`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ checkpoint_code: elements.activeCheckpoint.value }),
    });
    renderOfficer({ ...state.auth, officer: payload.officer });
  } catch (error) {
    elements.activeCheckpoint.value = previous || "";
    showError(error);
  } finally { elements.activeCheckpoint.disabled = false; }
}

async function logout() {
  try { await request(`${API}/auth/logout`, { method: "POST" }); } catch {}
  state.csrfToken = null;
  sessionStorage.removeItem("drishti_csrf");
  showLogin();
}

function setStep(step) {
  document.querySelectorAll(".stepper li").forEach((item) => {
    const number = Number(item.dataset.step);
    item.classList.toggle("active", number === step);
    item.classList.toggle("complete", number < step);
    if (number < step) item.querySelector("span").textContent = "✓";
    else item.querySelector("span").textContent = String(number).padStart(2, "0");
  });
}

function primaryDocument(snapshot) {
  return snapshot?.document?.documents?.[0] || {};
}

function identityFrom(snapshot) {
  return primaryDocument(snapshot).identity || {};
}

function selectFile(file) {
  clearError();
  if (!file) return;
  if (!file.type.startsWith("image/")) {
    showError({ message: "Please choose an image file." });
    return;
  }
  state.file = file;
  elements.fileLabel.textContent = file.name;
  elements.analyze.disabled = false;
  elements.preview.src = URL.createObjectURL(file);
  elements.preview.hidden = false;
  elements.placeholder.hidden = true;
}

function validImage(file) {
  if (!file?.type?.startsWith("image/")) {
    showError({ message: "Please choose an image file." });
    return false;
  }
  return true;
}

function updateAnalyzeState() {
  const ready = state.documentKind === "aadhaar"
    ? Boolean(state.aadhaarFront && state.aadhaarBack)
    : Boolean(state.file);
  elements.analyze.disabled = !ready;
}

function selectAadhaarSide(side, file) {
  clearError();
  if (!validImage(file)) return;
  const isFront = side === "front";
  state[isFront ? "aadhaarFront" : "aadhaarBack"] = file;
  elements[isFront ? "aadhaarFrontLabel" : "aadhaarBackLabel"].textContent = file.name;
  const preview = elements[isFront ? "aadhaarFrontPreview" : "aadhaarBackPreview"];
  preview.src = URL.createObjectURL(file);
  elements.aadhaarPreviews.hidden = false;
  elements.preview.hidden = true;
  elements.placeholder.hidden = true;
  updateAnalyzeState();
}

function setDocumentKind(kind) {
  state.documentKind = kind;
  elements.aadhaarFields.hidden = kind !== "aadhaar";
  elements.travelField.hidden = kind === "aadhaar";
  elements.aadhaarPreviews.hidden = kind !== "aadhaar" || !(state.aadhaarFront || state.aadhaarBack);
  elements.preview.hidden = kind === "aadhaar" || !state.file;
  elements.placeholder.hidden = kind === "aadhaar"
    ? Boolean(state.aadhaarFront || state.aadhaarBack)
    : Boolean(state.file);
  elements.analyze.textContent = kind === "aadhaar" ? "Verify Aadhaar front + back" : "Analyze document";
  updateAnalyzeState();
}

async function analyzeDocument() {
  if (state.documentKind === "aadhaar" && !(state.aadhaarFront && state.aadhaarBack)) return;
  if (state.documentKind !== "aadhaar" && !state.file) return;
  clearError();
  elements.analyze.disabled = true;
  elements.analyze.textContent = "Analyzing…";
  const form = new FormData();
  const endpoint = state.documentKind === "aadhaar" ? "aadhaar-card" : "";
  if (state.documentKind === "aadhaar") {
    form.append("front", state.aadhaarFront);
    form.append("back", state.aadhaarBack);
  } else {
    form.append("document", state.file);
  }
  try {
    state.snapshot = await request(`${API}/screenings${endpoint ? `/${endpoint}` : ""}`, { method: "POST", body: form });
    state.sessionId = state.snapshot.session_id;
    renderIdentity();
    elements.documentPanel.hidden = true;
    elements.facePanel.hidden = false;
    setStep(2);
    elements.facePanel.scrollIntoView({ behavior: "smooth", block: "start" });
    loadHistory();
  } catch (error) {
    showError(error);
  } finally {
    elements.analyze.textContent = state.documentKind === "aadhaar" ? "Verify Aadhaar front + back" : "Analyze document";
    updateAnalyzeState();
  }
}

function renderIdentity() {
  const documentResult = primaryDocument(state.snapshot);
  const identity = identityFrom(state.snapshot);
  const capture = documentResult.forensics?.overall?.capture_quality;
  const authenticity = documentResult.authenticity;
  const portraitCheck = documentResult.cross_validation?.portrait;
  const fields = [
    ["Type", documentResult.document_type || state.snapshot?.document?.classification?.document_type],
    ["Name", identity.name || identity.full_name],
    ["Document", identity.document_number_masked || identity.document_number || identity.passport_number || identity.visa_number],
    ["Expires", identity.date_of_expiry || identity.valid_until],
    ["Trust", documentResult.issuer_verification?.signature_valid ? "UIDAI Secure QR signature valid" : null],
    ["Validation", Number.isFinite(documentResult.validation?.validation_score) ? `${documentResult.validation.validation_score}%` : null],
    ["Capture", capture?.status ? `${capture.status.replaceAll("_", " ")} · ${capture.score}/100` : null],
    ["Assurance", authenticity?.assurance_level?.replaceAll("_", " ")],
    ["Printed photo", portraitCheck?.status === "MISMATCH"
      ? "ALERT · differs from signed QR portrait"
      : portraitCheck?.status?.replaceAll("_", " ")],
  ].filter(([, value]) => value);
  elements.identity.innerHTML = fields.map(([label, value]) =>
    `<div><small>${escapeHtml(label)}</small><strong>${escapeHtml(value)}</strong></div>`
  ).join("") || "<p class='muted'>Document analyzed; no identity fields were confidently extracted.</p>";
}

async function startCameraCheck() {
  clearError();
  elements.cameraButton.disabled = true;
  elements.cameraButton.textContent = "Starting…";
  try {
    const start = await request(`${API}/screenings/${state.sessionId}/face/start`, { method: "POST" });
    state.stream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: "user", width: { ideal: 960 }, height: { ideal: 720 } },
      audio: false,
    });
    elements.video.srcObject = state.stream;
    await elements.video.play();
    updateFacePrompt(start.face);
    elements.cameraState.textContent = "Live check active";
    // A natural blink often lasts 100-400 ms. Send sequential frames often
    // enough for one closed-eye sample to reach the server; sendFrame's guard
    // prevents requests from overlapping on slower machines.
    state.captureTimer = window.setInterval(sendFrame, 140);
  } catch (error) {
    stopCamera();
    showError(error?.name === "NotAllowedError" ? { message: "Camera access was denied." } : error);
    elements.cameraButton.disabled = false;
    elements.cameraButton.textContent = "Try camera check again";
  }
}

function frameBlob() {
  const width = elements.video.videoWidth;
  const height = elements.video.videoHeight;
  if (!width || !height) return Promise.resolve(null);
  elements.canvas.width = width;
  elements.canvas.height = height;
  elements.canvas.getContext("2d").drawImage(elements.video, 0, 0, width, height);
  return new Promise((resolve) => elements.canvas.toBlob(resolve, "image/jpeg", .86));
}

async function sendFrame() {
  if (state.sendingFrame || !state.stream) return;
  state.sendingFrame = true;
  try {
    const blob = await frameBlob();
    if (!blob) return;
    const form = new FormData();
    form.append("frame", blob, "frame.jpg");
    const payload = await request(`${API}/screenings/${state.sessionId}/face/frame?mirrored=true`, {
      method: "POST",
      body: form,
    });
    updateFacePrompt(payload.face);
    if (Object.hasOwn(payload.face, "verification_passed")) {
      stopCamera();
      await finalize(false);
    }
  } catch (error) {
    stopCamera();
    showError(error);
    elements.cameraButton.disabled = false;
    elements.cameraButton.textContent = "Restart camera check";
  } finally {
    state.sendingFrame = false;
  }
}

function updateFacePrompt(face) {
  let instruction = face.instruction || face.state || "Keep your face centered in the guide.";
  if (face.state === "BLINK" && face.blink_ready === false) {
    instruction = "Keep your eyes open while the camera calibrates…";
  } else if (face.state === "BLINK" && face.blink_progress > 0) {
    instruction = "Blink seen — open your eyes";
  } else if (face.state === "TURN_HEAD" && face.turn_progress > 0) {
    instruction = `${instruction} — hold briefly (${face.turn_progress}/${face.turn_required})`;
  }
  elements.instruction.textContent = instruction;
  elements.cameraState.textContent = face.state ? face.state.replaceAll("_", " ") : "Processing";
  renderCaptureQuality(face);
}

function renderCaptureQuality(face) {
  const stability = face.capture_stability || {};
  const quality = face.quality || {};
  let progress = Number(stability.progress || 0);
  let label = "Finding face";
  let guidance = face.instruction || "Keep your full face inside the oval.";

  if (face.quality_passed === false) {
    label = "Adjustment needed";
    progress = 0;
  } else if (stability.stable) {
    label = `${stability.samples} stable frames secured`;
    progress = 1;
    guidance = "Multi-frame sample is stable. Complete the live-person challenge.";
  } else if (stability.required_samples) {
    label = `${stability.samples || 0}/${stability.required_samples} stable frames`;
  } else if (quality.passed) {
    label = "Quality passed";
    progress = Math.max(progress, .35);
  }

  elements.captureQuality.dataset.state = face.quality_passed === false ? "warning" : stability.stable ? "ready" : "active";
  elements.captureProgress.style.width = `${Math.max(0, Math.min(1, progress)) * 100}%`;
  elements.captureQualityLabel.textContent = label;
  elements.qualityGuidance.textContent = guidance;
}

function stopCamera() {
  if (state.captureTimer) window.clearInterval(state.captureTimer);
  state.captureTimer = null;
  state.stream?.getTracks().forEach((track) => track.stop());
  state.stream = null;
  elements.video.srcObject = null;
  elements.cameraState.textContent = "Camera off";
}

async function finalize(allowIncompleteFace) {
  clearError();
  elements.skipFace.disabled = true;
  elements.instruction.textContent = "Combining verification signals…";
  try {
    state.snapshot = await request(`${API}/screenings/${state.sessionId}/finalize`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        allow_incomplete_face: allowIncompleteFace,
        border_context: {
          movement: elements.movement.value,
          lane: elements.lane.value.trim() || null,
        },
      }),
    });
    renderDecision();
    loadAudit(state.sessionId);
    elements.facePanel.hidden = true;
    elements.decisionPanel.hidden = false;
    setStep(3);
    elements.decisionPanel.scrollIntoView({ behavior: "smooth", block: "start" });
    loadHistory();
  } catch (error) {
    showError(error);
    elements.skipFace.disabled = false;
  }
}

function renderDecision() {
  const result = state.snapshot.final || {};
  const badge = $("#decision-badge");
  badge.textContent = (result.decision || "UNKNOWN").replaceAll("_", " ");
  badge.className = `decision-badge ${(result.decision || "").toLowerCase().replaceAll("_", "-")}`;
  $("#new-screening-button").textContent = result.retry_required
    ? "Retake document photo"
    : "Start another screening";
  $("#risk-score").textContent = Number.isFinite(result.risk_score) ? `${result.risk_score}/100` : "—";
  $("#risk-level").textContent = result.risk_level || "—";
  $("#session-label").textContent = state.sessionId.slice(0, 8);
  renderSecondaryInspection(result.secondary_inspection);
  renderOfficerDisposition(result.officer_disposition);

  const evidence = result.evidence || (result.reasons || []).map((code) => ({ code, severity: "WARNING" }));
  const list = $("#evidence-list");
  list.innerHTML = "";
  if (!evidence.length) list.innerHTML = "<p class='muted'>No automated adverse signals were found. This is not proof of document authenticity.</p>";
  evidence.forEach((item) => {
    const node = $("#evidence-template").content.firstElementChild.cloneNode(true);
    node.classList.add((item.severity || "info").toLowerCase());
    node.querySelector("strong").textContent = (item.code || "CHECK").replaceAll("_", " ");
    node.querySelector("p").textContent = item.message || item.detail || item.severity || "Signal recorded";
    list.append(node);
  });

  const documentResult = primaryDocument(state.snapshot);
  const positiveEvidence = [];
  if (documentResult.mrz?.checksums?.valid) positiveEvidence.push({
    code: "MRZ CHECK DIGITS VALID",
    message: "All available machine-readable-zone check digits are internally consistent.",
  });
  if (documentResult.cross_validation?.overall_status === "CONSISTENT_WITH_OCR") positiveEvidence.push({
    code: "VISIBLE AND MACHINE DATA CONSISTENT",
    message: `${documentResult.cross_validation.confirmed_matches || 0} independently extracted field(s) agree.`,
  });
  if (documentResult.forensics?.overall?.capture_quality?.status === "PASS") positiveEvidence.push({
    code: "DOCUMENT CAPTURE QUALITY PASSED",
    message: "Resolution, focus, alignment, exposure, and contrast passed the capture gate.",
  });
  positiveEvidence.forEach((item) => {
    const node = $("#evidence-template").content.firstElementChild.cloneNode(true);
    node.classList.add("info", "trusted-evidence");
    node.querySelector("strong").textContent = item.code;
    node.querySelector("p").textContent = item.message;
    list.prepend(node);
  });

  const issuerVerification = documentResult.issuer_verification;
  if (issuerVerification?.signature_valid) {
    const node = $("#evidence-template").content.firstElementChild.cloneNode(true);
    node.classList.add("info", "trusted-evidence");
    node.querySelector("strong").textContent = "UIDAI DIGITAL SIGNATURE VALID";
    node.querySelector("p").textContent = "Signed demographics and portrait were verified using a trusted UIDAI certificate.";
    list.prepend(node);
  }

  const identity = identityFrom(state.snapshot);
  const correction = identity.ocr_corrections?.[0];
  const frontBackCheck = documentResult.cross_validation;
  const portraitCheck = frontBackCheck?.portrait;
  const frontBackStatus = frontBackCheck?.source !== "AADHAAR_FRONT_VS_UIDAI_SECURE_QR"
    ? null
    : frontBackCheck.valid
      ? "Visible front fields match signed QR"
      : frontBackCheck.mismatches
        ? "Clear identity mismatch detected"
        : "Front OCR inconclusive · recapture required";
  const details = [
    ["Name", identity.name || identity.full_name],
    ["Document number", identity.document_number_masked || identity.document_number || identity.passport_number || identity.visa_number],
    ["Nationality", identity.nationality],
    ["Date of birth", identity.date_of_birth],
    ["Expiry", identity.date_of_expiry || identity.valid_until],
    ["Issued", identity.date_of_issue || identity.valid_from],
    ["Place of birth", identity.place_of_birth],
    ["Place of issue", identity.place_of_issue],
    ["Issuing authority", identity.issuing_authority],
    ["Visa entries", identity.entries],
    ["Stay duration", identity.stay_duration_days ? `${identity.stay_duration_days} days` : null],
    ["Permit type", identity.permit_type],
    ["Vehicle classes", Array.isArray(identity.vehicle_classes) ? identity.vehicle_classes.join(", ") : identity.vehicle_classes],
    ["Validation profile", documentResult.validation?.validation_profile?.replaceAll("_", " ")],
    ["Capture quality", documentResult.forensics?.overall?.capture_quality?.status
      ? `${documentResult.forensics.overall.capture_quality.status.replaceAll("_", " ")} · ${documentResult.forensics.overall.capture_quality.score}/100`
      : null],
    ["Authenticity assurance", documentResult.authenticity?.assurance_level?.replaceAll("_", " ")],
    ["OCR correction", correction ? `${correction.from} → ${correction.to} (suggested; review required)` : null],
    ["Issuer verification", issuerVerification?.signature_valid
      ? issuerVerification.method === "AADHAAR_SECURE_QR"
        ? "UIDAI Secure QR signature valid"
        : "Issuer digital signature valid"
      : null],
    ["Front/back match", frontBackStatus],
    ["Front photo vs signed QR", portraitCheck?.status
      ? `${portraitCheck.status.replaceAll("_", " ")}${Number.isFinite(portraitCheck.similarity) ? ` · ${(portraitCheck.similarity * 100).toFixed(1)}% similarity` : ` · ${(portraitCheck.reason || "comparison unavailable").replaceAll("_", " ")}`}`
      : null],
  ].filter(([, value]) => value);
  $("#result-details").innerHTML = details.map(([label, value]) =>
    `<div><dt>${escapeHtml(label)}</dt><dd>${escapeHtml(value)}</dd></div>`
  ).join("") || "<p class='muted'>No document details available.</p>";
  renderContinuity(result.continuity, result.border_context);
}

function renderOfficerDisposition(disposition) {
  const status = $("#disposition-status");
  if (!disposition) {
    status.textContent = "Automated triage does not replace the authorized officer’s statutory decision.";
    elements.dispositionPanel.dataset.recorded = "false";
    return;
  }
  const timestamp = disposition.recorded_at
    ? new Date(disposition.recorded_at).toLocaleString()
    : "recorded time unavailable";
  status.textContent = `${disposition.decision.replaceAll("_", " ")} by ${disposition.officer_username} · ${disposition.reason_code.replaceAll("_", " ")} · ${timestamp}`;
  elements.dispositionPanel.dataset.recorded = "true";
  elements.dispositionReason.value = disposition.reason_code;
  elements.dispositionNotes.value = disposition.notes || "";
}

async function recordDisposition(decision) {
  if (!state.sessionId) return;
  const buttons = elements.dispositionPanel.querySelectorAll("[data-disposition]");
  buttons.forEach((button) => { button.disabled = true; });
  clearError();
  try {
    if (
      elements.dispositionReason.value === "AUTOMATED_CHECKS_CLEAR"
      && decision !== "CLEARED"
    ) {
      elements.dispositionReason.value = decision === "REFERRED"
        ? "INSUFFICIENT_EVIDENCE"
        : "SUPERVISOR_DIRECTION";
    }
    state.snapshot = await request(`${API}/screenings/${state.sessionId}/disposition`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        decision,
        reason_code: elements.dispositionReason.value,
        notes: elements.dispositionNotes.value.trim() || null,
      }),
    });
    renderOfficerDisposition(state.snapshot.final?.officer_disposition);
    loadAudit(state.sessionId);
    loadHistory();
  } catch (error) {
    showError(error);
  } finally {
    buttons.forEach((button) => { button.disabled = false; });
  }
}

function renderSecondaryInspection(inspection) {
  if (!inspection) {
    elements.inspectionPanel.hidden = true;
    return;
  }
  elements.inspectionPanel.hidden = false;
  elements.inspectionPanel.dataset.status = inspection.status || "ACTION_REQUIRED";
  $("#inspection-headline").textContent = inspection.headline || "Officer action available";
  $("#inspection-priority").textContent = `${inspection.priority || "ROUTINE"} PRIORITY`;
  $("#inspection-status").textContent = (inspection.status || "").replaceAll("_", " ");
  $("#inspection-summary").textContent = inspection.summary || "";

  const action = inspection.primary_action || {};
  $("#inspection-action").textContent = action.title || "Review screening evidence";
  $("#inspection-instruction").textContent = action.instruction || "Follow the authorized checkpoint procedure.";
  $("#inspection-actor").textContent = `Assigned to ${action.actor || "OFFICER"}`;
  $("#inspection-advisory").textContent = inspection.advisory || "";

  $("#decision-path").innerHTML = (inspection.decision_path || []).map((item) => `
    <article class="decision-path-item ${(item.status || "clear").toLowerCase()}">
      <span></span><div><strong>${escapeHtml(item.signal)}</strong><small>${escapeHtml(item.detail)}</small></div>
      <b>${escapeHtml(item.status)}</b>
    </article>`).join("");
}

function renderContinuity(continuity, borderContext) {
  if (!continuity) {
    elements.continuityPanel.hidden = true;
    return;
  }
  elements.continuityPanel.hidden = false;
  elements.continuityPanel.classList.toggle(
    "identity-conflict",
    continuity.status === "IDENTITY_CONFLICT",
  );
  $("#continuity-status").textContent = continuity.status.replaceAll("_", " ");
  $("#continuity-summary").textContent = continuity.summary;
  $("#crossing-count").textContent = `${continuity.prior_crossing_count || 0} prior crossing(s)`;

  const alerts = continuity.alerts || [];
  $("#continuity-alerts").innerHTML = alerts.map((alert) => {
    const fields = (alert.conflicting_fields || []).join(", ");
    const similarity = Number.isFinite(alert.strongest_face_similarity)
      ? ` · Face similarity ${(alert.strongest_face_similarity * 100).toFixed(1)}%`
      : "";
    return `<article class="continuity-alert ${(alert.severity || "info").toLowerCase()}">
      <strong>${escapeHtml(alert.code.replaceAll("_", " "))}</strong>
      <small>${escapeHtml(alert.message)}${fields ? ` Conflicts: ${escapeHtml(fields)}.` : ""}${similarity}</small>
    </article>`;
  }).join("");

  renderIdentityGraph(continuity.graph);

  const timeline = continuity.timeline || [];
  const current = borderContext ? [{
    checkpoint_code: borderContext.checkpoint_code,
    movement: borderContext.movement,
    lane: borderContext.lane,
    decision: state.snapshot.final?.decision,
    document_number: identityFrom(state.snapshot).document_number_masked
      || identityFrom(state.snapshot).document_number
      || identityFrom(state.snapshot).passport_number
      || identityFrom(state.snapshot).visa_number,
    created_at: state.snapshot.updated_at,
    current: true,
  }] : [];
  $("#crossing-timeline").innerHTML = [...current, ...timeline].map((event) => {
    const date = event.created_at ? new Date(event.created_at).toLocaleString() : "Current screening";
    const location = [event.checkpoint_code, event.lane].filter(Boolean).join(" · ");
    return `<article class="crossing-event">
      <span></span><div><strong>${event.current ? "Current check" : "Previous crossing"} · ${escapeHtml(event.movement || "—")}</strong>
      <small>${escapeHtml(location)} · Document ${escapeHtml(event.document_number || "—")} · ${escapeHtml(event.decision || "—")}</small></div>
      <time>${escapeHtml(date)}</time>
    </article>`;
  }).join("");
}

function renderIdentityGraph(graph) {
  const svg = $("#identity-graph");
  state.continuityGraph = graph;
  if (!graph?.nodes?.length) {
    svg.replaceChildren();
    $("#graph-detail").textContent = "No linked identity relationships were found.";
    return;
  }

  const draw = () => {
    const namespace = "http://www.w3.org/2000/svg";
    const width = Math.max(290, Math.round(svg.getBoundingClientRect().width));
    const height = width < 500 ? 285 : 390;
    const horizontal = width >= 500;
    const types = ["biometric", "profile", "document", "checkpoint"];
    const groups = Object.fromEntries(types.map((type) => [
      type,
      graph.nodes.filter((node) => node.type === type),
    ]));
    const positions = new Map();
    const margin = horizontal ? 52 : 38;

    types.forEach((type, layerIndex) => {
      const layerNodes = groups[type];
      layerNodes.forEach((node, nodeIndex) => {
        const layerPosition = types.length === 1
          ? .5
          : layerIndex / (types.length - 1);
        const peerPosition = (nodeIndex + 1) / (layerNodes.length + 1);
        positions.set(node.id, horizontal
          ? {
              x: margin + layerPosition * (width - margin * 2),
              y: 45 + peerPosition * (height - 90),
            }
          : {
              x: margin + peerPosition * (width - margin * 2),
              y: 38 + layerPosition * (height - 76),
            });
      });
    });

    svg.replaceChildren();
    svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
    const edgesGroup = document.createElementNS(namespace, "g");
    const nodesGroup = document.createElementNS(namespace, "g");

    graph.edges.forEach((edge) => {
      const source = positions.get(edge.source);
      const target = positions.get(edge.target);
      if (!source || !target) return;
      const line = document.createElementNS(namespace, "line");
      line.setAttribute("x1", source.x);
      line.setAttribute("y1", source.y);
      line.setAttribute("x2", target.x);
      line.setAttribute("y2", target.y);
      line.setAttribute("class", `graph-edge ${edge.state === "conflict" ? "conflict" : ""}`);
      edgesGroup.append(line);
      if (horizontal && edge.label) {
        const label = document.createElementNS(namespace, "text");
        label.setAttribute("x", (source.x + target.x) / 2);
        label.setAttribute("y", (source.y + target.y) / 2 - 6);
        label.setAttribute("text-anchor", "middle");
        label.setAttribute("class", "graph-edge-label");
        label.textContent = edge.label;
        edgesGroup.append(label);
      }
    });

    graph.nodes.forEach((node) => {
      const position = positions.get(node.id);
      const group = document.createElementNS(namespace, "g");
      group.setAttribute("class", `graph-node ${node.type} ${node.state || ""}`);
      group.setAttribute("transform", `translate(${position.x} ${position.y})`);
      group.setAttribute("tabindex", "0");
      group.setAttribute("role", "button");
      group.setAttribute("aria-label", `${node.type}: ${node.label}. ${node.subtitle || ""}`);

      const circle = document.createElementNS(namespace, "circle");
      circle.setAttribute("r", node.type === "biometric" ? "21" : "17");
      group.append(circle);

      const label = document.createElementNS(namespace, "text");
      label.setAttribute("text-anchor", "middle");
      label.setAttribute("y", horizontal ? "37" : "34");
      const shortLabel = node.label.length > 18 ? `${node.label.slice(0, 17)}…` : node.label;
      label.textContent = shortLabel;
      group.append(label);

      if (horizontal && node.subtitle) {
        const subtitle = document.createElementNS(namespace, "text");
        subtitle.setAttribute("text-anchor", "middle");
        subtitle.setAttribute("y", "49");
        subtitle.setAttribute("class", "node-subtitle");
        subtitle.textContent = node.subtitle.length > 21
          ? `${node.subtitle.slice(0, 20)}…`
          : node.subtitle;
        group.append(subtitle);
      }

      const inspect = () => {
        const stateLabel = node.state === "conflict" ? "Conflict detected" : "Relationship verified";
        $("#graph-detail").textContent = `${node.type.toUpperCase()} · ${node.label} · ${node.subtitle || "No additional attributes"} · ${stateLabel}`;
      };
      group.addEventListener("click", inspect);
      group.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          inspect();
        }
      });
      nodesGroup.append(group);
    });

    svg.append(edgesGroup, nodesGroup);
  };

  graphResizeObserver?.disconnect();
  graphResizeObserver = new ResizeObserver(draw);
  graphResizeObserver.observe(svg);
  draw();
}

function resetScreening() {
  stopCamera();
  state.sessionId = null;
  state.file = null;
  state.aadhaarFront = null;
  state.aadhaarBack = null;
  state.snapshot = null;
  state.continuityGraph = null;
  graphResizeObserver?.disconnect();
  elements.input.value = "";
  elements.aadhaarFrontInput.value = "";
  elements.aadhaarBackInput.value = "";
  elements.aadhaarFrontLabel.textContent = "Choose front image";
  elements.aadhaarBackLabel.textContent = "Choose back image with QR";
  elements.aadhaarFrontPreview.removeAttribute("src");
  elements.aadhaarBackPreview.removeAttribute("src");
  elements.aadhaarPreviews.hidden = true;
  elements.fileLabel.textContent = "Choose passport, visa, ID, licence, or permit";
  elements.preview.removeAttribute("src");
  elements.preview.hidden = true;
  elements.placeholder.hidden = false;
  setDocumentKind(state.documentKind);
  elements.skipFace.disabled = false;
  elements.cameraButton.disabled = false;
  elements.cameraButton.textContent = "Start camera check";
  elements.captureQuality.dataset.state = "";
  elements.captureProgress.style.width = "0%";
  elements.captureQualityLabel.textContent = "Waiting for camera";
  elements.qualityGuidance.textContent = "Drishti will guide distance, lighting, stillness and pose in real time.";
  elements.documentPanel.hidden = false;
  elements.facePanel.hidden = true;
  elements.decisionPanel.hidden = true;
  elements.continuityPanel.hidden = true;
  elements.inspectionPanel.hidden = true;
  elements.dispositionPanel.dataset.recorded = "false";
  elements.dispositionReason.value = "AUTOMATED_CHECKS_CLEAR";
  elements.dispositionNotes.value = "";
  elements.auditPanel.open = false;
  elements.auditList.innerHTML = "<p class='muted'>Open to load recorded events.</p>";
  setStep(1);
  clearError();
  window.scrollTo({ top: 0, behavior: "smooth" });
}

async function deleteCurrentScreening() {
  if (!state.sessionId) return;
  const button = $("#delete-screening-button");
  button.disabled = true;
  try {
    await request(`${API}/screenings/${state.sessionId}`, { method: "DELETE" });
    resetScreening();
    loadHistory();
  } catch (error) {
    showError(error);
    button.disabled = false;
  }
}

async function loadHistory() {
  try {
    const payload = await request(`${API}/screenings?limit=200`);
    state.records = payload.screenings;
    renderHistory();
  } catch (error) {
    elements.history.innerHTML = "<p class='muted'>Screening records are unavailable.</p>";
    elements.recordCount.textContent = "";
  }
}

function renderHistory() {
  const query = elements.recordSearch.value.trim().toLowerCase();
  const status = elements.statusFilter.value;
  const records = state.records.filter((item) => {
    const identity = identityFrom(item);
    const searchable = [
      item.session_id,
      item.status,
      identity.name,
      identity.full_name,
      identity.document_number,
      identity.passport_number,
      identity.visa_number,
    ].filter(Boolean).join(" ").toLowerCase();
    return (!query || searchable.includes(query)) && (!status || item.status === status);
  });

  elements.recordCount.textContent = `${records.length} of ${state.records.length} records`;
  if (!records.length) {
    elements.history.innerHTML = `<p class="muted">${state.records.length ? "No records match these filters." : "No screenings yet."}</p>`;
    return;
  }

  elements.history.innerHTML = records.map((item) => {
      const identity = identityFrom(item);
      const title = identity.name || identity.full_name || "Unidentified document";
      const date = new Date(item.updated_at).toLocaleString();
      const result = item.final || {};
      const documentType = primaryDocument(item).document_type || item.document?.classification?.document_type || "document";
      const risk = Number.isFinite(result.risk_score) ? ` · Risk ${result.risk_score}/100` : "";
      return `<article class="history-item"><div><strong>${escapeHtml(title)}</strong><small>${escapeHtml(documentType.toUpperCase())} · ${escapeHtml(date)} · ${escapeHtml(item.session_id.slice(0, 8))}${escapeHtml(risk)}</small></div><span class="status-chip status-${escapeHtml(item.status.toLowerCase())}">${escapeHtml(item.status.replaceAll("_", " "))}</span><button class="text-button" data-session="${escapeHtml(item.session_id)}">View record</button></article>`;
    }).join("");
}

async function loadAudit(sessionId) {
  elements.auditList.innerHTML = "<p class='muted'>Loading audit trail…</p>";
  try {
    const payload = await request(`${API}/screenings/${sessionId}/audit`);
    if (!payload.events.length) {
      elements.auditList.innerHTML = "<p class='muted'>No audit events were recorded.</p>";
      return;
    }
    elements.auditList.innerHTML = payload.events.map((event) => {
      const timestamp = new Date(event.created_at).toLocaleString();
      const detail = Object.entries(event.data || {}).map(([key, value]) =>
        `${key.replaceAll("_", " ")}: ${typeof value === "object" ? JSON.stringify(value) : value}`
      ).join(" · ");
      return `<article class="audit-item"><span></span><div><strong>${escapeHtml(event.event_type.replaceAll("_", " "))}</strong><small>${escapeHtml(timestamp)}</small>${detail ? `<p>${escapeHtml(detail)}</p>` : ""}</div></article>`;
    }).join("");
  } catch (error) {
    elements.auditList.innerHTML = "<p class='muted'>Audit trail is unavailable.</p>";
  }
}

async function openHistory(sessionId) {
  clearError();
  try {
    const snapshot = await request(`${API}/screenings/${sessionId}`);
    if (!snapshot.final) throw { message: "This screening has not been finalized." };
    stopCamera();
    state.sessionId = sessionId;
    state.snapshot = snapshot;
    renderDecision();
    loadAudit(sessionId);
    elements.documentPanel.hidden = true;
    elements.facePanel.hidden = true;
    elements.decisionPanel.hidden = false;
    setStep(3);
    elements.decisionPanel.scrollIntoView({ behavior: "smooth" });
  } catch (error) { showError(error); }
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>'"]/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;",
  })[character]);
}

elements.input.addEventListener("change", () => selectFile(elements.input.files[0]));
elements.aadhaarFrontInput.addEventListener("change", () => selectAadhaarSide("front", elements.aadhaarFrontInput.files[0]));
elements.aadhaarBackInput.addEventListener("change", () => selectAadhaarSide("back", elements.aadhaarBackInput.files[0]));
document.querySelectorAll('input[name="document-kind"]').forEach((input) => {
  input.addEventListener("change", () => setDocumentKind(input.value));
});
elements.drop.addEventListener("dragover", (event) => { event.preventDefault(); elements.drop.classList.add("dragging"); });
elements.drop.addEventListener("dragleave", () => elements.drop.classList.remove("dragging"));
elements.drop.addEventListener("drop", (event) => {
  event.preventDefault();
  elements.drop.classList.remove("dragging");
  selectFile(event.dataTransfer.files[0]);
});
elements.analyze.addEventListener("click", analyzeDocument);
elements.cameraButton.addEventListener("click", startCameraCheck);
elements.skipFace.addEventListener("click", () => finalize(true));
$("#new-screening-button").addEventListener("click", resetScreening);
$("#delete-screening-button").addEventListener("click", deleteCurrentScreening);
$("#refresh-button").addEventListener("click", loadHistory);
elements.recordSearch.addEventListener("input", renderHistory);
elements.statusFilter.addEventListener("change", renderHistory);
elements.dispositionPanel.addEventListener("click", (event) => {
  const decision = event.target.dataset?.disposition;
  if (decision) recordDisposition(decision);
});
elements.loginForm.addEventListener("submit", login);
elements.activeCheckpoint.addEventListener("change", changeCheckpoint);
$("#logout-button").addEventListener("click", logout);
elements.history.addEventListener("click", (event) => {
  const sessionId = event.target.dataset?.session;
  if (sessionId) openHistory(sessionId);
});
window.addEventListener("beforeunload", stopCamera);

request("/health").then(() => {
  $("#health-dot").classList.add("online");
  $("#health-label").textContent = "Service online";
}).catch(() => {
  $("#health-dot").classList.add("offline");
  $("#health-label").textContent = "Service unavailable";
});
setDocumentKind("aadhaar");
restoreSession();
