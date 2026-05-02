(function () {
  var fileInput = document.getElementById('pfProfileImageInput');
  var removeBtn = document.getElementById('pfRemoveImageBtn');
  var clearFlag = document.getElementById('pfClearProfileImage');
  var heroImage = document.getElementById('pfAvatarImage');
  var heroFallback = document.getElementById('pfAvatarFallback');
  var previewImage = document.getElementById('pfPreviewImage');
  var previewFallback = document.getElementById('pfPreviewFallback');

  function setPreview(src) {
    if (heroImage) {
      heroImage.src = src || '';
      heroImage.classList.toggle('is-hidden', !src);
    }
    if (previewImage) {
      previewImage.src = src || '';
      previewImage.classList.toggle('is-hidden', !src);
    }
    if (heroFallback) heroFallback.style.display = src ? 'none' : 'flex';
    if (previewFallback) previewFallback.style.display = src ? 'none' : 'flex';
  }

  if (fileInput) {
    fileInput.addEventListener('change', function (event) {
      var file = event.target.files && event.target.files[0];
      if (!file) return;
      clearFlag.value = '0';
      var reader = new FileReader();
      reader.onload = function (loadEvent) {
        setPreview(loadEvent.target && loadEvent.target.result ? loadEvent.target.result : '');
      };
      reader.readAsDataURL(file);
    });
  }

  if (removeBtn) {
    removeBtn.addEventListener('click', function () {
      if (fileInput) fileInput.value = '';
      if (clearFlag) clearFlag.value = '1';
      setPreview('');
    });
  }
})();
