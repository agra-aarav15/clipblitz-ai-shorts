
    function toggleKeyVis(inputId, btn) {
      const input = document.getElementById(inputId);
      const icon = btn.querySelector('.material-symbols-outlined');
      if (!input || !icon) return;
      if (input.type === 'password') {
        input.type = 'text';
        icon.textContent = 'visibility_off';
      } else {
        input.type = 'password';
        icon.textContent = 'visibility';
      }
    }

    function triggerTest(btn, successMsg) {
      const originalText = btn.innerHTML;
      btn.disabled = true;
      btn.innerHTML = '<span class="material-symbols-outlined text-sm animate-spin">progress_activity</span><span>CHECKING...</span>';
      setTimeout(() => {
        btn.innerHTML = '<span class="material-symbols-outlined text-sm">check</span><span>VERIFIED</span>';
        setTimeout(() => {
          btn.innerHTML = originalText;
          btn.disabled = false;
        }, 1800);
      }, 700);
    }

    function runMasterCalibration(btn) {
      const original = btn.innerHTML;
      btn.disabled = true;
      btn.innerHTML = '<span class="material-symbols-outlined text-lg animate-spin">progress_activity</span><span>SYNCHRONIZING ENGINES...</span>';
      setTimeout(() => {
        btn.innerHTML = '<span class="material-symbols-outlined text-lg">done_all</span><span>ALL ENGINES LIVE</span>';
        setTimeout(() => {
          btn.innerHTML = original;
          btn.disabled = false;
        }, 2200);
      }, 1100);
    }
  