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
});
