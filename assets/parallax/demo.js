'use strict';
(() => {
  const player = document.getElementById('demo-player');
  if (!player) return;

  const playButton = document.getElementById('demo-play');
  const playLabel = document.getElementById('demo-play-label');
  const playIcon = document.getElementById('demo-play-icon');
  const pauseIcon = document.getElementById('demo-pause-icon');
  const bypassButton = document.getElementById('demo-bypass');
  const enabledButton = document.getElementById('demo-enabled');
  const status = document.getElementById('demo-status');
  const state = document.getElementById('demo-state');
  const seek = document.getElementById('demo-seek');
  const elapsed = document.getElementById('demo-elapsed');
  const total = document.getElementById('demo-duration');
  const canvas = document.getElementById('demo-waveform');
  const pen = canvas.getContext('2d');
  const motionQuery = window.matchMedia('(prefers-reduced-motion: reduce)');
  const files = {
    bypass: '/assets/parallax/audio/vocal-delay-bypass-v1.mp3',
    enabled: '/assets/parallax/audio/vocal-delay-enabled-v1.mp3',
  };
  const Context = window.AudioContext || window.webkitAudioContext;
  // macOS Safari can keep a running Web Audio clock after its output goes
  // silent. Use its native media output; iOS keeps its working Web Audio path.
  const ios = /iPad|iPhone|iPod/.test(navigator.userAgent) ||
    (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
  const desktopSafari = /Safari\//.test(navigator.userAgent) &&
    !/Chrome|Chromium|CriOS|FxiOS|Edg|OPR|Android/.test(navigator.userAgent) && !ios;
  const media = desktopSafari ? Object.fromEntries(Object.entries(files).map(([key, url]) => {
    const audio = document.createElement('audio');
    audio.preload = 'auto'; audio.loop = true; audio.playsInline = true; audio.hidden = true;
    audio.src = url; audio.volume = key === 'bypass' ? 1 : 0;
    audio.dataset.demoMode = key;
    player.append(audio);
    return [key, audio];
  })) : null;
  let fadeFrame;
  let context;
  let buffers;
  let channels = [];
  let mode = 'bypass';
  let playing = false;
  let loading = false;
  let offset = 0;
  let startedAt = 0;
  let duration = 14.769252;
  let peaks;
  let frame;
  let lastDraw = 0;
  let lastSecond = -1;

  const clock = seconds => `${Math.floor(seconds / 60)}:${String(Math.floor(seconds % 60)).padStart(2, '0')}`;
  const position = () => playing ? media ? media[mode].currentTime % duration :
    (offset + Math.max(0, context.currentTime - startedAt)) % duration : offset;

  function setAudioSessionType(type) {
    // iOS otherwise treats Web Audio as ambient sound, which Silent Mode mutes
    // even while the context clock and the visible playhead keep advancing.
    try {
      if (navigator.audioSession) navigator.audioSession.type = type;
    } catch {
      // Audio Session is optional; unsupported browsers keep normal playback.
    }
  }

  function draw() {
    if (!pen) return;
    const width = canvas.clientWidth;
    const height = canvas.clientHeight;
    const ratio = Math.min(window.devicePixelRatio || 1, 2);
    if (canvas.width !== Math.round(width * ratio) || canvas.height !== Math.round(height * ratio)) {
      canvas.width = Math.round(width * ratio);
      canvas.height = Math.round(height * ratio);
    }
    pen.setTransform(ratio, 0, 0, ratio, 0, 0);
    pen.clearRect(0, 0, width, height);
    pen.lineWidth = 1;
    pen.strokeStyle = '#26313a';
    pen.beginPath();
    for (let x = 1; x < 4; x++) {
      pen.moveTo(width * x / 4, 0);
      pen.lineTo(width * x / 4, height);
    }
    for (let y = 1; y < 4; y++) {
      pen.moveTo(0, height * y / 4);
      pen.lineTo(width, height * y / 4);
    }
    pen.stroke();

    const progress = position() / duration;
    const values = peaks && peaks[mode];
    const color = mode === 'enabled' ? '#76dece' : '#c2ccd1';
    const left = 10;
    const area = width - left * 2;
    if (values) {
      const step = area / values.length;
      values.forEach((value, index) => {
        const bar = Math.max(1, value * (height - 28));
        pen.globalAlpha = index / values.length <= progress ? 1 : .43;
        pen.fillStyle = color;
        pen.fillRect(left + index * step, (height - bar) / 2, Math.max(1, step * .65), bar);
      });
    }
    pen.globalAlpha = 1;
    pen.fillStyle = color;
    pen.fillRect(left + progress * area, 8, 1, height - 16);
    const seconds = position();
    seek.value = String(progress * 100);
    if (Math.floor(seconds) !== lastSecond) {
      elapsed.textContent = clock(seconds);
      seek.setAttribute('aria-valuetext', `${Math.floor(seconds)} of ${Math.round(duration)} seconds`);
      lastSecond = Math.floor(seconds);
    }
  }

  function animate(timestamp) {
    if (!playing) return;
    if (timestamp - lastDraw > (motionQuery.matches ? 100 : 33)) {
      draw();
      lastDraw = timestamp;
    }
    frame = requestAnimationFrame(animate);
  }

  function updatePlayButton() {
    playButton.disabled = loading;
    playButton.setAttribute('aria-busy', String(loading));
    playButton.setAttribute('aria-label', loading ? 'Loading vocal delay demo' : playing ? 'Pause vocal delay demo' : 'Play vocal delay demo');
    playLabel.textContent = loading ? 'Loading…' : playing ? 'Pause' : 'Play demo';
    playIcon.hidden = playing || loading;
    pauseIcon.hidden = !playing || loading;
  }

  function stopSources() {
    cancelAnimationFrame(fadeFrame);
    if (media) Object.values(media).forEach(audio => audio.pause());
    channels.forEach(({ source, gain }) => {
      source.stop();
      source.disconnect();
      gain.disconnect();
    });
    channels = [];
  }

  function startSources() {
    const start = context.currentTime + .025;
    // Both versions share a clock, offset and loop boundary. Switching changes
    // gains only, so the phrase continues from the same sample in either mode.
    channels = ['bypass', 'enabled'].map(key => {
      const source = context.createBufferSource();
      const gain = context.createGain();
      source.buffer = buffers[key];
      source.loop = true;
      source.loopEnd = duration;
      gain.gain.value = key === mode ? 1 : 0;
      source.connect(gain);
      gain.connect(context.destination);
      source.start(start, offset);
      return { key, source, gain };
    });
    startedAt = start;
  }

  function pause() {
    if (!playing) return;
    offset = position();
    playing = false;
    cancelAnimationFrame(frame);
    stopSources();
    setAudioSessionType('auto');
    updatePlayButton();
    draw();
  }

  async function fetchFile(url) {
    const response = await fetch(url, { signal: AbortSignal.timeout(30000) });
    if (!response.ok) throw new Error('Audio unavailable');
    return response.arrayBuffer();
  }

  function fadeMedia() {
    cancelAnimationFrame(fadeFrame);
    const start = performance.now();
    const levels = Object.fromEntries(Object.entries(media).map(([key, audio]) => [key, audio.volume]));
    function step(timestamp) {
      const progress = Math.min(1, (timestamp - start) / 25);
      Object.entries(media).forEach(([key, audio]) => {
        audio.volume = levels[key] + ((key === mode ? 1 : 0) - levels[key]) * progress;
      });
      if (progress < 1) fadeFrame = requestAnimationFrame(step);
    }
    fadeFrame = requestAnimationFrame(step);
  }

  async function startMedia() {
    // Start both during the click, before awaiting metadata or network I/O.
    // Each element keeps its user-gesture permission for subsequent comparisons.
    const pending = Object.entries(media).map(([key, audio]) => {
      if (audio.readyState >= 1) audio.currentTime = offset;
      else audio.addEventListener('loadedmetadata', () => { audio.currentTime = offset; }, {once: true});
      audio.volume = key === mode ? 1 : 0;
      return audio.play();
    });
    let timeout;
    try {
      await Promise.race([Promise.all(pending), new Promise((_, reject) => {
        timeout = setTimeout(() => reject(new Error('Audio unavailable')), 30000);
      })]);
    } finally { clearTimeout(timeout); }
    duration = Math.min(...Object.values(media).map(audio => audio.duration));
    if (!Number.isFinite(duration) || duration <= 0) throw new Error('Audio unavailable');
    const current = media[mode].currentTime % duration;
    Object.entries(media).forEach(([key, audio]) => { if (key !== mode) audio.currentTime = current; });
    total.textContent = clock(Math.ceil(duration));
    seek.disabled = false;
  }

  async function play() {
    if (loading) return;
    status.textContent = '';
    loading = true;
    updatePlayButton();
    try {
      if (!media && !Context) throw new Error('Audio unsupported');
      setAudioSessionType('playback');
      if (media) {
        await startMedia();
      } else {
        if (!context) {
          context = new Context();
          context.addEventListener('statechange', () => {
            if (context.state !== 'running') pause();
          });
        }
        // Resume during the click gesture, before waiting for audio downloads.
        await context.resume();
        if (!buffers) {
          const pairs = await Promise.all(Object.entries(files).map(async ([key, url]) => {
            const buffer = await context.decodeAudioData(await fetchFile(url));
            return [key, buffer];
          }));
          const decoded = Object.fromEntries(pairs);
          if (Math.abs(decoded.bypass.duration - decoded.enabled.duration) > .05) throw new Error('Audio not aligned');
          buffers = decoded;
          duration = Math.min(buffers.bypass.duration, buffers.enabled.duration);
          total.textContent = clock(Math.ceil(duration));
          seek.disabled = false;
        }
        if (context.state !== 'running') throw new Error('Audio suspended');
        startSources();
      }
      playing = true;
      lastDraw = 0;
      frame = requestAnimationFrame(animate);
    } catch {
      stopSources();
      playing = false;
      setAudioSessionType('auto');
      status.textContent = 'The demo couldn’t play. Check your connection and try again.';
    } finally {
      loading = false;
      updatePlayButton();
      draw();
    }
  }

  function selectMode(nextMode) {
    const current = position();
    if (media && playing && nextMode !== mode) media[nextMode].currentTime = current;
    mode = nextMode;
    player.dataset.mode = mode;
    bypassButton.setAttribute('aria-pressed', String(mode === 'bypass'));
    enabledButton.setAttribute('aria-pressed', String(mode === 'enabled'));
    state.textContent = mode === 'enabled' ? 'With Parallax' : 'Without Parallax';
    canvas.setAttribute('aria-label', `Waveform of the vocal delay ${mode === 'enabled' ? 'with' : 'without'} Parallax`);
    if (media) {
      if (playing) fadeMedia();
      else Object.entries(media).forEach(([key, audio]) => { audio.volume = key === mode ? 1 : 0; });
    }
    if (context) {
      const now = context.currentTime;
      channels.forEach(({ key, gain }) => {
        if (gain.gain.cancelAndHoldAtTime) gain.gain.cancelAndHoldAtTime(now);
        else {
          const current = gain.gain.value;
          gain.gain.cancelScheduledValues(now);
          gain.gain.setValueAtTime(current, now);
        }
        gain.gain.linearRampToValueAtTime(key === mode ? 1 : 0, now + .025);
      });
    }
    draw();
  }

  playButton.addEventListener('click', () => playing ? pause() : play());
  bypassButton.addEventListener('click', () => selectMode('bypass'));
  enabledButton.addEventListener('click', () => selectMode('enabled'));
  seek.addEventListener('input', () => {
    offset = Math.min(Number(seek.value) / 100 * duration, duration - .01);
    lastSecond = -1;
    if (playing) {
      if (media) Object.values(media).forEach(audio => { audio.currentTime = offset; });
      else { stopSources(); startSources(); }
    }
    draw();
  });
  if (media) Object.values(media).forEach(audio => {
    audio.addEventListener('pause', () => { if (playing) pause(); });
    audio.addEventListener('error', () => {
      if (playing) {
        pause();
        status.textContent = 'The demo couldn’t play. Check your connection and try again.';
      }
    });
  });
  window.addEventListener('pagehide', pause);
  if (window.ResizeObserver) new ResizeObserver(draw).observe(canvas);
  else window.addEventListener('resize', draw);

  if (!media && !Context) {
    playButton.disabled = true;
    playLabel.textContent = 'Audio unavailable';
    status.textContent = 'Try a newer browser to hear the audio demo.';
  }
  fetch('/assets/parallax/audio/vocal-delay-peaks-v1.json')
    .then(response => response.ok ? response.json() : Promise.reject())
    .then(data => {
      peaks = data;
      if (!buffers) duration = data.duration;
      total.textContent = clock(Math.ceil(duration));
      draw();
    })
    .catch(() => draw());
  draw();
})();
