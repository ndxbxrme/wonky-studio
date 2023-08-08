import { drawWaveform } from "./draw-waveform.js";
import { bufferToWave } from "./buffer-to-wave.js";
class WaveformEditor {
  id = Math.floor(Math.random * 99999999999999).toString(36);
  audioBuffer;
  canvas;
  context;
  zoom = 1;
  offset = 0;
  playing = false;
  gain;
  source;
  duration = 0;
  audioCtx;
  startTime = 0;
  cursor;
  cursorPosition = 0;
  dragging = false;
  selecting = false;
  dragStart = 0;
  selectionFrom;
  selectionTo;
  selectionStart;
  throttleActive;
  constructor(appendTo, audioBuffer, audioCtx, disabled, timeRanges=[], zoom=1, offset=0) {
    this.mouseoutHandler = this.mouseout.bind(this);
    this.mouseupHandler = this.mouseup.bind(this);
    this.mousemoveHandler = this.mousemove.bind(this);
    this.mousewheelHandler = this.mousewheel.bind(this);
    this.keydownHandler = this.keydown.bind(this);
    this.scrollbarHandler = this.scrollbarOnScroll.bind(this);
    const html = `<div id="w${this.id}" class="waveform-editor">
      <canvas class="waveform"></canvas>
      <div class="waveform-cursor"></div>
      <div class="waveform-selection"></div>
      <div class="scroll-container">
        <div class="scroll-content"></div>
      </div>
    </div>`;
    if(appendTo.className) {
      appendTo.innerHTML = html;
    }
    else {
      document.querySelector(appendTo).innerHTML = html;
    }
    this.timeRanges = timeRanges;
    this.audioBuffer = audioBuffer;
    this.duration = this.audioBuffer.duration;
    this.zoom = zoom;
    this.offset = offset;
    this.audioCtx = audioCtx;
    this.canvas = document.querySelector('#w' + this.id + ' canvas.waveform');
    this.scrollContainer = document.querySelector('#w' + this.id + ' .scroll-container');
    this.scrollContent = document.querySelector('#w' + this.id + ' .scroll-content');
    this.canvas.width = this.canvas.offsetWidth;
    this.canvas.height = this.canvas.offsetHeight;
    this.context = this.canvas.getContext('2d');
    this.gain = this.audioCtx.createGain();
    this.gain.gain.value = 0.8;
    this.gain.connect(this.audioCtx.destination);
    this.cursor = document.querySelector('#w' + this.id + ' .waveform-cursor');
    this.selection = document.querySelector('#w' + this.id + ' .waveform-selection');
    this.tick = this.tick.bind(this);
    this.drawAll();
    this.updateScrollbar();
    this.tick();
    if(!disabled) {
      this.canvas.addEventListener('mousedown', (event) => {
        event.preventDefault();
        if(event.button===1) {
          this.dragging = true;
          this.dragStart = event.offsetX;
        }
        if(event.button===0) {
          const time = this.screenPositionToTime(event.offsetX);
          const fromDiff = Math.abs(time - this.selectionFrom);
          const toDiff = Math.abs(time - this.selectionTo);
          if(fromDiff < 0.02) {
            this.selectionStart = this.selectionTo;
            this.selectionFrom = time;
          }
          else if(toDiff < 0.02) {
            this.selectionStart = this.selectionFrom;
            this.selectionTo = time;
          }
          else {
            this.selectionFrom = time;
            this.selectionTo = time;
            this.selectionStart = time;
          }
          if(!this.playing) {
            this.cursorPosition = this.selectionFrom;
          }
          this.selecting = true;
          this.drawAll();
        }
      });
      this.canvas.addEventListener('mouseout', this.mouseoutHandler);
      this.canvas.addEventListener('mouseup', this.mouseupHandler);
      this.canvas.addEventListener('mousemove', this.mousemoveHandler);
      this.canvas.addEventListener('mousewheel', this.mousewheelHandler);
      this.scrollContainer.addEventListener('scroll', this.scrollbarHandler);
      window.addEventListener('keydown', this.keydownHandler)
    }
  }
  destroy() {
    this.canvas.removeEventListener('mouseout', this.mouseoutHandler);
    this.canvas.removeEventListener('mouseup', this.mouseupHandler);
    this.canvas.removeEventListener('mousemove', this.mousemoveHandler);
    this.canvas.removeEventListener('mousewheel', this.mousewheelHandler);
    window.removeEventListener('keydown', this.keydownHandler);
    this.canvas.parentElement.removeChild(this.canvas);
  }
  updateScrollbar() {
    if(this.disableScroll) {
      this.disableScroll = false;
      return;
    }
    this.scrollContent.style.width = (100/this.zoom) + '%';
    this.scrollContainer.scrollLeft = ((this.offset/this.duration) * this.scrollContainer.scrollWidth);
  }
  scrollbarOnScroll(event) {
    const scrollContainer = event.currentTarget;
    this.offset = (scrollContainer.scrollLeft / scrollContainer.scrollWidth) * this.duration;
    this.drawAll();
  }
  throttle(func, delay) {
    if(!this.throttleActive) {
      this.throttleActive = true;
      setTimeout(() => {
        this.throttleActive = false;
        func();
      }, delay);
    }
  }
  mouseout(event) {
    this.dragging = false;
    this.selecting = false;
  }
  mouseup(event) {
    this.dragging = false;
    this.selecting = false;
  }
  mousemove(event) {
    this.disableScroll = true;
    if(this.dragging) {
      const pxMove = event.offsetX - this.dragStart;
      const pxPerSec = this.canvas.width / (this.duration * this.zoom);
      this.offset -= pxMove / pxPerSec;
      this.clampOffset();
      this.disableScroll = false;
      this.updateScrollbar();
      this.drawAll();
      this.dragStart = event.offsetX;
    }
    else if(this.selecting) {
      const time = this.screenPositionToTime(event.offsetX);
      if(time < this.selectionStart) {
        this.selectionFrom = time;
        this.selectionTo = this.selectionStart;
      }
      else {
        this.selectionTo = time;
        this.selectionFrom = this.selectionStart;
      }
      this.drawSelection();
    }
  }
  mousewheel(event) {
    event.preventDefault();
    const cursorTime = this.screenPositionToTime(event.offsetX);
    if(event.deltaY > 0) {
      this.zoom *= 1.1;
      this.zoom = Math.min(1, this.zoom);
    }
    if(event.deltaY < 0) {
      this.zoom *= 0.9;
    }
    const cursorTime2 = this.screenPositionToTime(event.offsetX);
    const cursorDiff = cursorTime2 - cursorTime;
    this.offset -= cursorDiff;
    this.clampOffset();
    this.updateScrollbar();
    this.drawAll();
  }
  zoomOut() {
    this.zoom *= 1.1;
    this.zoom = Math.min(1, this.zoom);
    this.clampOffset();
    this.updateScrollbar();
    this.drawAll();
  }
  zoomIn() {
    this.zoom *= 0.9;
    this.clampOffset();
    this.updateScrollbar();
    this.drawAll();
  }
  keydown(event) {
    switch(event.keyCode) {
      case 32:
        event.preventDefault();
        if(this.playing) {
          this.stop();
        }
        else {
          this.play()
        }
        break;
      case 46:
      case 8:
        if(this.selectionTo && (this.selectionTo !== this.selectionFrom)) {
          event.preventDefault();
          if(this.playing) this.stop();
          let end = Math.floor((this.selectionTo > this.duration - (this.duration / 150) ? this.audioBuffer.length : this.selectionTo * this.audioCtx.sampleRate));
          let start = Math.floor((this.selectionFrom < (this.duration / 150) ? 0 : this.selectionFrom) * this.audioCtx.sampleRate);
          let data = new Float32Array(this.audioBuffer.length);
          this.audioBuffer.copyFromChannel(data, 0);
          const startArr = data.slice(0, start);
          const endArr = data.slice(end, data.length);
          const newArr = new Float32Array(startArr.length + endArr.length);
          newArr.set(startArr, 0);
          newArr.set(endArr, startArr.length);
          this.audioBuffer = this.audioCtx.createBuffer(1, newArr.length, this.audioCtx.sampleRate);
          this.audioBuffer.copyToChannel(newArr, 0);
          this.duration = this.audioBuffer.duration;
          this.selectionFrom = 0;
          this.selectionTo = 0;
          this.cursorPosition = 0;
          this.drawAll();
          this.updateScrollbar();
          this.tick();
        }
        break;
    }
  }
  tick() {
    window.requestAnimationFrame(this.tick);
    if(this.playing) {
      this.cursorPosition = this.audioCtx.currentTime - this.startTime + (this.selectionFrom || 0);
      if((this.selectionTo && (this.cursorPosition > this.selectionTo)) || this.cursorPosition > this.audioBuffer.duration) {
        this.playing = false;
      }
    }
    this.drawCursor();
  }
  clampOffset() {
    this.offset = Math.max(0, this.offset);
    if(this.offset + this.duration * this.zoom > this.duration) {
      this.offset = this.duration - (this.duration * this.zoom);
    }
  }
  drawAll() {
    this.throttle(() => {
      this.disableScroll = true;
      drawWaveform(this.audioBuffer, this.canvas, this.context, this.offset, this.offset + this.duration * this.zoom, this.timeRanges);
      this.drawTranscript();
      this.drawSelection();
      this.drawCursor();
    }, 100);
  }
  drawSelection() {
    const startPos = this.timeToScreenPosition(this.selectionFrom || 0);
    const endPos = this.timeToScreenPosition(this.selectionTo || this.selectionFrom || 0);
    const width = endPos - startPos;
    this.selection.style.left = Math.floor(startPos) + 'px';
    this.selection.style.width = Math.floor(width) + 'px';
  }
  drawCursor() {
    const screenPos = this.timeToScreenPosition(this.cursorPosition);
    this.cursor.style.left = Math.floor(screenPos) + 'px';
  }
  setSelection(from, to) {
    this.selectionFrom = from;
    this.selectionTo = to;
    this.zoomToSelection();
  }
  zoomToSelection() {
    let selectionLength = this.selectionTo - this.selectionFrom;
    let zoomLength = selectionLength * 1.2;
    let startOffset = (zoomLength - selectionLength) / 2;
    this.offset = this.selectionFrom - startOffset;
    this.zoom = zoomLength / this.audioBuffer.duration;
    this.updateScrollbar();
    this.drawAll();
  }
  timeToScreenPosition(time) {
    const pos = time;
    const startPos = this.offset;
    const endPos = (this.offset + this.duration * this.zoom);
    const screenPos = (pos - startPos) / (endPos - startPos);
    return screenPos * this.canvas.width;
  }
  screenPositionToTime(screenPos) {
    screenPos /= this.canvas.width;
    const startPos = this.offset;
    const endPos = (this.offset + this.duration * this.zoom);
    const time = screenPos * (endPos - startPos) + startPos;
    return time;
  }
  setTranscript(transcript) {
    //this.transcript = transcript.segments.reduce((res, segment) => [...res, ...segment.words], []);
    this.transcript = transcript;
    this.drawAll();  
  }
  getSelectionTranscript() {
    let selectionTranscript = '';
    if(this.transcript) {
      const from = this.selectionFrom || 0;
      const to = this.selectionTo || this.duration;
      selectionTranscript = this.transcript.filter(word => word.start >= from && word.start < to).map(word => ({
        text: word.text,
        start: word.start - from,
        end: word.end - from
      })).join(' ');
    }
    return selectionTranscript;
  }
  getSuggestedName() {
    let selectionTranscript = '';
    if(this.transcript) {
      const from = this.selectionFrom || 0;
      const to = this.selectionTo || this.duration;
      selectionTranscript = this.transcript.filter(word => word.start >= from && word.start < to).filter((word, i) => i < 3).map(word => word.text).join(' ');
    }
    //return sanitizeProjectName(selectionTranscript);
  }
  drawTranscript() {
    return;
    if(this.transcript) {
      const start = this.offset;
      const end = (this.offset + this.duration * this.zoom);
      const startPos = start / this.duration;
      const endPos = end / this.duration;
      this.context.font = '12px sans-serif';
      this.context.fillStyle = 'white';
      this.transcript.forEach(word => {
        if(word.start >= start && word.start < end) {
          const pos = word.start;
          const screenPos = (pos - start) / (end - start);
          this.context.fillText(word.text, screenPos * this.canvas.width, this.canvas.height - 14);
        }
      })
    }
  }
  play() {
    if(this.source) this.source.stop();
    this.source = this.audioCtx.createBufferSource();
    this.source.buffer = this.audioBuffer;
    this.source.connect(this.gain);
    this.startTime = this.audioCtx.currentTime;
    this.playing = true;
    if(this.selectionFrom && this.selectionTo) {
      if(this.selectionFrom > this.selectionTo) {
        this.selectionFrom = this.selectionTo;
      }
      if(this.selectionFrom === this.selectionTo) {
        this.selectionTo = this.duration;
        this.source.start(this.startTime, this.selectionFrom);
      }
      else {
        this.source.start(this.startTime, this.selectionFrom, this.selectionTo - this.selectionFrom);
      }
    }
    else {
      this.source.start(this.startTime);
    }
  }
  stop() {
    this.playing = false;
    this.source.stop();
  }
  extract(channel) {
    let start = 0;
    let stop = Math.floor(this.duration * this.audioCtx.sampleRate);
    if(this.selectionFrom && this.selectionTo && this.selectionFrom < this.selectionTo) {
      start = Math.floor(this.selectionFrom * this.audioCtx.sampleRate);
      stop = Math.floor(this.selectionTo * this.audioCtx.sampleRate);
    }
    const arrs = [];
    let c = 0;
    const data = new Float32Array(this.audioBuffer.length);
    while(c < this.audioBuffer.numberOfChannels) {
      if(typeof(channel)==='number' && c !== channel) {
        c++;
        continue;
      }
      const arr = new Float32Array(stop - start);
      this.audioBuffer.copyFromChannel(data, c);
      let i = start;
      while(i < stop) {
        arr[i - start] = data[i];
        i++;
      }
      arrs.push(arr);
      c++;
    }
    const newBuffer = this.audioCtx.createBuffer(arrs.length, arrs[0].length, this.audioCtx.sampleRate);
    for(let i=0; i<arrs.length; i++) {
      newBuffer.copyToChannel(arrs[i], i);
    }
    const filename = Math.floor(Math.random() * 99999999999999999).toString(36) + '.wav';
    const folder = 'extracted_audio';
    const transcript = this.getSelectionTranscript();
    const name = this.getSuggestedName();
    const blob = bufferToWave(newBuffer);
    const fileReader = new FileReader();
    fileReader.onload = () => {
      const arrayBuffer = fileReader.result;
      const wave = new Uint8Array(arrayBuffer);
      myAPI.saveWave(wave, filename, 'extracted_audio');
    }
    fileReader.readAsArrayBuffer(blob);
    return {filename,folder,transcript,name,start,stop};
  }
  getSelection() {
    return [this.selectionFrom, this.selectionTo];
  }
  getWav() {
    return bufferToWave(this.audioBuffer);
  }
}
export {WaveformEditor};