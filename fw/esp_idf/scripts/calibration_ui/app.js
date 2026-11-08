"use strict";
const $ = (id) => document.getElementById(id);
const keyNames = ["A", "N", "I", "—", "H", "O", "R", "SHIFT", "T", "E", "S", "BACKSPACE", "SPACE", "SPACE", "SPACE", "ENTER"];
const grid = $("grid");
for (let i = 0; i < 16; i++) {
  const cell = document.createElement("div"); cell.className = "cell";
  const key = document.createElement("span"); key.className = "key" + (keyNames[i].length > 1 ? " command" : ""); key.textContent = keyNames[i];
  const label = document.createElement("span"); label.className = "region"; label.textContent = `R${Math.floor(i / 4) + 1}C${i % 4 + 1}`;
  cell.append(key, label); grid.append(cell);
}
let latest = null, busy = false, networkFailed = false, lastCue = "", audioContext = null, lastTouch = false;
function enableSound() {
  if (!$("sound").checked) return;
  try {
    const Audio = window.AudioContext || window.webkitAudioContext;
    audioContext = audioContext || new Audio();
    audioContext.resume().catch(() => { $("audio-status").textContent = "Sound unavailable; follow the visual cues."; });
  } catch { $("audio-status").textContent = "Sound unavailable; follow the visual cues."; }
}
function tone(contact) {
  if (!$("sound").checked || !audioContext || audioContext.state !== "running") return;
  try {
    const oscillator = audioContext.createOscillator(), gain = audioContext.createGain(), now = audioContext.currentTime;
    oscillator.frequency.value = contact ? 1000 : 350;
    gain.gain.setValueAtTime(0, now); gain.gain.linearRampToValueAtTime(0.08, now + 0.01);
    gain.gain.exponentialRampToValueAtTime(0.001, now + 0.14);
    oscillator.connect(gain); gain.connect(audioContext.destination);
    oscillator.start(now); oscillator.stop(now + 0.15);
    oscillator.onended = () => { oscillator.disconnect(); gain.disconnect(); };
  } catch { $("audio-status").textContent = "Sound unavailable; follow the visual cues."; }
}
function showError(message) { $("error").hidden = !message; $("error").textContent = message || ""; }
async function command(action, payload = {}) {
  if (busy) return;
  busy = true;
  try {
    const response = await fetch(`/api/${action}`, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(payload)});
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "Request failed");
    showError("");
    if (action === "start" || action === "resume") document.querySelector(".exercise").scrollIntoView({behavior: "smooth", block: "start"});
  } catch (error) { showError(error.message); }
  finally { busy = false; }
}
function startPayload() {
  return {block: $("block").value, seed: Number($("seed").value),
    pre_idle: Number($("pre-idle").value), contact: Number($("contact").value), post_idle: Number($("post-idle").value),
    environment: {cover: $("cover").value, grip: $("grip").value, finger: $("finger").value, notes: $("notes").value}};
}
$("start").addEventListener("click", () => { if ($("setup-form").reportValidity()) { enableSound(); command("start", startPayload()); } });
for (const action of ["pause", "resume", "skip", "mistake", "stop"]) $(action).addEventListener("click", () => { if (action === "resume") enableSound(); command(action); });
$("sound").addEventListener("change", enableSound);
$("setup-form").addEventListener("submit", (event) => event.preventDefault());
document.addEventListener("visibilitychange", () => {
  if (document.hidden && latest && ["running", "waiting_marker"].includes(latest.state)) {
    fetch("/api/pause", {method: "POST", headers: {"Content-Type": "application/json"}, body: "{}", keepalive: true}).catch(() => {});
  }
});
$("block").addEventListener("change", () => {
  $("start").textContent = $("block").value === "pilot" ? "Start pilot" : "Start positions";
  $("block-help").textContent = $("block").value === "pilot"
    ? "Pilot: hands away, four corners, center, then two slow traversals."
    : "Positions: three shuffled training passes, then a separate validation pass. Lift fully between targets.";
});
function mask(value) { return Number.isInteger(value) ? "0x" + value.toString(16).padStart(4, "0") : "—"; }
function setSvg(element, name, value) { element.setAttribute(name, String(value)); }
function render(state) {
  latest = state;
  const capture = state.capture || {}, sample = capture.latest_sample || {}, quality = capture.quality || {};
  const trial = state.trial, target = trial?.target;
  const isContact = state.state === "running" && state.phase === "contact" && trial?.intended_action !== "hands_away";
  if (isContact !== lastTouch) tone(isContact);
  lastTouch = isContact;
  $("synthetic").hidden = !state.synthetic;
  $("connection").textContent = capture.running ? (!capture.ready ? "Synchronizing device…" : state.can_start || state.can_resume || state.state === "running" || state.state === "waiting_marker" ? "Device streaming" : "Waiting for valid data") : "Capture stopped";
  $("connection").classList.toggle("ready", Boolean(capture.running && capture.ready && capture.latest_metadata && capture.samples && capture.sample_age_s < 2.5));
  $("start").disabled = !state.can_start;
  $("pause").disabled = !["running", "waiting_marker"].includes(state.state);
  $("resume").disabled = !state.can_resume;
  $("skip").disabled = !["running", "waiting_marker", "paused"].includes(state.state);
  $("mistake").disabled = !state.previous_trial || state.state === "stopped";
  $("stop").disabled = ["stopped", "stopping"].includes(state.state);
  for (const input of $("setup-form").elements) input.disabled = !["idle", "complete"].includes(state.state);
  $("progress").textContent = state.total ? `${state.block.toUpperCase()} · ${Math.min(state.index + 1, state.total)} / ${state.total}${trial ? " · " + trial.split.toUpperCase() + " · PASS " + trial.pass_index : ""}` : "READY WHEN YOU ARE";
  $("progress-bar").max = state.total || 1; $("progress-bar").value = state.index;
  let cue = "Waiting for device", instruction = "Connecting and checking the data stream…";
  if (state.state === "idle" && state.can_start) { cue = "Ready to start"; instruction = "Enter your setup above, then click Start pilot."; }
  else if (state.state === "running") {
    if (state.phase === "pre_idle") { cue = "Get ready"; instruction = "Finger off. The next target is highlighted."; }
    else if (state.phase === "post_idle") { cue = "RELEASE"; instruction = "Lift your finger completely."; }
    else { cue = trial.intended_action === "hands_away" ? "Hands away" : trial.intended_action === "continuous_traversal" ? "TRACE" : "TOUCH & HOLD"; instruction = trial.prompt; }
  } else if (state.state === "waiting_marker") { cue = "Finger off"; instruction = "Preparing the next cue…"; }
  else if (state.state === "paused") { cue = "PAUSED"; instruction = "Keep your finger off. Resume when ready."; }
  else if (state.state === "complete") { cue = "Block complete"; instruction = state.block === "pilot" ? "The pilot is saved. Wait for the capture check before spending time on the position block." : "All scheduled targets are saved. Stop recording when finished."; }
  else if (state.state === "stopping") { cue = "Saving…"; instruction = "Finishing the recording."; }
  else if (state.state === "stopped") { cue = "Recording saved"; instruction = "You can close this page. Original recordings and labels are preserved."; }
  $("cue").textContent = cue;
  // Update the live region only when the cue changes; countdown updates stay quiet.
  const cueId = `${trial?.trial_id}:${state.phase}:${state.state}:${cue}`;
  if (cueId !== lastCue) { $("instruction").textContent = instruction; lastCue = cueId; }
  $("countdown").textContent = state.state === "running" ? Math.max(0, state.remaining_s).toFixed(1) : "—";
  $("target-label").textContent = target ? `Target: ${target.id}` : "";
  $("reason").textContent = state.reason || "";
  $("cue").parentElement.classList.toggle("contact", isContact);
  Array.from(grid.children).forEach((cell, i) => {
    const match = target?.row === Math.floor(i / 4) + 1 && target?.col === i % 4 + 1;
    cell.classList.toggle("target", Boolean(match)); cell.classList.toggle("touch", Boolean(match && isContact));
  });
  const special = target && target.row === null;
  $("point").style.display = special ? "block" : "none";
  $("path").style.display = special && target.end_x_mm !== undefined ? "block" : "none";
  if (special) {
    setSvg($("point"), "cx", target.x_mm); setSvg($("point"), "cy", target.y_mm);
    if (target.end_x_mm !== undefined) { setSvg($("path"), "x1", target.x_mm); setSvg($("path"), "y1", target.y_mm); setSvg($("path"), "x2", target.end_x_mm); setSvg($("path"), "y2", target.end_y_mm); }
  }
  $("samples").textContent = (capture.samples || 0).toLocaleString();
  $("rate").textContent = quality.measured_hz ? `${quality.measured_hz.toFixed(1)} Hz` : "—";
  $("drops").textContent = quality.device_dropped_scans || 0;
  $("gaps").textContent = `${quality.packet_gaps || 0} / ${quality.scan_gaps || 0}`;
  $("masks").textContent = `Channel masks · registered ${mask(sample.registered_mask)} · raw ${mask(sample.raw_valid_mask)} · smooth ${mask(sample.smooth_valid_mask)} · benchmark ${mask(sample.benchmark_valid_mask)} · latest sample ${capture.sample_age_s?.toFixed(1) || "0.0"}s ago`;
  const metadata = capture.latest_metadata;
  $("metadata").textContent = metadata ? `Metadata received · boot ${metadata.boot_id ?? "unknown"} · ${metadata.firmware || metadata.project || metadata.project_name || "SWP1 acquisition"}${metadata.app_version ? " · " + metadata.app_version : ""}${metadata.idf_version ? " · IDF " + metadata.idf_version : ""}` : "Firmware metadata: waiting. Legacy text logs do not enable collection.";
  const issues = [...(quality.issues || []), ...(capture.errors || [])];
  $("issues").textContent = issues.length ? [...new Set(issues)].join("\n") : "No capture integrity issues reported.";
  $("issues").classList.toggle("warning", issues.length > 0);
  $("session-dir").textContent = state.session_dir;
  if (state.error) showError(state.error);
}
async function poll() {
  try {
    const response = await fetch("/api/status", {cache: "no-store"});
    if (!response.ok) throw new Error("Collector unavailable");
    const state = await response.json();
    if (networkFailed) { showError(""); networkFailed = false; }
    document.body.classList.remove("disconnected"); render(state);
  } catch (error) {
    if (lastTouch) { tone(false); lastTouch = false; }
    networkFailed = true; document.body.classList.add("disconnected");
    $("cue").textContent = "Connection lost · finger off"; $("countdown").textContent = "—";
    for (const id of ["start", "pause", "resume", "skip", "mistake", "stop"]) $(id).disabled = true;
    showError("The cue display is disconnected. Lift your finger. The server pauses prompts if this page stops polling; raw capture continues. Reconnect to resume.");
  } finally { setTimeout(poll, 125); }
}
poll();
