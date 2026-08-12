// NetPlex Tudum Client Interaction Script

document.addEventListener('DOMContentLoaded', () => {
    const modalBackdrop = document.getElementById('trailer-modal');
    const modalTitle = document.getElementById('modal-media-title');
    const videoPlayer = document.getElementById('modal-video-player');
    const closeBtn = document.getElementById('modal-close-btn');

    // Open video trailer modal
    window.openTrailerModal = (itemId, title) => {
        if (window.DUMMY_MEDIA_MODE) {
            console.log('Dummy media mode enabled: trailer player UI disabled.');
            return;
        }
        if (!modalBackdrop || !videoPlayer) return;
        
        if (modalTitle) {
            modalTitle.textContent = title;
        }
        
        // Set video source
        videoPlayer.src = `/stream/video/${itemId}`;
        modalBackdrop.classList.add('active');
        
        // Autoplay if possible
        videoPlayer.play().catch(err => {
            console.log('Autoplay prevented or video unavailable:', err);
        });
    };

    // Close video trailer modal
    window.closeTrailerModal = () => {
        if (!modalBackdrop || !videoPlayer) return;
        
        videoPlayer.pause();
        videoPlayer.src = '';
        modalBackdrop.classList.remove('active');
    };

    if (closeBtn) {
        closeBtn.addEventListener('click', window.closeTrailerModal);
    }

    if (modalBackdrop) {
        modalBackdrop.addEventListener('click', (e) => {
            if (e.target === modalBackdrop) {
                window.closeTrailerModal();
            }
        });
    }

    // Keyboard ESC listener
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && modalBackdrop && modalBackdrop.classList.contains('active')) {
            window.closeTrailerModal();
        }
    });

    // Global Crawl Status Management
    let crawlPollInterval = null;
    let wasCrawling = false;

    function updateCrawlStatusUI(isCrawling, taskDisplay = null, statusMessage = null) {
        const displayLabel = taskDisplay || "Crawling...";
        
        const landingBtn = document.getElementById('btn-landing-crawl');
        if (landingBtn) {
            if (isCrawling) {
                landingBtn.disabled = true;
                landingBtn.textContent = `⏳ ${displayLabel}`;
            } else {
                landingBtn.disabled = false;
                landingBtn.textContent = taskDisplay || "▶ Trigger Crawl";
            }
        }

        const settingsBtn = document.getElementById('btn-trigger-crawl');
        const settingsBadge = document.getElementById('crawl-status-badge');
        if (settingsBtn) {
            if (isCrawling) {
                settingsBtn.disabled = true;
                settingsBtn.textContent = `▶ ${displayLabel}`;
            } else {
                settingsBtn.disabled = false;
                settingsBtn.textContent = "▶ Trigger Manual Crawl Job";
            }
        }
        if (settingsBadge) {
            if (isCrawling) {
                settingsBadge.textContent = `Status: ${statusMessage || displayLabel}`;
                settingsBadge.style.color = "#f1c40f";
            } else {
                settingsBadge.textContent = statusMessage || "Status: Idle";
                settingsBadge.style.color = "var(--text-secondary)";
            }
        }
    }

    async function checkCrawlStatus() {
        try {
            const resp = await fetch('/api/crawl/status');
            if (!resp.ok) return;
            const data = await resp.json();

            if (data.is_crawling) {
                wasCrawling = true;
                updateCrawlStatusUI(true, data.task_display, data.message);
                startPolling();
            } else {
                if (wasCrawling) {
                    wasCrawling = false;
                    stopPolling();
                    updateCrawlStatusUI(false, "✓ Crawl Done!", "Status: ✓ Crawl Done!");
                    if (document.getElementById('btn-landing-crawl')) {
                        setTimeout(() => window.location.reload(), 1000);
                    } else {
                        setTimeout(() => updateCrawlStatusUI(false), 3000);
                    }
                } else {
                    stopPolling();
                    updateCrawlStatusUI(false);
                }
            }
        } catch (err) {
            console.error("Error checking crawl status:", err);
        }
    }

    function startPolling() {
        if (!crawlPollInterval) {
            crawlPollInterval = setInterval(checkCrawlStatus, 1500);
        }
    }

    function stopPolling() {
        if (crawlPollInterval) {
            clearInterval(crawlPollInterval);
            crawlPollInterval = null;
        }
    }

    window.triggerManualCrawl = async () => {
        const landingBtn = document.getElementById('btn-landing-crawl');
        const settingsBtn = document.getElementById('btn-trigger-crawl');
        const settingsBadge = document.getElementById('crawl-status-badge');

        if (landingBtn) landingBtn.disabled = true;
        if (settingsBtn) settingsBtn.disabled = true;
        if (settingsBadge) {
            settingsBadge.textContent = "Status: Initiating pipeline...";
            settingsBadge.style.color = "#f1c40f";
        }

        try {
            const resp = await fetch('/api/crawl', { method: 'POST' });
            if (resp.status === 202) {
                wasCrawling = true;
                updateCrawlStatusUI(true, "Status: Crawl job in progress in background...");
                startPolling();
            } else if (resp.status === 409) {
                wasCrawling = true;
                updateCrawlStatusUI(true, "Status: A crawl job is already running!");
                startPolling();
            } else {
                throw new Error(`Unexpected status code ${resp.status}`);
            }
        } catch (err) {
            updateCrawlStatusUI(false, `Status: Error - ${err.message}`);
            setTimeout(() => updateCrawlStatusUI(false), 3000);
        }
    };

    window.triggerManualCrawlFromLanding = window.triggerManualCrawl;

    // Check crawl status immediately on page load
    checkCrawlStatus();
});
