(() => {
  const fileInput = document.getElementById('fileInput');
  const dropzone = document.getElementById('dropzone');
  const preview = document.getElementById('preview');
  const canvas = document.getElementById('photoCanvas');
  const ctx = canvas.getContext('2d', { willReadFrequently: true });
  const stage = document.getElementById('stageWrap');
  const controls = ['exposure', 'contrast', 'saturation', 'warmth', 'clarity', 'sharpness', 'denoise'];
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

  // Apply the same restrained pixel pipeline to the preview and full-size export.
  function enhancePixels(input, width, height) {
    const src = input.data;
    const out = new ImageData(width, height);
    const dst = out.data;
    const exposure = Math.pow(2, value('exposure') / 100);
    const contrast = contrastFactor(value('contrast'));
    const saturation = 1 + value('saturation') / 100;
    const warmth = value('warmth') * 0.42;
    const clarity = value('clarity') / 100;
    const sharpness = value('sharpness') / 100;
    const denoise = value('denoise') / 100;
    const detail = clarity * 0.28 + sharpness * 0.72;
    const mix = denoise * 0.42;
    const threshold = 10 + denoise * 54;

    for (let y = 0; y < height; y++) {
      for (let x = 0; x < width; x++) {
        const i = (y * width + x) * 4;
        let r = src[i], g = src[i + 1], b = src[i + 2];
        const left = (y * width + Math.max(0, x - 1)) * 4;
        const right = (y * width + Math.min(width - 1, x + 1)) * 4;
        const up = (Math.max(0, y - 1) * width + x) * 4;
        const down = (Math.min(height - 1, y + 1) * width + x) * 4;

        if (denoise > 0) {
          const centerLum = 0.2126 * r + 0.7152 * g + 0.0722 * b;
          let rr = 0, gg = 0, bb = 0, weightSum = 0;
          let nr = src[left], ng = src[left + 1], nb = src[left + 2];
          let delta = (0.2126 * nr + 0.7152 * ng + 0.0722 * nb - centerLum) / threshold;
          let weight = 1 / (1 + delta * delta);
          rr += nr * weight; gg += ng * weight; bb += nb * weight; weightSum += weight;
          nr = src[right]; ng = src[right + 1]; nb = src[right + 2];
          delta = (0.2126 * nr + 0.7152 * ng + 0.0722 * nb - centerLum) / threshold;
          weight = 1 / (1 + delta * delta);
          rr += nr * weight; gg += ng * weight; bb += nb * weight; weightSum += weight;
          nr = src[up]; ng = src[up + 1]; nb = src[up + 2];
          delta = (0.2126 * nr + 0.7152 * ng + 0.0722 * nb - centerLum) / threshold;
          weight = 1 / (1 + delta * delta);
          rr += nr * weight; gg += ng * weight; bb += nb * weight; weightSum += weight;
          nr = src[down]; ng = src[down + 1]; nb = src[down + 2];
          delta = (0.2126 * nr + 0.7152 * ng + 0.0722 * nb - centerLum) / threshold;
          weight = 1 / (1 + delta * delta);
          rr += nr * weight; gg += ng * weight; bb += nb * weight; weightSum += weight;
          r = r * (1 - mix) + (rr / weightSum) * mix;
          g = g * (1 - mix) + (gg / weightSum) * mix;
          b = b * (1 - mix) + (bb / weightSum) * mix;
        }
        if (detail > 0) {
          const amount = detail * 0.9;
          r += (src[i] - (src[left] + src[right] + src[up] + src[down]) / 4) * amount;
          g += (src[i + 1] - (src[left + 1] + src[right + 1] + src[up + 1] + src[down + 1]) / 4) * amount;
          b += (src[i + 2] - (src[left + 2] + src[right + 2] + src[up + 2] + src[down + 2]) / 4) * amount;
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
    }
    return out;
  }

  function render() {
    if (!originalPixels || !originalImage) return;
    ctx.putImageData(enhancePixels(originalPixels, originalPixels.width, originalPixels.height), 0, 0);
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
    const histogram = new Uint32Array(256);
    const pixelCount = data.length / 4;
    const pixelStep = Math.max(1, Math.floor(pixelCount / 24000));
    let samples = 0;
    for (let pixel = 0; pixel < pixelCount; pixel += pixelStep) {
      const i = pixel * 4;
      const luminance = Math.round(0.2126 * data[i] + 0.7152 * data[i + 1] + 0.0722 * data[i + 2]);
      histogram[luminance]++;
      samples++;
    }
    const percentile = (fraction) => {
      const target = samples * fraction;
      let accumulated = 0;
      for (let level = 0; level < histogram.length; level++) {
        accumulated += histogram[level];
        if (accumulated >= target) return level;
      }
      return 128;
    };
    const low = percentile(0.02), median = percentile(0.5), high = percentile(0.98);
    const exposure = Math.max(-35, Math.min(35, Math.round(Math.log2(128 / Math.max(1, median)) * 100)));
    const contrast = Math.max(-4, Math.min(18, Math.round((215 - (high - low)) * 0.18)));
    document.getElementById('exposure').value = exposure;
    document.getElementById('contrast').value = contrast;
    document.getElementById('saturation').value = 8;
    document.getElementById('warmth').value = 0;
    document.getElementById('clarity').value = 8;
    document.getElementById('sharpness').value = 10;
    document.getElementById('denoise').value = 6;
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
    exportCtx.fillStyle = '#fff';
    exportCtx.fillRect(0, 0, exportCanvas.width, exportCanvas.height);
    exportCtx.drawImage(originalImage, 0, 0, exportCanvas.width, exportCanvas.height);
    const sourcePixels = exportCtx.getImageData(0, 0, exportCanvas.width, exportCanvas.height);
    exportCtx.putImageData(enhancePixels(sourcePixels, exportCanvas.width, exportCanvas.height), 0, 0);
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
