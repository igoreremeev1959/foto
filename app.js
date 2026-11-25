(() => {
  const fileInput = document.getElementById('fileInput');
  const dropzone = document.getElementById('dropzone');
  const preview = document.getElementById('preview');
  const canvas = document.getElementById('photoCanvas');
  const ctx = canvas.getContext('2d', { willReadFrequently: true });
  const stage = document.getElementById('stageWrap');
  const controls = ['exposure', 'contrast', 'saturation', 'warmth', 'clarity'];
  const originalBadge = document.getElementById('originalBadge');
  let originalImage = null;
  let originalPixels = null;
  let renderTimer = null;
  let toastTimer = null;

  const value = (name) => Number(document.getElementById(name).value);
  const clamp = (n) => Math.max(0, Math.min(255, n));
  const contrastFactor = (amount) => {
    const c = amount * 2.55;
    return (259 * (c + 255)) / (255 * (259 - c));
  };

  function updateRange(input) {
    const min = Number(input.min), max = Number(input.max), val = Number(input.value);
    const percent = ((val - min) / (max - min)) * 100;
    input.style.background = `linear-gradient(to right, #9caf65 ${percent}%, #e3e2dc ${percent}%)`;
    const output = document.getElementById(`${input.id}Value`);
    output.textContent = val > 0 ? `+${val}` : `${val}`;
  }

  function showToast(message) {
    const toast = document.getElementById('toast');
    toast.textContent = message;
    toast.classList.add('show');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toast.classList.remove('show'), 2500);
  }

  function setImage(file) {
    if (!file) return;
    if (!file.type.startsWith('image/')) {
      showToast('Please choose an image file.');
      return;
    }
    if (file.size > 25 * 1024 * 1024) {
      showToast('That image is over 25 MB. Try a smaller file.');
      return;
    }
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => {
      originalImage = img;
      const maxSide = 1800;
      const scale = Math.min(1, maxSide / Math.max(img.naturalWidth, img.naturalHeight));
      canvas.width = Math.round(img.naturalWidth * scale);
      canvas.height = Math.round(img.naturalHeight * scale);
      ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
      originalPixels = ctx.getImageData(0, 0, canvas.width, canvas.height);
      document.getElementById('fileName').textContent = file.name;
      document.getElementById('fileSize').textContent = `· ${formatBytes(file.size)}`;
      document.getElementById('photoDimensions').textContent = `${img.naturalWidth} × ${img.naturalHeight} px`;
      dropzone.hidden = true;
      preview.hidden = false;
      stage.classList.add('has-image');
      download.disabled = false;
      resetAdjustments(false);
      URL.revokeObjectURL(url);
    };
    img.onerror = () => {
      URL.revokeObjectURL(url);
      showToast('This image format could not be opened in your browser.');
    };
    img.src = url;
  }

  function formatBytes(bytes) {
    if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }

  function render() {
    if (!originalPixels || !originalImage) return;
    const src = originalPixels.data;
    const out = ctx.createImageData(originalPixels.width, originalPixels.height);
    const dst = out.data;
    const exposure = Math.pow(2, value('exposure') / 100);
    const contrast = contrastFactor(value('contrast'));
    const saturation = 1 + value('saturation') / 100;
    const warmth = value('warmth') * 0.42;
    const clarity = value('clarity') / 100;
    const w = originalPixels.width, h = originalPixels.height;
    // Mild local contrast enhancement adds definition without inventing detail.
    const blur = clarity > 0 ? new Uint8ClampedArray(src.length) : null;
    if (blur) {
      const radius = Math.max(1, Math.round(1 + clarity * 2));
      const step = Math.max(1, Math.floor(Math.max(w, h) / 900));
      for (let y = 0; y < h; y += step) {
        for (let x = 0; x < w; x += step) {
          let r = 0, g = 0, b = 0, count = 0;
          for (let oy = -radius; oy <= radius; oy += step) for (let ox = -radius; ox <= radius; ox += step) {
            const xx = Math.max(0, Math.min(w - 1, x + ox));
            const yy = Math.max(0, Math.min(h - 1, y + oy));
            const i = (yy * w + xx) * 4;
            r += src[i]; g += src[i + 1]; b += src[i + 2]; count++;
          }
          const ri = (y * w + x) * 4;
          blur[ri] = r / count; blur[ri + 1] = g / count; blur[ri + 2] = b / count;
        }
      }
      // Expand the sampled low-frequency layer for a smooth clarity effect.
      for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
        const i = (y * w + x) * 4;
        if (!blur[i] && (x || y)) {
          const si = ((Math.floor(y / step) * step) * w + Math.floor(x / step) * step) * 4;
          blur[i] = blur[si]; blur[i + 1] = blur[si + 1]; blur[i + 2] = blur[si + 2];
        }
      }
    }
    for (let i = 0; i < src.length; i += 4) {
      let r = src[i], g = src[i + 1], b = src[i + 2];
      if (blur) {
        const amount = clarity * 0.8;
        r += (r - blur[i]) * amount;
        g += (g - blur[i + 1]) * amount;
        b += (b - blur[i + 2]) * amount;
      }
      r = (r * exposure - 128) * contrast + 128 + warmth;
      g = (g * exposure - 128) * contrast + 128;
      b = (b * exposure - 128) * contrast + 128 - warmth;
      const luminance = 0.2126 * r + 0.7152 * g + 0.0722 * b;
      dst[i] = clamp(luminance + (r - luminance) * saturation);
      dst[i + 1] = clamp(luminance + (g - luminance) * saturation);
      dst[i + 2] = clamp(luminance + (b - luminance) * saturation);
      dst[i + 3] = src[i + 3];
    }
    ctx.putImageData(out, 0, 0);
  }

  function scheduleRender() {
    clearTimeout(renderTimer);
    renderTimer = setTimeout(render, 15);
  }

  function resetAdjustments(shouldRender = true) {
    controls.forEach((name) => {
      const input = document.getElementById(name);
      input.value = input.dataset.default;
      updateRange(input);
    });
    if (shouldRender) render();
  }

  function autoEnhance() {
    if (!originalPixels) {
      showToast('Choose a photo first to enhance it.');
      return;
    }
    const data = originalPixels.data;
    let sum = 0, sumSq = 0, count = 0;
    const stride = Math.max(4, Math.floor(data.length / 16000 / 4) * 4);
    for (let i = 0; i < data.length; i += stride) {
      const lum = 0.2126 * data[i] + 0.7152 * data[i + 1] + 0.0722 * data[i + 2];
      sum += lum; sumSq += lum * lum; count++;
    }
    const mean = sum / count;
    const contrast = Math.sqrt(Math.max(0, sumSq / count - mean * mean));
    const exposure = Math.max(-20, Math.min(24, Math.round((128 - mean) / 5)));
    document.getElementById('exposure').value = exposure;
    document.getElementById('contrast').value = Math.max(5, Math.min(24, Math.round((56 - contrast) / 2)));
    document.getElementById('saturation').value = 10;
    document.getElementById('warmth').value = 2;
    document.getElementById('clarity').value = 13;
    controls.forEach((name) => updateRange(document.getElementById(name)));
    render();
    showToast('A fresh little lift, just for this photo.');
  }

  controls.forEach((name) => {
    const input = document.getElementById(name);
    updateRange(input);
    input.addEventListener('input', () => { updateRange(input); scheduleRender(); });
  });

  document.getElementById('browseButton').addEventListener('click', () => fileInput.click());
  document.getElementById('uploadButton').addEventListener('click', () => fileInput.click());
  document.getElementById('emptyReplace').addEventListener('click', () => fileInput.click());
  dropzone.addEventListener('click', (event) => { if (!event.target.closest('button')) fileInput.click(); });
  dropzone.addEventListener('keydown', (event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); fileInput.click(); } });
  fileInput.addEventListener('change', (event) => { setImage(event.target.files[0]); event.target.value = ''; });
  document.getElementById('resetButton').addEventListener('click', () => resetAdjustments());
  document.getElementById('autoButton').addEventListener('click', autoEnhance);

  const compareButton = document.getElementById('compareButton');
  function showOriginal(show) {
    if (!originalPixels) return;
    if (show) ctx.putImageData(originalPixels, 0, 0);
    else render();
    originalBadge.classList.toggle('show', show);
    compareButton.setAttribute('aria-pressed', String(show));
  }
  compareButton.addEventListener('pointerdown', (e) => { e.preventDefault(); showOriginal(true); });
  ['pointerup', 'pointerleave', 'pointercancel'].forEach((event) => compareButton.addEventListener(event, () => showOriginal(false)));
  compareButton.addEventListener('keydown', (event) => { if (event.key === ' ' || event.key === 'Enter') showOriginal(true); });
  compareButton.addEventListener('keyup', () => showOriginal(false));

  ['dragenter', 'dragover'].forEach((event) => stage.addEventListener(event, (e) => { e.preventDefault(); dropzone.classList.add('dragging'); }));
  ['dragleave', 'drop'].forEach((event) => stage.addEventListener(event, (e) => { e.preventDefault(); dropzone.classList.remove('dragging'); }));
  stage.addEventListener('drop', (event) => setImage(event.dataTransfer.files[0]));

  const help = document.getElementById('helpDialog');
  document.getElementById('helpButton').addEventListener('click', () => help.showModal());
  document.getElementById('closeHelp').addEventListener('click', () => help.close());
  document.getElementById('dialogOk').addEventListener('click', () => help.close());

  // Export a full-resolution copy with the current adjustments applied.
  const download = document.createElement('button');
  download.className = 'secondary-button download-button';
  download.type = 'button';
  download.textContent = 'Download';
  download.disabled = true;
  document.querySelector('.toolbar-actions').appendChild(download);
  download.addEventListener('click', () => {
    if (!originalImage) return;
    const exportCanvas = document.createElement('canvas');
    const maxSide = 4800;
    const scale = Math.min(1, maxSide / Math.max(originalImage.naturalWidth, originalImage.naturalHeight));
    exportCanvas.width = Math.round(originalImage.naturalWidth * scale);
    exportCanvas.height = Math.round(originalImage.naturalHeight * scale);
    const exportCtx = exportCanvas.getContext('2d', { willReadFrequently: true });
    exportCtx.drawImage(originalImage, 0, 0, exportCanvas.width, exportCanvas.height);
    const src = exportCtx.getImageData(0, 0, exportCanvas.width, exportCanvas.height);
    const data = src.data;
    const base = data.slice();
    const exportWidth = exportCanvas.width, exportHeight = exportCanvas.height;
    const clarity = value('clarity') / 100;
    const exposure = Math.pow(2, value('exposure') / 100);
    const contrast = contrastFactor(value('contrast'));
    const saturation = 1 + value('saturation') / 100, warmth = value('warmth') * .42;
    for (let y = 0; y < exportHeight; y++) for (let x = 0; x < exportWidth; x++) {
      const i = (y * exportWidth + x) * 4;
      let r = base[i], g = base[i + 1], b = base[i + 2];
      if (clarity > 0) {
        const left = (y * exportWidth + Math.max(0, x - 1)) * 4;
        const right = (y * exportWidth + Math.min(exportWidth - 1, x + 1)) * 4;
        const up = (Math.max(0, y - 1) * exportWidth + x) * 4;
        const down = (Math.min(exportHeight - 1, y + 1) * exportWidth + x) * 4;
        const amount = clarity * .55;
        r += (r - (base[left] + base[right] + base[up] + base[down]) / 4) * amount;
        g += (g - (base[left + 1] + base[right + 1] + base[up + 1] + base[down + 1]) / 4) * amount;
        b += (b - (base[left + 2] + base[right + 2] + base[up + 2] + base[down + 2]) / 4) * amount;
      }
      r = (r * exposure - 128) * contrast + 128 + warmth;
      g = (g * exposure - 128) * contrast + 128;
      b = (b * exposure - 128) * contrast + 128 - warmth;
      const l = .2126 * r + .7152 * g + .0722 * b;
      data[i] = clamp(l + (r - l) * saturation);
      data[i + 1] = clamp(l + (g - l) * saturation);
      data[i + 2] = clamp(l + (b - l) * saturation);
    }
    exportCtx.putImageData(src, 0, 0);
    exportCanvas.toBlob((blob) => {
      if (!blob) { showToast('Could not export this image.'); return; }
      const link = document.createElement('a');
      link.href = URL.createObjectURL(blob);
      link.download = `${(document.getElementById('fileName').textContent.replace(/\.[^.]+$/, '') || 'foto')}-enhanced.jpg`;
      link.click();
      URL.revokeObjectURL(link.href);
    }, 'image/jpeg', .94);
  });
})();
