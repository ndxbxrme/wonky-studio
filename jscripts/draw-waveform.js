function drawWaveform(audioBuffer, canvas, ctx, start = 0, end = audioBuffer.duration, timeRanges = []) {
  const width = canvas.width;
  const height = canvas.height;
  const data = new Float32Array(audioBuffer.getChannelData(0));
  const step = Math.ceil((end - start) * audioBuffer.sampleRate / width);
  const startSmp = start * audioBuffer.sampleRate;
  const amp = height / 2;
  
  ctx.fillStyle = 'black';
  ctx.fillRect(0, 0, width, height);
  ctx.lineWidth = 1;
  ctx.strokeStyle = 'green';
  ctx.beginPath();
  
  for (let i = 0; i < width; i++) {
    let min = 1.0;
    let max = -1.0;
    const indexOffset = Math.floor(i * step);
    
    for (let j = 0; j < step; j++) {
      const index = Math.floor(startSmp + indexOffset + j);
      
      if (index >= 0 && index < data.length) {
        const datum = data[index];
        if (datum < min) {
          min = datum;
        }
        if (datum > max) {
          max = datum;
        }
      }
    }
    ctx.moveTo(i, (1 + min) * amp);
    ctx.lineTo(i, (1 + max) * amp);
  }
  ctx.moveTo(width, amp);
  ctx.lineTo(width, amp);
  ctx.stroke();

  // Highlight the waveform based on the time ranges
  ctx.fillStyle = 'rgba(255, 255, 255, 0.1)'; // Highlight color (red with 50% opacity)
  for (const [highlightStart, highlightEnd] of timeRanges) {
    const xStart = Math.floor((highlightStart - start) * width / (end - start));
    const xEnd = Math.ceil((highlightEnd - start) * width / (end - start));
    ctx.fillRect(xStart, 0, xEnd - xStart, height);
  }
}
export {drawWaveform};