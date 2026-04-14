const state = {
  jobId: null,
  pollTimer: null,
  lastLogCount: 0,
};

const form = document.getElementById("job-form");
const fieldset = document.getElementById("job-fields");
const jobStatus = document.getElementById("job-status");
const jobMeta = document.getElementById("job-meta");
const apiStatus = document.getElementById("api-status");
const logOutput = document.getElementById("log-output");
const summaryList = document.getElementById("summary-list");
const artifactList = document.getElementById("artifact-list");
const downloadLink = document.getElementById("download-link");
const clearLogButton = document.getElementById("clear-log");

function buildJobFormData() {
  const formData = new FormData();
  const fileInput = document.getElementById("file");
  const file = fileInput.files?.[0];

  if (!file) {
    throw new Error("Please choose a PDF file.");
  }

  formData.append("file", file);
  formData.append("page", document.getElementById("page").value || "1");
  formData.append(
    "wrapper_groups",
    document.getElementById("wrapper_groups").value || "2",
  );
  formData.append("padding", document.getElementById("padding").value || "0");
  formData.append("dpi", document.getElementById("dpi").value || "1200");
  formData.append("precision", document.getElementById("precision").value || "6");
  formData.append(
    "object_streams",
    document.getElementById("object_streams").value || "disable",
  );
  formData.append(
    "acrobat_fix",
    document.getElementById("acrobat_fix").checked ? "true" : "false",
  );
  formData.append(
    "linearize",
    document.getElementById("linearize").checked ? "true" : "false",
  );
  formData.append(
    "keep_temp",
    document.getElementById("keep_temp").checked ? "true" : "false",
  );

  return formData;
}

function setBadge(element, label, tone) {
  element.textContent = label;
  element.className = `badge ${tone}`;
}

function resetDownloadLink() {
  downloadLink.href = "#";
  downloadLink.classList.add("is-disabled");
  downloadLink.setAttribute("aria-disabled", "true");
}

function setDownloadLink(url) {
  downloadLink.href = url;
  downloadLink.classList.remove("is-disabled");
  downloadLink.setAttribute("aria-disabled", "false");
}

function renderList(container, items) {
  container.innerHTML = "";
  for (const item of items) {
    const entry = document.createElement("li");
    if (typeof item === "string") {
      entry.textContent = item;
    } else {
      const link = document.createElement("a");
      link.href = item.url;
      link.textContent = item.label;
      link.target = "_blank";
      link.rel = "noreferrer";
      entry.appendChild(link);
    }
    container.appendChild(entry);
  }
}

function appendLogs(logs) {
  logOutput.textContent = logs.join("\n");
  logOutput.scrollTop = logOutput.scrollHeight;
}

function stopPolling() {
  if (state.pollTimer !== null) {
    window.clearTimeout(state.pollTimer);
    state.pollTimer = null;
  }
}

async function checkApiHealth() {
  try {
    const response = await fetch("/api/health");
    if (!response.ok) {
      throw new Error("Backend unavailable");
    }
    setBadge(apiStatus, "Backend Ready", "badge-succeeded");
  } catch (_error) {
    setBadge(apiStatus, "Backend Down", "badge-failed");
  }
}

function startPolling(jobId) {
  stopPolling();
  state.jobId = jobId;

  const poll = async () => {
    try {
      const response = await fetch(`/api/jobs/${jobId}`);
      if (!response.ok) {
        throw new Error("Could not fetch job status.");
      }

      const payload = await response.json();
      appendLogs(payload.logs);
      state.lastLogCount = payload.logs.length;

      const stamp = new Date(payload.updated_at).toLocaleString();
      jobMeta.textContent = `${payload.filename} • updated ${stamp}`;

      if (payload.status === "queued" || payload.status === "running") {
        setBadge(jobStatus, payload.status, "badge-running");
        fieldset.disabled = true;
        resetDownloadLink();
        state.pollTimer = window.setTimeout(poll, 1000);
        return;
      }

      fieldset.disabled = false;
      if (payload.status === "succeeded") {
        setBadge(jobStatus, "Succeeded", "badge-succeeded");
        setDownloadLink(payload.result.download_url);
        renderList(summaryList, payload.result.summary_lines);

        const artifactEntries = Object.entries(payload.result.artifacts || {}).map(
          ([name, artifact]) => ({
            url: artifact.url,
            label: `${name}: ${artifact.filename}`,
          }),
        );
        renderList(
          artifactList,
          artifactEntries.length > 0
            ? artifactEntries
            : ["No intermediate files were saved for this run."],
        );
        return;
      }

      setBadge(jobStatus, "Failed", "badge-failed");
      resetDownloadLink();
      renderList(summaryList, [payload.error || "The job failed."]);
      renderList(artifactList, ["No artifacts available."]);
    } catch (error) {
      setBadge(jobStatus, "Connection Error", "badge-failed");
      jobMeta.textContent = error.message;
      fieldset.disabled = false;
    }
  };

  poll();
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  stopPolling();
  resetDownloadLink();
  renderList(summaryList, ["Submitting job..."]);
  renderList(artifactList, ["Intermediate files will appear here when enabled."]);
  logOutput.textContent = "Creating job...";
  setBadge(jobStatus, "Submitting", "badge-running");
  jobMeta.textContent = "Uploading file and sending settings to the backend.";

  try {
    const formData = buildJobFormData();
    fieldset.disabled = true;
    const response = await fetch("/api/jobs", {
      method: "POST",
      body: formData,
    });

    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      throw new Error(payload.detail || "The job request was rejected.");
    }

    const payload = await response.json();
    logOutput.textContent = "Job created.\nWaiting for worker to start...";
    startPolling(payload.job_id);
  } catch (error) {
    fieldset.disabled = false;
    setBadge(jobStatus, "Failed", "badge-failed");
    jobMeta.textContent = error.message;
    renderList(summaryList, [error.message]);
    renderList(artifactList, ["No artifacts available."]);
    logOutput.textContent = `Request failed.\n${error.message}`;
  }
});

clearLogButton.addEventListener("click", () => {
  logOutput.textContent = "Waiting for a job.";
});

checkApiHealth();
resetDownloadLink();
