// NetPlex Tudum Client Interaction Script

document.addEventListener('DOMContentLoaded', () => {
    const modalBackdrop = document.getElementById('trailer-modal');
    const modalTitle = document.getElementById('modal-media-title');
    const videoPlayer = document.getElementById('modal-video-player');
    const closeBtn = document.getElementById('modal-close-btn');

    // Open video trailer modal
    window.openTrailerModal = (itemId, title) => {
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

    // Country/Category select change handler
    const countrySelect = document.getElementById('country-select');
    if (countrySelect) {
        countrySelect.addEventListener('change', (e) => {
            const selectedCountry = e.target.value;
            const currentUrl = new URL(window.location.href);
            currentUrl.searchParams.set('country', selectedCountry);
            window.location.href = currentUrl.toString();
        });
    }

    // Trigger Manual Crawl from landing page handler
    window.triggerManualCrawlFromLanding = async () => {
        const btn = document.getElementById('btn-landing-crawl');
        if (!btn) return;
        btn.disabled = true;
        btn.textContent = "⏳ Crawling...";
        try {
            const resp = await fetch('/api/crawl', { method: 'POST' });
            if (resp.status === 202) {
                btn.textContent = "▶ Crawling in progress...";
                const interval = setInterval(async () => {
                    try {
                        const statusResp = await fetch('/api/crawl/status');
                        const data = await statusResp.json();
                        if (!data.is_crawling) {
                            clearInterval(interval);
                            btn.textContent = "✓ Crawl Done!";
                            setTimeout(() => window.location.reload(), 1000);
                        }
                    } catch (err) {
                        console.error("Crawl status check error:", err);
                    }
                }, 3000);
            } else if (resp.status === 409) {
                btn.textContent = "⚠️ Crawl Active";
                setTimeout(() => {
                    btn.disabled = false;
                    btn.textContent = "▶ Trigger Crawl";
                }, 3000);
            } else {
                throw new Error(`Status ${resp.status}`);
            }
        } catch (err) {
            btn.textContent = "❌ Crawl Failed";
            setTimeout(() => {
                btn.disabled = false;
                btn.textContent = "▶ Trigger Crawl";
            }, 3000);
        }
    };
});
