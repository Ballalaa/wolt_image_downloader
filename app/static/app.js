(() => {
  "use strict";

  // ---------- Theme ----------
  const THEME_KEY = "wolt-image-tool-theme";
  const themeToggle = document.getElementById("theme-toggle");

  function applyTheme(theme) {
    document.documentElement.setAttribute("data-theme", theme);
  }

  function initTheme() {
    const saved = localStorage.getItem(THEME_KEY);
    if (saved) {
      applyTheme(saved);
      return;
    }
    const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
    applyTheme(prefersDark ? "dark" : "light");
  }

  themeToggle.addEventListener("click", () => {
    const current = document.documentElement.getAttribute("data-theme") || "light";
    const next = current === "dark" ? "light" : "dark";
    applyTheme(next);
    localStorage.setItem(THEME_KEY, next);
  });

  initTheme();

  // ---------- Elements ----------
  const dropzone = document.getElementById("dropzone");
  const fileInput = document.getElementById("file-input");
  const fileChip = document.getElementById("file-chip");
  const fileChipName = document.getElementById("file-chip-name");
  const fileChipChange = document.getElementById("file-chip-change");
  const previewBox = document.getElementById("preview-box");
  const previewCount = document.getElementById("preview-count");
  const previewTableBody = document.querySelector("#preview-table tbody");
  const uploadError = document.getElementById("upload-error");

  const samplePreviewSelect = document.getElementById("sample-preview-select");
  const samplePreviewMenu = document.getElementById("sample-preview-menu");
  const samplePreviewButton = document.getElementById("sample-preview-button");
  const samplePreview = document.getElementById("sample-preview");
  const samplePreviewImage = document.getElementById("sample-preview-image");
  const samplePreviewSku = document.getElementById("sample-preview-sku");
  const samplePreviewOriginalLink = document.getElementById("sample-preview-original-link");
  const samplePreviewError = document.getElementById("sample-preview-error");

  const cardUpload = document.getElementById("card-upload");
  const cardRun = document.getElementById("card-run");

  const prefixToggle = document.getElementById("prefix-toggle");
  const prefixInput = document.getElementById("prefix-input");
  const sizeToggle = document.getElementById("size-toggle");
  const dimensionRow = document.getElementById("dimension-row");
  const defaultSizeNote = document.getElementById("default-size-note");
  const widthInput = document.getElementById("width-input");
  const heightInput = document.getElementById("height-input");
  const paddingInput = document.getElementById("padding-input");
  const paddingValue = document.getElementById("padding-value");
  const startButton = document.getElementById("start-button");

  const progressFill = document.getElementById("progress-fill");
  const progressText = document.getElementById("progress-text");
  const statSuccess = document.getElementById("stat-success");
  const statFailed = document.getElementById("stat-failed");
  const resultBlock = document.getElementById("result-block");
  const resultSummary = document.getElementById("result-summary");
  const downloadButton = document.getElementById("download-button");
  const resetButton = document.getElementById("reset-button");
  const failuresBox = document.getElementById("failures-box");
  const failuresCount = document.getElementById("failures-count");
  const failuresBody = document.getElementById("failures-body");
  const runError = document.getElementById("run-error");
  const statElapsed = document.getElementById("stat-elapsed");
  const statEta = document.getElementById("stat-eta");
  const cancelButton = document.getElementById("cancel-button");

  const state = {
    file: null,
    rowCount: 0,
    previewRows: [],
    skuList: [],
    skuToIndex: new Map(),
    prefixEnabled: false,
    sizeMode: "default",
  };

  const COMBOBOX_MAX_RESULTS = 50;
  let comboboxActiveIndex = -1;

  function resolveSkuIndex(query) {
    const trimmed = query.trim();
    if (!trimmed) return null;
    if (state.skuToIndex.has(trimmed)) return state.skuToIndex.get(trimmed);
    const lower = trimmed.toLowerCase();
    const index = state.previewRows.findIndex((row) => row.sku.toLowerCase().includes(lower));
    return index === -1 ? null : index;
  }

  function comboboxOptions(query) {
    const trimmed = query.trim().toLowerCase();
    const matches = trimmed
      ? state.skuList.filter((sku) => sku.toLowerCase().includes(trimmed))
      : state.skuList;
    return matches.slice(0, COMBOBOX_MAX_RESULTS);
  }

  function renderComboboxMenu(query) {
    const options = comboboxOptions(query);
    comboboxActiveIndex = options.length ? 0 : -1;
    samplePreviewMenu.innerHTML = "";

    if (!options.length) {
      const empty = document.createElement("div");
      empty.className = "combobox-empty";
      empty.textContent = "No matching SKUs";
      samplePreviewMenu.appendChild(empty);
    } else {
      options.forEach((sku, index) => {
        const option = document.createElement("div");
        option.className = "combobox-option" + (index === 0 ? " is-active" : "");
        option.textContent = sku;
        option.addEventListener("mousedown", (event) => {
          event.preventDefault();
          samplePreviewSelect.value = sku;
          closeComboboxMenu();
        });
        samplePreviewMenu.appendChild(option);
      });
    }
    samplePreviewMenu.classList.remove("hidden");
    samplePreviewSelect.setAttribute("aria-expanded", "true");
  }

  function closeComboboxMenu() {
    samplePreviewMenu.classList.add("hidden");
    samplePreviewSelect.setAttribute("aria-expanded", "false");
    comboboxActiveIndex = -1;
  }

  function setComboboxActive(delta) {
    const options = Array.from(samplePreviewMenu.querySelectorAll(".combobox-option"));
    if (!options.length) return;
    options[comboboxActiveIndex]?.classList.remove("is-active");
    comboboxActiveIndex = (comboboxActiveIndex + delta + options.length) % options.length;
    options[comboboxActiveIndex].classList.add("is-active");
    options[comboboxActiveIndex].scrollIntoView({ block: "nearest" });
  }

  samplePreviewSelect.addEventListener("input", () => renderComboboxMenu(samplePreviewSelect.value));
  samplePreviewSelect.addEventListener("focus", () => renderComboboxMenu(samplePreviewSelect.value));
  samplePreviewSelect.addEventListener("blur", () => closeComboboxMenu());
  samplePreviewSelect.addEventListener("keydown", (event) => {
    if (samplePreviewMenu.classList.contains("hidden")) return;
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setComboboxActive(1);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setComboboxActive(-1);
    } else if (event.key === "Enter") {
      const active = samplePreviewMenu.querySelector(".combobox-option.is-active");
      if (active) {
        event.preventDefault();
        samplePreviewSelect.value = active.textContent;
        closeComboboxMenu();
      }
    } else if (event.key === "Escape") {
      closeComboboxMenu();
    }
  });

  function formatDuration(seconds) {
    if (seconds == null || !isFinite(seconds) || seconds < 0) return null;
    const total = Math.round(seconds);
    const m = Math.floor(total / 60);
    const s = total % 60;
    return `${m}:${String(s).padStart(2, "0")}`;
  }

  function renderPreviewRows(rows) {
    previewTableBody.innerHTML = "";
    rows.forEach((row) => {
      const tr = document.createElement("tr");
      const skuTd = document.createElement("td");
      skuTd.textContent = row.sku;
      const urlTd = document.createElement("td");
      urlTd.textContent = row.url;
      tr.append(skuTd, urlTd);
      previewTableBody.appendChild(tr);
    });
  }

  // ---------- Upload ----------
  function showUploadError(message) {
    uploadError.textContent = message;
    uploadError.classList.remove("hidden");
  }
  function clearUploadError() {
    uploadError.classList.add("hidden");
  }

  function isExcelFile(file) {
    return /\.(xlsx|xls)$/i.test(file.name);
  }

  function resetSamplePreview() {
    samplePreviewSelect.value = "";
    closeComboboxMenu();
    samplePreviewSelect.disabled = true;
    samplePreviewButton.disabled = true;
    samplePreviewButton.textContent = "Preview image";
    samplePreview.classList.add("hidden");
    samplePreviewError.classList.add("hidden");
  }

  async function handleFile(file) {
    clearUploadError();
    previewBox.classList.add("hidden");
    startButton.disabled = true;
    resetSamplePreview();

    if (!isExcelFile(file)) {
      showUploadError("Please choose an .xlsx or .xls file.");
      return;
    }

    state.file = file;
    dropzone.classList.add("hidden");
    fileChip.classList.remove("hidden");
    fileChipName.textContent = `${file.name} (${(file.size / 1024).toFixed(0)} KB)`;

    const formData = new FormData();
    formData.append("file", file);

    try {
      const response = await fetch("/api/preview", { method: "POST", body: formData });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Could not read that file.");

      state.rowCount = data.row_count;
      state.previewRows = data.rows;
      previewCount.textContent = `${data.row_count.toLocaleString()} row(s) detected`;
      renderPreviewRows(data.rows);
      previewBox.classList.remove("hidden");
      startButton.disabled = false;

      state.skuToIndex = new Map();
      state.skuList = [];
      data.rows.forEach((row, index) => {
        if (!state.skuToIndex.has(row.sku)) {
          state.skuToIndex.set(row.sku, index);
          state.skuList.push(row.sku);
        }
      });
      samplePreviewSelect.disabled = false;
      samplePreviewButton.disabled = false;
    } catch (error) {
      showUploadError(error.message);
    }
  }

  dropzone.addEventListener("dragover", (event) => {
    event.preventDefault();
    dropzone.classList.add("is-dragover");
  });
  dropzone.addEventListener("dragleave", () => dropzone.classList.remove("is-dragover"));
  dropzone.addEventListener("drop", (event) => {
    event.preventDefault();
    dropzone.classList.remove("is-dragover");
    const file = event.dataTransfer.files[0];
    if (file) handleFile(file);
  });

  fileInput.addEventListener("change", () => {
    const file = fileInput.files[0];
    if (file) handleFile(file);
  });

  fileChipChange.addEventListener("click", () => {
    fileInput.value = "";
    fileChip.classList.add("hidden");
    dropzone.classList.remove("hidden");
    previewBox.classList.add("hidden");
    startButton.disabled = true;
    resetSamplePreview();
    fileInput.click();
  });

  // ---------- Sample preview ----------
  samplePreviewButton.addEventListener("click", async () => {
    if (!state.file) return;

    const query = samplePreviewSelect.value.trim();
    const rowIndex = resolveSkuIndex(samplePreviewSelect.value);
    if (rowIndex === null) {
      samplePreviewError.textContent = query
        ? `No SKU matches "${query}".`
        : "Search or pick a SKU above before previewing.";
      samplePreviewError.classList.remove("hidden");
      return;
    }

    samplePreviewButton.disabled = true;
    samplePreviewButton.textContent = "Loading…";
    samplePreviewError.classList.add("hidden");

    const formData = new FormData();
    formData.append("file", state.file);
    formData.append("row_index", String(rowIndex));
    formData.append("size_mode", state.sizeMode);
    formData.append("width", widthInput.value);
    formData.append("height", heightInput.value);
    formData.append("padding", paddingInput.value);

    try {
      const response = await fetch("/api/preview-image", { method: "POST", body: formData });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Could not build a sample preview.");

      samplePreviewImage.src = `data:image/jpeg;base64,${data.processed_base64}`;
      samplePreviewSku.textContent = data.sku;
      samplePreviewSelect.value = data.sku;
      samplePreviewOriginalLink.href = data.url;
      samplePreview.classList.remove("hidden");
    } catch (error) {
      samplePreviewError.textContent = error.message;
      samplePreviewError.classList.remove("hidden");
    } finally {
      samplePreviewButton.disabled = false;
      samplePreviewButton.textContent = "Refresh preview";
    }
  });

  // ---------- Settings: prefix ----------
  prefixToggle.addEventListener("click", (event) => {
    const button = event.target.closest(".segmented-option");
    if (!button) return;
    Array.from(prefixToggle.children).forEach((el) => el.classList.remove("is-active"));
    button.classList.add("is-active");
    state.prefixEnabled = button.dataset.value === "yes";
    prefixInput.classList.toggle("hidden", !state.prefixEnabled);
  });

  // ---------- Settings: size ----------
  sizeToggle.addEventListener("click", (event) => {
    const button = event.target.closest(".segmented-option");
    if (!button) return;
    Array.from(sizeToggle.children).forEach((el) => el.classList.remove("is-active"));
    button.classList.add("is-active");
    state.sizeMode = button.dataset.value;
    dimensionRow.classList.toggle("is-visible", state.sizeMode === "custom");
    defaultSizeNote.classList.toggle("hidden", state.sizeMode === "custom");
  });

  paddingInput.addEventListener("input", () => {
    paddingValue.textContent = paddingInput.value;
  });

  // ---------- Start job ----------
  let pollTimer = null;
  let activeJobId = null;

  startButton.addEventListener("click", async () => {
    if (!state.file) return;
    startButton.disabled = true;

    const formData = new FormData();
    formData.append("file", state.file);
    formData.append("prefix_enabled", state.prefixEnabled ? "true" : "false");
    formData.append("prefix", state.prefixEnabled ? prefixInput.value.trim() : "");
    formData.append("size_mode", state.sizeMode);
    formData.append("width", widthInput.value);
    formData.append("height", heightInput.value);
    formData.append("padding", paddingInput.value);

    try {
      const response = await fetch("/api/jobs", { method: "POST", body: formData });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Could not start the job.");

      activeJobId = data.job_id;
      cardUpload.classList.add("hidden");
      cardRun.classList.remove("hidden");
      resultBlock.classList.add("hidden");
      runError.classList.add("hidden");
      cancelButton.disabled = false;
      cancelButton.textContent = "Stop processing";
      cancelButton.classList.remove("hidden");
      pollJob(data.job_id);
    } catch (error) {
      startButton.disabled = false;
      showUploadError(error.message);
    }
  });

  cancelButton.addEventListener("click", async () => {
    if (!activeJobId) return;
    cancelButton.disabled = true;
    cancelButton.textContent = "Stopping…";
    try {
      await fetch(`/api/jobs/${activeJobId}/cancel`, { method: "POST" });
    } catch {
      // Polling will still reflect the real state; nothing else to do here.
    }
  });

  downloadButton.addEventListener("click", async () => {
    if (!activeJobId) return;
    downloadButton.disabled = true;
    downloadButton.textContent = "Preparing…";
    try {
      const response = await fetch(`/api/jobs/${activeJobId}/download`);
      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        throw new Error(body.detail || "Could not download the ZIP.");
      }
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = "wolt-images.zip";
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
      runError.classList.add("hidden");
    } catch (error) {
      runError.textContent = error.message;
      runError.classList.remove("hidden");
    } finally {
      downloadButton.disabled = false;
      downloadButton.textContent = "Download ZIP";
    }
  });

  function pollJob(jobId) {
    pollTimer = setInterval(async () => {
      try {
        const response = await fetch(`/api/jobs/${jobId}`);
        const job = await response.json();
        if (!response.ok) throw new Error(job.detail || "Lost track of the job.");
        renderJob(jobId, job);
        if (job.status === "done" || job.status === "error" || job.status === "cancelled") {
          clearInterval(pollTimer);
          cancelButton.classList.add("hidden");
        }
      } catch (error) {
        clearInterval(pollTimer);
        runError.textContent = error.message;
        runError.classList.remove("hidden");
      }
    }, 400);
  }

  function renderJob(jobId, job) {
    const percent = job.total ? Math.round((job.processed / job.total) * 100) : 0;
    progressFill.style.width = `${percent}%`;
    progressText.textContent = `${job.processed.toLocaleString()} / ${job.total.toLocaleString()} processed`;
    statSuccess.textContent = `${job.succeeded.toLocaleString()} succeeded`;
    statFailed.textContent = `${job.failed.toLocaleString()} failed`;

    const elapsedText = formatDuration(job.elapsed_seconds);
    statElapsed.textContent = elapsedText ? `Elapsed ${elapsedText}` : "Elapsed 0:00";
    const etaText = formatDuration(job.eta_seconds);
    statEta.textContent =
      job.status === "running"
        ? etaText
          ? `~${etaText} remaining`
          : "Estimating time left…"
        : "";

    if (job.status === "error") {
      runError.textContent = job.error_message || "Something went wrong while processing.";
      runError.classList.remove("hidden");
      return;
    }

    if (job.status === "done" || job.status === "cancelled") {
      resultBlock.classList.remove("hidden");
      const skipped = job.total - job.processed;
      const label = job.status === "cancelled" ? "Stopped" : "Done";
      resultSummary.textContent =
        `${label}: ${job.succeeded.toLocaleString()} succeeded, ${job.failed.toLocaleString()} failed` +
        (skipped > 0 ? `, ${skipped.toLocaleString()} skipped` : "") +
        ` out of ${job.total.toLocaleString()}` +
        (elapsedText ? ` in ${elapsedText}.` : ".");
      downloadButton.disabled = false;
      downloadButton.textContent = "Download ZIP";

      if (job.failed > 0) {
        failuresCount.textContent = job.failed.toLocaleString();
        failuresBody.innerHTML = "";
        job.failures.forEach((failure) => {
          const tr = document.createElement("tr");
          const skuTd = document.createElement("td");
          skuTd.textContent = failure.sku;
          const reasonTd = document.createElement("td");
          reasonTd.textContent = failure.reason;
          const linkTd = document.createElement("td");
          const link = document.createElement("a");
          link.href = failure.url;
          link.target = "_blank";
          link.rel = "noopener noreferrer";
          link.textContent = "Open link";
          linkTd.appendChild(link);
          tr.append(skuTd, reasonTd, linkTd);
          failuresBody.appendChild(tr);
        });
        failuresBox.classList.remove("hidden");
        failuresBox.open = true;
      } else {
        failuresBox.classList.add("hidden");
      }
    }
  }

  resetButton.addEventListener("click", () => window.location.reload());
})();
