const bufferToWave = (mybuffer) => {
  const noChan = mybuffer.numberOfChannels;
  const length = (mybuffer.length) * noChan * 2 + 44;
  const buffer = new ArrayBuffer(length);
  const view = new DataView(buffer);
  const channels = [];
  let offset = 0;
  let pos = 0;
  const setUint32 = (data) => {
    view.setUint32(pos, data, true);
    pos += 4;
  }
  const setUint16 = (data) => {
    view.setUint16(pos, data, true)
    pos += 2;
  }
  setUint32(0x46464952);
  setUint32(length - 8);
  setUint32(0x45564157);
  setUint32(0x20746d66);
  setUint32(16);
  setUint16(1);
  setUint16(noChan);
  setUint32(mybuffer.sampleRate);
  setUint32(mybuffer.sampleRate * 2 * noChan);
  setUint16(noChan * 2);
  setUint16(16);
  setUint32(0x61746164);
  setUint32(length - pos - 4);
  let i = 0;
  while(i < noChan) {
    channels.push(mybuffer.getChannelData(i));
    i++;
  }
  while(pos < length) {
    i = 0;
    while(i < noChan) {
      let sample = Math.max(-1, Math.min(1, channels[i][offset]));
      sample = (0.5 + sample < 0 ? sample * 32768 : sample * 32768) || 0;
      view.setInt16(pos, sample, true);
      pos += 2;
      i++;
    }
    offset++;
  }
  return new Blob([buffer], {type:'audio/wav'});
}
export {bufferToWave};