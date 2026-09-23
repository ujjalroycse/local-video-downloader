document.addEventListener("DOMContentLoaded", () => {
    // Main Elements
    const analyzeBtn = document.getElementById("analyze-btn");
    const downloadBtn = document.getElementById("download-btn");
    const videoUrlInput = document.getElementById("video-url");
    const errorBox = document.getElementById("error-message");
    const analysisResult = document.getElementById("analysis-result");
    const progressSection = document.getElementById("progress-section");
    const successSection = document.getElementById("success-section");

    // Video Information
    const thumbImg = document.getElementById("video-thumbnail");
    const videoTitle = document.getElementById("video-title");
    const videoDuration = document.getElementById("video-duration");
    const qualityOptions = document.getElementById("quality-options");
    const qualityContainer = document.getElementById("quality-container");

    // Audio Language
    const languageOptions = document.getElementById("language-options");
    const languageContainer = document.getElementById("language-container");

    // Download Progress
    const progressBarFill = document.getElementById("progress-bar-fill");
    const progressPercent = document.getElementById("progress-percent");
    const progressStatus = document.getElementById("progress-status");
    const progressSpeed = document.getElementById("progress-speed");
    const progressEta = document.getElementById("progress-eta");

    // State
    let currentVideoUrl = "";
    let progressInterval = null;
    let downloadInProgress = false;
    let cancellingDownload = false;
    let lifecycleConnection = null;
    let processingStarted = false;

    // Processing Progress UI
    let processingProgressContainer = document.getElementById("processing-progress-container");
    let processingProgressFill = document.getElementById("processing-progress-fill");
    let processingProgressPercent = document.getElementById("processing-progress-percent");
    let processingProgressStatus = document.getElementById("processing-progress-status");

    // Create Processing Progress UI
    if (!processingProgressContainer && progressSection) {
        processingProgressContainer = document.createElement("div");
        processingProgressContainer.id = "processing-progress-container";
        processingProgressContainer.style.marginTop = "24px";

        const processingLabel = document.createElement("div");
        processingLabel.style.display = "flex";
        processingLabel.style.justifyContent = "space-between";
        processingLabel.style.alignItems = "center";
        processingLabel.style.marginBottom = "8px";

        processingProgressStatus = document.createElement("span");
        processingProgressStatus.id = "processing-progress-status";
        processingProgressStatus.textContent = "Processing...";

        processingProgressPercent = document.createElement("span");
        processingProgressPercent.id = "processing-progress-percent";
        processingProgressPercent.textContent = "0%";

        processingLabel.appendChild(processingProgressStatus);
        processingLabel.appendChild(processingProgressPercent);

        const processingProgressTrack = document.createElement("div");
        processingProgressTrack.style.width = "100%";
        processingProgressTrack.style.height = "8px";
        processingProgressTrack.style.borderRadius = "999px";
        processingProgressTrack.style.overflow = "hidden";
        processingProgressTrack.style.background = "rgba(255, 255, 255, 0.08)";

        processingProgressFill = document.createElement("div");
        processingProgressFill.id = "processing-progress-fill";
        processingProgressFill.style.width = "0%";
        processingProgressFill.style.height = "100%";
        processingProgressFill.style.minWidth = "0";
        processingProgressFill.style.borderRadius = "999px";
        processingProgressFill.style.background = "#3b82f6";
        processingProgressFill.style.transition = "width 0.25s ease";
        processingProgressFill.style.display = "block";

        processingProgressTrack.appendChild(processingProgressFill);
        processingProgressContainer.appendChild(processingLabel);
        processingProgressContainer.appendChild(processingProgressTrack);
        progressSection.appendChild(processingProgressContainer);
    }

    // Create Cancel Button
    let cancelDownloadBtn = document.getElementById("cancel-download-btn");

    if (!cancelDownloadBtn && progressSection) {
        cancelDownloadBtn = document.createElement("button");
        cancelDownloadBtn.id = "cancel-download-btn";
        cancelDownloadBtn.type = "button";
        cancelDownloadBtn.className = "secondary-btn cancel-download-btn";
        cancelDownloadBtn.textContent = "Cancel Download";
        progressSection.appendChild(cancelDownloadBtn);
    }

    // Persistent Browser Lifecycle Connection
    function connectLifecycle() {
        try {
            lifecycleConnection = new EventSource("/api/lifecycle");

            lifecycleConnection.onopen = () => {
                console.debug("Browser lifecycle connection established.");
            };

            lifecycleConnection.addEventListener("connected", () => {
                console.debug("Downloader lifecycle connected.");
            });

            lifecycleConnection.onerror = () => {
                console.debug("Lifecycle connection interrupted. Browser will reconnect automatically.");
            };
        } catch (error) {
            console.error("Could not create lifecycle connection:", error);
        }
    }

    connectLifecycle();

    // Browser Before Unload
    window.addEventListener("beforeunload", (event) => {
        if (downloadInProgress) {
            event.preventDefault();
            event.returnValue = "";
            return "";
        }
    });

    // Helpers
    function show(element) {
        if (element) {
            element.classList.remove("hidden");
        }
    }

    function hide(element) {
        if (element) {
            element.classList.add("hidden");
        }
    }

    function showError(message) {
        if (!errorBox) return;
        errorBox.textContent = message;
        show(errorBox);
    }

    function clearError() {
        hide(errorBox);
    }

    function formatTime(seconds) {
        if (!seconds) return "00:00";

        const h = Math.floor(seconds / 3600);
        const m = Math.floor((seconds % 3600) / 60);
        const s = Math.floor(seconds % 60);

        return [h, m, s]
            .filter((value, index) => value > 0 || index > 0)
            .map(value => value.toString().padStart(2, "0"))
            .join(":");
    }

    // Reset Progress UI
    function resetProgressUI() {
        processingStarted = false;

        // Download
        if (progressBarFill) {
            progressBarFill.style.width = "0%";
        }

        if (progressPercent) {
            progressPercent.textContent = "0%";
        }

        if (progressStatus) {
            progressStatus.textContent = "Starting...";
        }

        if (progressSpeed) {
            progressSpeed.textContent = "Speed: 0 MB/s";
        }

        if (progressEta) {
            progressEta.textContent = "Remaining: --";
        }

        // Processing
        if (processingProgressFill) {
            processingProgressFill.style.width = "0%";
        }

        if (processingProgressPercent) {
            processingProgressPercent.textContent = "0%";
        }

        if (processingProgressStatus) {
            processingProgressStatus.textContent = "Processing...";
        }

        if (processingProgressContainer) {
            hide(processingProgressContainer);
        }
    }

    // Start Processing Progress
    function startProcessingProgress() {
        if (!processingProgressContainer) return;

        if (!processingStarted) {
            processingStarted = true;
            updateProcessingProgress(0);
        }

        show(processingProgressContainer);

        if (processingProgressStatus) {
            processingProgressStatus.textContent = "Processing...";
        }
    }

    // Update Download Progress
    function updateDownloadProgress(percentage) {
        const numericPercentage = Number(percentage);

        const safePercentage = Math.min(
            100,
            Math.max(
                0,
                Number.isFinite(numericPercentage) ? numericPercentage : 0
            )
        );

        if (progressBarFill) {
            progressBarFill.style.width = `${safePercentage}%`;
        }

        if (progressPercent) {
            progressPercent.textContent = `${Math.round(safePercentage)}%`;
        }
    }

    // Update Processing Progress
    function updateProcessingProgress(percentage) {
        const numericPercentage = Number(percentage);

        const safePercentage = Math.min(
            100,
            Math.max(
                0,
                Number.isFinite(numericPercentage) ? numericPercentage : 0
            )
        );

        if (processingProgressFill) {
            processingProgressFill.style.width = `${safePercentage}%`;
            processingProgressFill.offsetWidth;
        }

        if (processingProgressPercent) {
            processingProgressPercent.textContent = `${Math.round(safePercentage)}%`;
        }
    }

    // Reset Download Button
    function resetDownloadButton() {
        downloadInProgress = false;
        cancellingDownload = false;

        if (downloadBtn) {
            downloadBtn.disabled = false;
            downloadBtn.textContent = "DOWNLOAD";
        }

        if (cancelDownloadBtn) {
            cancelDownloadBtn.disabled = false;
            cancelDownloadBtn.textContent = "Cancel Download";
            hide(cancelDownloadBtn);
        }
    }

    // Show Cancel Button
    function showCancelButton() {
        if (!cancelDownloadBtn) return;

        cancelDownloadBtn.disabled = false;
        cancelDownloadBtn.textContent = "Cancel Download";
        show(cancelDownloadBtn);
    }

    // Audio Language Options
    function populateLanguageOptions(languages) {
        if (languageOptions) {
            languageOptions.innerHTML = "";
        }

        if (!languages || !Array.isArray(languages) || languages.length === 0) {
            hide(languageContainer);
            return;
        }

        show(languageContainer);

        languages.forEach((language, index) => {
            if (!language || !language.code) return;

            const label = document.createElement("label");
            label.className = "radio-item";

            const input = document.createElement("input");
            input.type = "radio";
            input.name = "language";
            input.value = language.code;

            if (index === 0) {
                input.checked = true;
            }

            const span = document.createElement("span");
            span.textContent = language.name || language.code;

            label.appendChild(input);
            label.appendChild(span);
            languageOptions.appendChild(label);
        });
    }

    // Analyze Button
    analyzeBtn.addEventListener("click", async () => {
        const url = videoUrlInput.value.trim();

        if (!url) {
            showError("Please enter a valid video URL.");
            return;
        }

        clearError();

        hide(analysisResult);
        hide(progressSection);
        hide(successSection);

        if (progressInterval) {
            clearInterval(progressInterval);
            progressInterval = null;
        }

        resetProgressUI();

        if (languageOptions) {
            languageOptions.innerHTML = "";
        }

        hide(languageContainer);

        analyzeBtn.disabled = true;
        analyzeBtn.textContent = "ANALYZING...";

        try {
            const response = await fetch("/api/analyze", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json"
                },
                body: JSON.stringify({
                    url: url
                })
            });

            const data = await response.json();

            if (data.success) {
                currentVideoUrl = url;

                if (data.thumbnail) {
                    thumbImg.src = data.thumbnail;
                }

                videoTitle.textContent = data.title || "Unknown title";

                videoDuration.textContent = `Duration: ${
                    data.duration_string || formatTime(data.duration)
                }`;

                qualityOptions.innerHTML = "";

                if (data.qualities && data.qualities.length > 0) {
                    show(qualityContainer);

                    data.qualities.forEach((quality, index) => {
                        const label = document.createElement("label");
                        label.className = "radio-item";

                        label.innerHTML = `
                            <input
                                type="radio"
                                name="quality"
                                value="${quality}"
                                ${index === data.qualities.length - 1 ? "checked" : ""}
                            >
                            <span>${quality}</span>
                        `;

                        qualityOptions.appendChild(label);
                    });
                } else {
                    hide(qualityContainer);
                }

                populateLanguageOptions(data.languages);
                show(analysisResult);
            } else {
                showError(data.error || "Failed to analyze the video.");
            }
        } catch (error) {
            console.error("Analysis error:", error);
            showError("An error occurred while analyzing the video.");
        } finally {
            analyzeBtn.disabled = false;
            analyzeBtn.textContent = "ANALYZE";
        }
    });

    // Download Button
    downloadBtn.addEventListener("click", async () => {
        if (downloadInProgress) return;

        if (!currentVideoUrl) {
            showError("Please analyze a video before downloading.");
            return;
        }

        const selectedFormat = document.querySelector(
            'input[name="format"]:checked'
        );

        if (!selectedFormat) {
            showError("Please select a format.");
            return;
        }

        const format = selectedFormat.value;

        const selectedQuality = document.querySelector(
            'input[name="quality"]:checked'
        );

        const quality = selectedQuality
            ? selectedQuality.value
            : "1080p";

        const selectedLanguage = document.querySelector(
            'input[name="language"]:checked'
        );

        const language = selectedLanguage
            ? selectedLanguage.value
            : "";

        downloadInProgress = true;
        cancellingDownload = false;

        downloadBtn.disabled = true;
        downloadBtn.textContent = "DOWNLOADING...";

        clearError();

        hide(analysisResult);
        hide(successSection);
        show(progressSection);
        showCancelButton();

        resetProgressUI();

        if (processingProgressContainer) {
            hide(processingProgressContainer);
        }

        try {
            const response = await fetch("/api/download", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json"
                },
                body: JSON.stringify({
                    url: currentVideoUrl,
                    format: format,
                    quality: quality,
                    language: language
                })
            });

            const data = await response.json();

            if (data.success) {
                startPollingProgress();
            } else {
                showError(data.error || "Failed to start download.");
                hide(progressSection);
                hide(successSection);
                resetDownloadButton();
            }
        } catch (error) {
            console.error("Download error:", error);

            showError(
                "An error occurred while starting the download."
            );

            hide(progressSection);
            hide(successSection);
            resetDownloadButton();
        }
    });

    // Cancel Download Button
    if (cancelDownloadBtn) {
        cancelDownloadBtn.addEventListener("click", async () => {
            if (!downloadInProgress || cancellingDownload) return;

            const confirmed = window.confirm(
                "Are you sure you want to cancel this download?"
            );

            if (!confirmed) return;

            cancellingDownload = true;

            cancelDownloadBtn.disabled = true;
            cancelDownloadBtn.textContent = "CANCELLING...";

            if (downloadBtn) {
                downloadBtn.disabled = true;
                downloadBtn.textContent = "CANCELLING...";
            }

            try {
                const response = await fetch("/api/cancel", {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/json"
                    }
                });

                const data = await response.json();

                if (!data.success) {
                    throw new Error(
                        data.message || "Unable to cancel download."
                    );
                }

                if (progressStatus) {
                    progressStatus.textContent = "Cancelling...";
                }

                if (processingProgressStatus) {
                    processingProgressStatus.textContent = "Cancelling...";
                }
            } catch (error) {
                console.error("Cancel error:", error);

                cancellingDownload = false;

                if (cancelDownloadBtn) {
                    cancelDownloadBtn.disabled = false;
                    cancelDownloadBtn.textContent = "Cancel Download";
                }

                if (downloadBtn) {
                    downloadBtn.disabled = true;
                    downloadBtn.textContent = "DOWNLOADING...";
                }

                showError(
                    error.message ||
                    "Could not cancel the download."
                );
            }
        });
    }

    // Progress Polling
    function startPollingProgress() {
        if (progressInterval) {
            clearInterval(progressInterval);
        }

        progressInterval = setInterval(async () => {
            try {
                const response = await fetch("/api/progress", {
                    cache: "no-store"
                });

                const data = await response.json();

                // Starting
                if (data.status === "starting") {
                    progressStatus.textContent = "Starting...";
                    updateDownloadProgress(0);

                    if (progressSpeed) {
                        progressSpeed.textContent = "Speed: 0 MB/s";
                    }

                    if (progressEta) {
                        progressEta.textContent = "Remaining: --";
                    }

                    if (processingProgressContainer) {
                        hide(processingProgressContainer);
                    }

                    processingStarted = false;
                }

                // Downloading
                else if (data.status === "downloading") {
                    if (processingProgressContainer) {
                        hide(processingProgressContainer);
                    }

                    const percentage =
                        Number(
                            data.download_percentage ?? data.percentage
                        ) || 0;

                    updateDownloadProgress(percentage);

                    progressStatus.textContent = "Downloading...";

                    progressSpeed.textContent = `Speed: ${
                        data.speed || "0 MB/s"
                    }`;

                    progressEta.textContent = `Remaining: ${
                        data.eta || "--"
                    }`;

                    processingStarted = false;
                }

                // Processing
                else if (data.status === "processing") {
                    // Download bar stays at 100%.
                    updateDownloadProgress(100);

                    progressStatus.textContent =
                        "Download complete";

                    progressSpeed.textContent =
                        "Speed: Download complete";

                    progressEta.textContent =
                        "Remaining: 00:00";

                    // Start processing from 0%.
                    startProcessingProgress();

                    const processingPercentage =
                        Number(data.processing_percentage) || 0;

                    // Update processing bar.
                    updateProcessingProgress(
                        processingPercentage
                    );

                    if (processingProgressStatus) {
                        processingProgressStatus.textContent =
                            processingPercentage >= 100
                                ? "Processing complete"
                                : "Processing...";
                    }
                }

                // Cancelling
                else if (data.status === "cancelling") {
                    progressStatus.textContent = "Cancelling...";

                    progressSpeed.textContent =
                        "Speed: Cancelling...";

                    progressEta.textContent =
                        "Remaining: --";

                    if (processingProgressStatus) {
                        processingProgressStatus.textContent =
                            "Cancelling...";
                    }
                }

                // Completed
                else if (data.status === "completed") {
                    // Ignore stale completed response after cancellation.
                    if (cancellingDownload) {
                        progressStatus.textContent =
                            "Cancelling...";

                        progressSpeed.textContent =
                            "Speed: Cancelling...";

                        progressEta.textContent =
                            "Remaining: --";

                        return;
                    }

                    clearInterval(progressInterval);
                    progressInterval = null;

                    // Download = 100%
                    updateDownloadProgress(100);

                    progressStatus.textContent =
                        "Download complete";

                    progressSpeed.textContent =
                        "Speed: Completed";

                    progressEta.textContent =
                        "Remaining: 00:00";

                    // Processing = 100%
                    startProcessingProgress();
                    updateProcessingProgress(100);

                    if (processingProgressStatus) {
                        processingProgressStatus.textContent =
                            "Processing complete";
                    }

                    hide(progressSection);
                    show(successSection);

                    resetDownloadButton();
                }

                // Cancelled
                else if (data.status === "cancelled") {
                    clearInterval(progressInterval);
                    progressInterval = null;

                    updateDownloadProgress(0);
                    updateProcessingProgress(0);

                    processingStarted = false;

                    progressStatus.textContent =
                        "Download cancelled";

                    progressSpeed.textContent =
                        "Speed: 0 MB/s";

                    progressEta.textContent =
                        "Remaining: --";

                    if (processingProgressStatus) {
                        processingProgressStatus.textContent =
                            "Processing cancelled";
                    }

                    hide(progressSection);
                    hide(successSection);

                    resetDownloadButton();
                    show(analysisResult);
                }

                // Error
                else if (data.status === "error") {
                    clearInterval(progressInterval);
                    progressInterval = null;

                    hide(progressSection);
                    hide(successSection);

                    showError(
                        data.error ||
                        "Download failed."
                    );

                    resetDownloadButton();
                }

                // Idle
                else if (data.status === "idle") {
                    clearInterval(progressInterval);
                    progressInterval = null;

                    if (!downloadInProgress) {
                        hide(successSection);
                    }

                    resetDownloadButton();
                }
            } catch (error) {
                console.error(
                    "Progress polling error:",
                    error
                );
            }
        }, 300);
    }

    // Format Selection
    document
        .querySelectorAll('input[name="format"]')
        .forEach((radio) => {
            radio.addEventListener("change", (event) => {
                if (event.target.value === "mp3") {
                    hide(qualityContainer);
                } else {
                    show(qualityContainer);
                }
            });
        });

    // Open Downloads Folder
    const openFolderBtn =
        document.getElementById("open-folder-btn");

    if (openFolderBtn) {
        openFolderBtn.addEventListener("click", () => {
            alert(
                'Downloads are saved in the "downloads" folder inside the project directory.'
            );
        });
    }
});