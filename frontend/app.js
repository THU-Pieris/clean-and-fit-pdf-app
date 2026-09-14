const $ = (id) => document.getElementById(id);
const state = {
  file: null,
  jobId: null,
  pollTimer: null,
  busy: false,
  logs: [],
  clearedLogs: 0,
};
const form = $("job-form");
const fieldset = $("job-fields");
const fileInput = $("file");
const downloadLink = $("download-link");
const MAX_FILE_BYTES = 64 * 1024 * 1024 - 64 * 1024; // Leave room for multipart fields in Nginx's 64 MB request limit.

function formatBytes(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function setBadge(element, label, tone) {
  element.textContent = label;
  element.className = `badge badge-${tone}`;
}

function setStep(current) {
  for (const step of ["upload", "configure", "download"]) {
    if (step === current)
      $(`step-${step}`).setAttribute("aria-current", "step");
    else $(`step-${step}`).removeAttribute("aria-current");
  }
}

function setBusy(busy) {
  state.busy = busy;
  fieldset.disabled = busy;
  $("submit-button").disabled = busy || !state.file;
  $("submit-label").textContent = busy ? "Processing PDF…" : "Clean & fit PDF";
}

function showFileError(message) {
  $("file-error").textContent = message;
  $("file-error").hidden = !message;
  fileInput.setAttribute("aria-invalid", String(Boolean(message)));
}

function selectFile(file) {
  if (state.busy || !file) return;
  if (!file.name.toLowerCase().endsWith(".pdf")) {
    showFileError("Choose a PDF file (.pdf) to continue.");
    fileInput.value = "";
    return;
  }
  if (!file.size || file.size > MAX_FILE_BYTES) {
    showFileError(
      !file.size
        ? "This file is empty. Choose a PDF with content."
        : "This PDF is too large. Choose a file smaller than 64 MB.",
    );
    fileInput.value = "";
    return;
  }
  state.file = file;
  showFileError("");
  $("file-name").textContent = file.name;
  $("file-size").textContent = `${formatBytes(file.size)} · PDF document`;
  $("selected-file").hidden = false;
  $("drop-zone").hidden = true;
  $("submit-button").disabled = false;
  setStep("configure");
  if ($("output-panel").dataset.state === "idle") {
    $("job-meta").textContent =
      "Your document is ready. Adjust the settings, then select Clean & fit PDF.";
    setBadge($("job-status"), "Ready to process", "muted");
  }
}

function resetDownload() {
  downloadLink.removeAttribute("href");
  downloadLink.removeAttribute("download");
  downloadLink.classList.add("is-disabled");
  downloadLink.setAttribute("aria-disabled", "true");
  downloadLink.tabIndex = -1;
  $("result-details").hidden = true;
}

function renderStatus(status, message) {
  const content = {
    submitting: [
      "Uploading",
      "running",
      "PREPARING YOUR DOCUMENT",
      "Sending your PDF…",
      "upload",
    ],
    queued: [
      "Queued",
      "running",
      "YOUR DOCUMENT IS IN LINE",
      "Ready for processing.",
      "crop",
    ],
    running: [
      "Processing",
      "running",
      "CLEANING. MEASURING. FITTING.",
      "Finding the perfect fit…",
      "crop",
    ],
    succeeded: [
      "Complete",
      "succeeded",
      "ALL DONE",
      "Your PDF, neatly fitted.",
      "check",
    ],
    failed: [
      "Failed",
      "failed",
      "SOMETHING NEEDS ATTENTION",
      "We couldn’t finish this PDF.",
      "alert",
    ],
    "connection-error": [
      "Connection lost",
      "failed",
      "LET’S RECONNECT",
      "Your job may still be running.",
      "alert",
    ],
  }[status];
  $("output-panel").dataset.state = status;
  setBadge($("job-status"), content[0], content[1]);
  $("result-kicker").textContent = content[2];
  $("result-title").textContent = content[3];
  $("result-icon").setAttribute("href", `#icon-${content[4]}`);
  $("job-meta").textContent = message;
  $("empty-note").hidden = true;
  $("retry-status").hidden = status !== "connection-error";
}

function renderList(container, items) {
  container.replaceChildren();
  for (const item of items) {
    const entry = document.createElement("li");
    if (typeof item === "string") entry.textContent = item;
    else {
      const link = document.createElement("a");
      link.href = item.url;
      link.textContent = item.label;
      link.download = item.filename;
      entry.appendChild(link);
    }
    container.appendChild(entry);
  }
}

function renderLogs() {
  const logs = state.logs.slice(state.clearedLogs);
  const output = $("log-output");
  const nearBottom =
    output.scrollTop + output.clientHeight >= output.scrollHeight - 30;
  output.textContent = logs.join("\n") || "No new activity.";
  if (nearBottom) output.scrollTop = output.scrollHeight;
  $("log-count").textContent =
    `${logs.length} ${logs.length === 1 ? "entry" : "entries"}`;
}

function renderResult(result) {
  $("output-filename").textContent = result.output_filename;
  $("result-dimensions").textContent =
    `${Number(result.size_pt.width).toFixed(2)} × ${Number(result.size_pt.height).toFixed(2)} pt`;
  $("result-size").textContent = formatBytes(result.output_bytes);
  $("result-page").textContent = result.page;
  downloadLink.href = result.download_url;
  downloadLink.download = result.output_filename;
  downloadLink.classList.remove("is-disabled");
  downloadLink.setAttribute("aria-disabled", "false");
  downloadLink.removeAttribute("tabindex");
  $("result-details").hidden = false;
  renderList($("summary-list"), result.summary_lines || []);
  $("summary-section").hidden = !result.summary_lines?.length;
  const artifacts = Object.entries(result.artifacts || {}).map(
    ([name, artifact]) => ({
      url: artifact.url,
      filename: artifact.filename,
      label: `${name.replaceAll("_", " ")} — ${artifact.filename}`,
    }),
  );
  renderList($("artifact-list"), artifacts);
  $("artifact-section").hidden = !artifacts.length;
  setStep("download");
}

function stopPolling() {
  if (state.pollTimer !== null) window.clearTimeout(state.pollTimer);
  state.pollTimer = null;
}

// Bound network waits so a dropped connection always offers a way to recover.
async function request(url, options = {}, timeout = 30000) {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), timeout);
  try {
    const response = await fetch(url, {
      ...options,
      signal: controller.signal,
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      const detail = payload.detail;
      const message =
        typeof detail === "string"
          ? detail
          : Array.isArray(detail)
            ? detail
                .map((item) => `${item.loc?.at(-1) || "Input"}: ${item.msg}`)
                .join("; ")
            : response.status === 413
              ? "This PDF is too large for the server."
              : `The server returned an error (${response.status}). Please try again.`;
      throw new Error(message);
    }
    return payload;
  } catch (error) {
    if (error.name === "AbortError")
      throw new Error(
        "The server took too long to respond. Check your connection and try again.",
      );
    if (error instanceof TypeError)
      throw new Error(
        "Cannot reach the server. Check your connection and try again.",
      );
    throw error;
  } finally {
    window.clearTimeout(timer);
  }
}

async function checkApiHealth() {
  try {
    await request("/api/health", {}, 10000);
    setBadge($("api-status"), "Service online", "succeeded");
  } catch (_error) {
    setBadge($("api-status"), "Service unavailable", "failed");
  }
}

async function pollJob(jobId) {
  stopPolling();
  try {
    const payload = await request(`/api/jobs/${jobId}`);
    if (state.jobId !== jobId) return;
    setBadge($("api-status"), "Service online", "succeeded");
    state.logs = payload.logs || [];
    renderLogs();
    if (payload.status === "queued" || payload.status === "running") {
      renderStatus(
        payload.status,
        payload.status === "queued"
          ? `${payload.filename} is waiting for the worker.`
          : `Processing ${payload.filename}. Larger pages and higher DPI can take longer.`,
      );
      state.pollTimer = window.setTimeout(() => pollJob(jobId), 1000);
      return;
    }
    setBusy(false);
    if (payload.status === "succeeded" && payload.result) {
      renderStatus("succeeded", "The fitted document is ready to download.");
      renderResult(payload.result);
    } else {
      renderStatus(
        "failed",
        payload.error ||
          "Check your PDF and processing settings, then try again.",
      );
      $("processing-details").open = true;
    }
  } catch (error) {
    if (state.jobId !== jobId) return;
    setBusy(false);
    renderStatus("connection-error", error.message);
    setBadge($("api-status"), "Connection issue", "failed");
  }
}

function buildJobFormData() {
  const formData = new FormData();
  formData.append("file", state.file);
  for (const name of [
    "page",
    "wrapper_groups",
    "padding",
    "dpi",
    "precision",
    "object_streams",
  ]) {
    formData.append(name, $(name).value);
  }
  for (const name of ["acrobat_fix", "linearize", "keep_temp"]) {
    formData.append(name, String($(name).checked));
  }
  return formData;
}

fileInput.addEventListener("change", () => selectFile(fileInput.files?.[0]));
$("remove-file").addEventListener("click", () => {
  if (state.busy) return;
  state.file = null;
  fileInput.value = "";
  $("selected-file").hidden = true;
  $("drop-zone").hidden = false;
  $("submit-button").disabled = true;
  showFileError("");
  setStep("upload");
  if ($("output-panel").dataset.state === "idle") {
    setBadge($("job-status"), "Awaiting PDF", "muted");
    $("job-meta").textContent =
      "Add a PDF and choose your settings. Your fitted document will appear here.";
  }
  fileInput.focus();
});

// Prevent dropped files from navigating the browser away from an active job.
for (const eventName of ["dragover", "drop"]) {
  window.addEventListener(eventName, (event) => {
    if (Array.from(event.dataTransfer?.types || []).includes("Files"))
      event.preventDefault();
  });
}
$("drop-zone").addEventListener("dragover", (event) => {
  event.preventDefault();
  if (!state.busy) $("drop-zone").classList.add("is-dragging");
});
$("drop-zone").addEventListener("dragleave", (event) => {
  if (!$("drop-zone").contains(event.relatedTarget))
    $("drop-zone").classList.remove("is-dragging");
});
$("drop-zone").addEventListener("drop", (event) => {
  event.preventDefault();
  $("drop-zone").classList.remove("is-dragging");
  if (state.busy) return;
  if (event.dataTransfer?.files.length !== 1) {
    showFileError("Choose one PDF at a time.");
    return;
  }
  selectFile(event.dataTransfer.files[0]);
});

// Reveal advanced inputs before the browser focuses an invalid value.
form.addEventListener(
  "invalid",
  (event) => {
    if ($("advanced-settings").contains(event.target))
      $("advanced-settings").open = true;
  },
  true,
);

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (state.busy) return;
  if (!state.file) {
    showFileError("Choose a PDF file to continue.");
    fileInput.focus();
    return;
  }
  if (!form.reportValidity()) return;
  stopPolling();
  state.jobId = null;
  state.logs = [];
  state.clearedLogs = 0;
  resetDownload();
  $("summary-section").hidden = true;
  $("artifact-section").hidden = true;
  $("processing-details").open = false;
  $("log-output").textContent = "Uploading document…";
  $("log-count").textContent = "Starting";
  renderStatus(
    "submitting",
    `Uploading ${state.file.name}. Keep this page open while your document is processed.`,
  );
  setStep("configure");
  const data = buildJobFormData();
  setBusy(true);
  try {
    const payload = await request(
      "/api/jobs",
      { method: "POST", body: data },
      120000,
    );
    if (!payload.job_id)
      throw new Error("The server did not return a job ID. Please try again.");
    state.jobId = payload.job_id;
    pollJob(payload.job_id);
  } catch (error) {
    setBusy(false);
    renderStatus("failed", error.message);
    state.logs = [`Upload failed: ${error.message}`];
    renderLogs();
    checkApiHealth();
  }
});

$("retry-status").addEventListener("click", () => {
  if (!state.jobId || state.busy) return;
  setBusy(true);
  renderStatus("running", "Reconnecting to your existing job…");
  pollJob(state.jobId);
});
$("clear-log").addEventListener("click", () => {
  state.clearedLogs = state.logs.length;
  renderLogs();
});
window.addEventListener("online", checkApiHealth);
checkApiHealth();
