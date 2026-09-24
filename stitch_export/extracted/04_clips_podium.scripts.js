
    (() => {
      const activeNav = document.querySelector('aside nav a[data-path="clips"]');
      if (activeNav) {
        document.querySelectorAll('aside nav a').forEach(a => {
          a.className = 'flex items-center gap-3 px-4 py-3 rounded-full text-on-surface-variant hover:text-on-surface hover:bg-white/[0.06] transition-all font-body-md text-body-md';
        });
        activeNav.className = 'flex items-center gap-3 px-4 py-3 rounded-full bg-primary text-on-primary font-semibold shadow-[0_0_20px_rgba(255,255,255,0.35)] transition-all font-body-md text-body-md';
      }
    })();
  