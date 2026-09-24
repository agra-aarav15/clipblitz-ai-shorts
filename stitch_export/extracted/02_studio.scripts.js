
  (function initStudioCockpit() {
    // Synchronize Sidebar "Studio" Active Pill State
    const navItems = document.querySelectorAll('aside nav a');
    navItems.forEach(item => {
      if (item.getAttribute('data-path') === 'studio') {
        item.classList.add('bg-primary', 'text-on-primary', 'font-semibold', 'shadow-[0_0_20px_rgba(255,255,255,0.35)]');
        item.classList.remove('text-on-surface-variant');
      } else {
        item.classList.remove('bg-primary', 'text-on-primary', 'font-semibold', 'shadow-[0_0_20px_rgba(255,255,255,0.35)]');
        item.classList.add('text-on-surface-variant');
      }
    });

    // Make Clips Button Click Feedback
    const makeBtn = document.getElementById('make-clips-btn');
    const inputField = document.getElementById('url-input');
    const dropzone = document.getElementById('dropzone');

    if (makeBtn && inputField) {
      makeBtn.addEventListener('click', () => {
        const val = inputField.value.trim();
        if (!val) {
          inputField.placeholder = "Enter a valid YouTube URL first...";
          inputField.focus();
        } else {
          makeBtn.innerHTML = '<span>ANALYZING...</span><span class="material-symbols-outlined text-[18px] animate-spin">progress_activity</span>';
          setTimeout(() => {
            makeBtn.innerHTML = '<span>COMPLETE</span><span class="material-symbols-outlined text-[18px]">check</span>';
            setTimeout(() => {
              makeBtn.innerHTML = '<span>MAKE CLIPS</span><span class="material-symbols-outlined text-[18px]">bolt</span>';
            }, 1800);
          }, 1400);
        }
      });
    }

    // Dropzone interaction simulation
    if (dropzone) {
      dropzone.addEventListener('dragover', (e) => {
        e.preventDefault();
        dropzone.classList.add('bg-white/[0.08]', 'scale-[1.01]');
      });
      dropzone.addEventListener('dragleave', () => {
        dropzone.classList.remove('bg-white/[0.08]', 'scale-[1.01]');
      });
      dropzone.addEventListener('drop', (e) => {
        e.preventDefault();
        dropzone.classList.remove('bg-white/[0.08]', 'scale-[1.01]');
        const textElem = dropzone.querySelector('span:first-of-type');
        if (textElem) {
          const original = textElem.innerText;
          textElem.innerText = "Ingesting MP4 file payload...";
          setTimeout(() => { textElem.innerText = original; }, 2000);
        }
      });
    }
  })();
