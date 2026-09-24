
  // Simple interactive feedback simulation for Connect screen
  document.getElementById('connect-yt-btn')?.addEventListener('click', function() {
    const btn = this;
    const originalText = btn.innerHTML;
    btn.innerHTML = '<span class="material-symbols-outlined text-[18px] animate-spin">progress_activity</span><span>Authenticating...</span>';
    btn.classList.add('opacity-80');
    setTimeout(() => {
      btn.innerHTML = '<span class="material-symbols-outlined text-[18px]">verified</span><span>Auth Prompt Dispatched</span>';
      setTimeout(() => {
        btn.innerHTML = originalText;
        btn.classList.remove('opacity-80');
      }, 3000);
    }, 1200);
  });

  document.getElementById('refresh-diagnostics-btn')?.addEventListener('click', function() {
    const icon = this.querySelector('span');
    icon.classList.add('animate-spin');
    setTimeout(() => {
      icon.classList.remove('animate-spin');
    }, 800);
  });
