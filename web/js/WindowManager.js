export class WindowManager {
    constructor() {
        this.windows = document.querySelectorAll('.window');
        this.zIndex = 1000;
        this.init();
    }

    init() {
        this.windows.forEach(win => {
            this.setupWindow(win);
        });

        // Global click to deselect?
        document.addEventListener('mousedown', (e) => {
            if (!e.target.closest('.window')) {
                this.windows.forEach(w => w.classList.remove('active'));
            }
        });
    }

    setupWindow(win) {
        // Bring to front on click
        win.addEventListener('mousedown', () => {
            this.bringToFront(win);
        });

        const header = win.querySelector('.window-header');
        if (header) {
            this.setupDrag(win, header);

            // Minimize Support
            const minBtn = header.querySelector('.minimize');
            if (minBtn) {
                minBtn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    win.classList.toggle('minimized');
                });
            }
        }
    }

    bringToFront(win) {
        this.zIndex++;
        win.style.zIndex = this.zIndex;
        this.windows.forEach(w => w.classList.remove('active'));
        win.classList.add('active');
    }

    setupDrag(win, handle) {
        let isDragging = false;
        let startX, startY, initialLeft, initialTop;

        handle.addEventListener('mousedown', (e) => {
            if (e.target.closest('.win-btn')) return; // Ignore buttons

            isDragging = true;
            startX = e.clientX;
            startY = e.clientY;

            const rect = win.getBoundingClientRect();
            // We use style.left if set, else computation
            initialLeft = win.offsetLeft;
            initialTop = win.offsetTop;

            // Remove transform centering if it exists (for the Sim Control bar)
            // This is a bit tricky if we used transform: translate(-50%).
            // For general windows, easy. active classes are robust.

            win.style.cursor = 'grabbing';
            handle.style.cursor = 'grabbing';
        });

        window.addEventListener('mousemove', (e) => {
            if (!isDragging) return;
            e.preventDefault();

            const dx = e.clientX - startX;
            const dy = e.clientY - startY;

            win.style.left = `${initialLeft + dx}px`;
            win.style.top = `${initialTop + dy}px`;
            win.style.transform = 'none'; // Clear any centering transforms
        });

        window.addEventListener('mouseup', () => {
            if (isDragging) {
                isDragging = false;
                win.style.cursor = 'default';
                handle.style.cursor = 'grab';
            }
        });
    }
}
