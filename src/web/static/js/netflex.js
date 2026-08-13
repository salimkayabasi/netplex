// NetPlex Tudum Client Interaction Script

// Storage Keys for Video Playback & Mute Preferences
const STORAGE_KEY_AUTOPLAY = 'netplex_video_autoplay';
const STORAGE_KEY_MUTED = 'netplex_video_muted';

let isPageNavigating = false;
window.addEventListener('beforeunload', () => {
    isPageNavigating = true;
});

function getSavedAutoplay() {
    const saved = localStorage.getItem(STORAGE_KEY_AUTOPLAY);
    return saved === null ? true : saved === 'true';
}

function setSavedAutoplay(val) {
    localStorage.setItem(STORAGE_KEY_AUTOPLAY, val ? 'true' : 'false');
}

function getSavedMuted() {
    const saved = localStorage.getItem(STORAGE_KEY_MUTED);
    return saved === 'true';
}

function setSavedMuted(val) {
    localStorage.setItem(STORAGE_KEY_MUTED, val ? 'true' : 'false');
}

function bindVideoPrefEvents(video, isModalPlayer = false) {
    if (!video || video.dataset.prefEventsBound === 'true') return;
    video.dataset.prefEventsBound = 'true';

    // Set initial mute state from local storage
    video.muted = getSavedMuted();

    // When user plays video, save autoplay = true preference
    video.addEventListener('play', () => {
        setSavedAutoplay(true);
    });

    // When user pauses video, save autoplay = false preference
    video.addEventListener('pause', () => {
        if (isPageNavigating) return;
        if (video.ended) return;
        if (isModalPlayer) {
            const modalBackdrop = document.getElementById('trailer-modal');
            if (!modalBackdrop || !modalBackdrop.classList.contains('active') || !video.src || video.src === window.location.href) {
                return;
            }
        }
        setSavedAutoplay(false);
    });

    // When user changes volume/mute state, update saved muted preference
    video.addEventListener('volumechange', () => {
        setSavedMuted(video.muted);
    });
}

document.addEventListener('DOMContentLoaded', () => {
    const modalBackdrop = document.getElementById('trailer-modal');
    const modalTitle = document.getElementById('modal-media-title');
    const videoPlayer = document.getElementById('modal-video-player');
    const closeBtn = document.getElementById('modal-close-btn');
    const ytBtn = document.getElementById('modal-yt-btn');

    // Bind preference tracking for modal player
    if (videoPlayer) {
        bindVideoPrefEvents(videoPlayer, true);
    }

    // Bind preference tracking and initial playback state for detail page video player
    const detailVideoPlayer = document.getElementById('detail-video-player');
    if (detailVideoPlayer) {
        bindVideoPrefEvents(detailVideoPlayer, false);

        detailVideoPlayer.muted = getSavedMuted();

        if (getSavedAutoplay()) {
            detailVideoPlayer.play().catch(err => {
                console.log('Autoplay prevented or video unavailable:', err);
            });
        } else {
            detailVideoPlayer.pause();
        }
    }

    // Open video trailer modal
    window.openTrailerModal = (itemId, title, youtubeUrl) => {
        if (window.DUMMY_MEDIA_MODE) {
            console.log('Dummy media mode enabled: trailer player UI disabled.');
            return;
        }
        if (!modalBackdrop || !videoPlayer) return;
        
        if (modalTitle) {
            modalTitle.textContent = title;
        }

        if (ytBtn) {
            if (youtubeUrl && typeof youtubeUrl === 'string' && youtubeUrl.trim() !== '' && youtubeUrl.trim() !== 'None' && youtubeUrl.trim() !== 'null') {
                ytBtn.href = youtubeUrl.trim();
                ytBtn.style.display = 'inline-flex';
            } else {
                ytBtn.href = '#';
                ytBtn.style.display = 'none';
            }
        }
        
        // Set video source
        videoPlayer.src = `/stream/video/${itemId}`;
        videoPlayer.muted = getSavedMuted();
        modalBackdrop.classList.add('active');
        
        // Autoplay if saved preference allows
        if (getSavedAutoplay()) {
            videoPlayer.play().catch(err => {
                console.log('Autoplay prevented or video unavailable:', err);
            });
        } else {
            videoPlayer.pause();
        }
    };

    // Close video trailer modal
    window.closeTrailerModal = () => {
        if (!modalBackdrop || !videoPlayer) return;
        
        modalBackdrop.classList.remove('active');
        videoPlayer.pause();
        videoPlayer.src = '';
        if (ytBtn) {
            ytBtn.href = '#';
            ytBtn.style.display = 'none';
        }
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

    // Keyboard ESC and Arrow navigation listeners
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' || e.key === 'Esc') {
            if (modalBackdrop && modalBackdrop.classList.contains('active')) {
                window.closeTrailerModal();
                return;
            }

            if (document.fullscreenElement || document.webkitFullscreenElement || document.mozFullScreenElement || document.msFullscreenElement) {
                return;
            }

            const activeElem = document.activeElement;
            if (activeElem && (['INPUT', 'TEXTAREA', 'SELECT'].includes(activeElem.tagName) || activeElem.isContentEditable)) {
                activeElem.blur();
                return;
            }

            const backLink = document.querySelector('.back-link');
            if (backLink) {
                backLink.click();
                return;
            }
        }

        // Detail Page Prev/Next keyboard navigation
        const activeElem = document.activeElement;
        if (activeElem && (['INPUT', 'TEXTAREA', 'SELECT'].includes(activeElem.tagName) || activeElem.isContentEditable)) {
            return;
        }

        if (e.key === 'ArrowLeft') {
            const prevBtn = document.getElementById('detail-prev-link') || document.querySelector('.side-arrow-left');
            if (prevBtn) {
                prevBtn.click();
            }
        } else if (e.key === 'ArrowRight') {
            const nextBtn = document.getElementById('detail-next-link') || document.querySelector('.side-arrow-right');
            if (nextBtn) {
                nextBtn.click();
            }
        }
    });

    // Global Crawl Status Management
    let crawlPollInterval = null;
    let wasCrawling = false;

    function updateCrawlStatusUI(isCrawling, taskDisplay = null, statusMessage = null) {
        const displayLabel = taskDisplay || "Crawling...";
        
        const landingBtn = document.getElementById('btn-landing-crawl');
        const landingLabel = document.getElementById('btn-landing-crawl-label');
        const landingIcon = landingBtn ? landingBtn.querySelector('.crawl-icon') : null;

        if (landingBtn) {
            landingBtn.disabled = isCrawling;
            if (landingLabel) {
                landingLabel.textContent = isCrawling ? displayLabel : (taskDisplay || "Sync & Crawl");
            } else {
                landingBtn.textContent = isCrawling ? displayLabel : (taskDisplay || "Sync & Crawl");
            }
            if (landingIcon) {
                if (isCrawling) {
                    landingIcon.classList.add('spinning');
                } else {
                    landingIcon.classList.remove('spinning');
                }
            }
        }

        const settingsBtn = document.getElementById('btn-trigger-crawl');
        const settingsLabel = document.getElementById('btn-trigger-crawl-label');
        const settingsIcon = settingsBtn ? settingsBtn.querySelector('.crawl-icon') : null;

        if (settingsBtn) {
            settingsBtn.disabled = isCrawling;
            if (settingsLabel) {
                settingsLabel.textContent = isCrawling ? displayLabel : "Trigger Manual Crawl Job";
            } else {
                settingsBtn.textContent = isCrawling ? displayLabel : "Trigger Manual Crawl Job";
            }
            if (settingsIcon) {
                if (isCrawling) {
                    settingsIcon.classList.add('spinning');
                } else {
                    settingsIcon.classList.remove('spinning');
                }
            }
        }

        const settingsDot = document.getElementById('crawl-status-dot');
        const settingsStatusText = document.getElementById('crawl-status-text');
        const settingsBadge = document.getElementById('crawl-status-badge');

        if (settingsStatusText) {
            settingsStatusText.textContent = statusMessage || (isCrawling ? `Status: ${displayLabel}` : "Status: Idle");
        } else if (settingsBadge) {
            settingsBadge.textContent = statusMessage || (isCrawling ? `Status: ${displayLabel}` : "Status: Idle");
        }

        if (settingsDot) {
            settingsDot.classList.remove('active-running', 'active-success');
            if (isCrawling) {
                settingsDot.classList.add('active-running');
            } else if (statusMessage && statusMessage.includes('Done')) {
                settingsDot.classList.add('active-success');
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
                updateCrawlStatusUI(true, data.task_display, `Status: ${data.message || data.task_display}`);
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
        const settingsDot = document.getElementById('crawl-status-dot');
        const settingsStatusText = document.getElementById('crawl-status-text');

        if (landingBtn) landingBtn.disabled = true;
        if (settingsBtn) settingsBtn.disabled = true;
        
        if (settingsDot) {
            settingsDot.classList.remove('active-success');
            settingsDot.classList.add('active-running');
        }
        if (settingsStatusText) {
            settingsStatusText.textContent = "Status: Initiating pipeline...";
        }

        try {
            const resp = await fetch('/api/crawl', { method: 'POST' });
            if (resp.status === 202) {
                wasCrawling = true;
                updateCrawlStatusUI(true, "Initiating...", "Status: Crawl job in progress...");
                startPolling();
            } else if (resp.status === 409) {
                wasCrawling = true;
                updateCrawlStatusUI(true, "Crawling...", "Status: A crawl job is already running!");
                startPolling();
            } else {
                throw new Error(`Unexpected status code ${resp.status}`);
            }
        } catch (err) {
            if (settingsDot) settingsDot.classList.remove('active-running');
            updateCrawlStatusUI(false, null, `Status: Error - ${err.message}`);
            setTimeout(() => updateCrawlStatusUI(false), 3000);
        }
    };

    window.triggerManualCrawlFromLanding = window.triggerManualCrawl;

    // Check crawl status immediately on page load
    checkCrawlStatus();
});
