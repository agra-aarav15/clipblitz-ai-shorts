
  (function() {
    const searchInput = document.getElementById('transcript-search');
    const container = document.getElementById('transcript-container');
    if (!searchInput || !container) return;

    searchInput.addEventListener('input', function(e) {
      const term = e.target.value.toLowerCase().trim();
      const blocks = container.querySelectorAll('.flex-1 p');
      
      blocks.forEach(p => {
        const parent = p.closest('.group, .bg-white\\[0\\.08\\]');
        if (!parent) return;
        
        if (!term) {
          parent.style.display = 'flex';
          return;
        }

        const text = p.textContent.toLowerCase();
        if (text.includes(term)) {
          parent.style.display = 'flex';
        } else {
          parent.style.display = 'none';
        }
      });
    });
  })();
