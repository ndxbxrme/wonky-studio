import { WaveformEditor } from "./waveform-editor.js";
class App {
  language = 'en';
  audioSources = {};
  phraseAudioSources = [];
  constructor() {
    this.init();
  }
  async init() {
    console.log(document.location.hash);
    this.audioCtx = this.audioCtx || new AudioContext();
    this.script = await this.loadData('script-processed-wav');
    this.game = await this.loadData('game');
    this.script.forEach((line, l) => {
      line.index = l;
      line.occurrences.forEach(occ => {
        if (occ.text.endsWith(',.')) {
          occ.text = occ.text.replace(/,\.$/, '.');
        }
        occ.text = occ.text[0].toUpperCase() + occ.text.slice(1);
      })
    });
    this.words = await this.loadData('words');
    this.timeRanges = await this.loadData('time-ranges');
    this.sources = await this.loadSources();
    this.audioFiles = new Set();
    this.updateWordRanges();
    this.audioFiles = Array.from(this.audioFiles);
    this.loadState();
    this.wordRange = [];
    window.addEventListener('popstate', this.loadState.bind(this));
    document.addEventListener('keyup', this.keyup.bind(this));
    document.body.addEventListener('drop', async (event) => {
      event.preventDefault();
      let elm = event.target;
      while(elm && !elm.dataset.room) {
        elm = elm.parentElement;
      }
      let roomName, objectName, stateName;
      if(elm) {
        roomName = elm.dataset.room;
        objectName = elm.dataset.object;
        stateName = elm.dataset.state;
      }
      document.body.classList.remove('dragover');
      this.openFeedback();
      const files = event.dataTransfer.files;
      let id = null;
      let type = null;
      for (let f = 0; f < files.length; f++) {
        this.progressFeedback(f, files.length, 'Uploading');
        const file = files[f];
        await new Promise(res => {
          const reader = new FileReader();
          reader.onload = async () => {
            const base64Wav = reader.result.split(',')[1];
            const requestData = { data: base64Wav, name: file.name, language: this.language, id: id };
            const response = await fetch('/upload', {
              method: 'POST',
              headers: {
                'Content-Type': 'application/json',
              },
              body: JSON.stringify(requestData),
            });

            // Handle the response from the API, if needed
            const data = await response.json();
            id = data.id;
            type = data.type;
            res();
          }
          reader.readAsDataURL(file)
        });
      }
      this.closeFeedback();
      this.openUploadDetails(id, type, roomName, objectName, stateName);
    });
    document.body.addEventListener('dragover', (event) => {
      event.preventDefault();
      document.body.classList.add('dragover');
    });
    document.body.addEventListener('dragleave', (event) => {
      event.preventDefault();
      document.body.classList.remove('dragover');
    });
  }
  loadState = () => {
    const hash = document.location.hash.replace('#', '');
    const [state, name] = hash.split(/\//g);
    this.renderState(state || 'script', name);
  }
  openFeedback = () => {
    const uploadFeedback = document.querySelector('.upload-feedback-modal');
    const uploadFeedbackBg = document.querySelector('.upload-feedback-bg');
    const progressBar = uploadFeedback.querySelector('.progress-bar');
    const feedbackText = uploadFeedback.querySelector('.feedback-text');
    feedbackText.innerHTML = '';
    progressBar.style.width = '0%';
    uploadFeedbackBg.classList.remove('hidden');
    uploadFeedback.classList.remove('hidden');
  }
  progressFeedback = (f, length, action) => {
    const uploadFeedback = document.querySelector('.upload-feedback-modal');
    const progressBar = uploadFeedback.querySelector('.progress-bar');
    const feedbackText = uploadFeedback.querySelector('.feedback-text');
    progressBar.style.width = (((f + 1) / length) * 100) + '%';
    feedbackText.innerHTML = `${action} ${f + 1} of ${length}`;
  }
  closeFeedback = () => {
    const uploadFeedback = document.querySelector('.upload-feedback-modal');
    const uploadFeedbackBg = document.querySelector('.upload-feedback-bg');
    const progressBar = uploadFeedback.querySelector('.progress-bar');
    progressBar.style.width = '0%';
    uploadFeedbackBg.classList.add('hidden');
    uploadFeedback.classList.add('hidden');
  }
  async loadData(filename) {
    const res = await fetch(`./rendered/data/${this.language}/${filename}.json`);
    const json = await res.json();
    return json;
  }
  async loadSources() {
    const res = await fetch(`./sources/sources.json`);
    const json = await res.json();
    return json;
  }
  async loadAudioSources() {
    /*
    const response = await fetch('/get-audio-sources', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        language: this.language
      })
    });
    const filePaths = await response.json();
    this.audioSources = {};
    await Promise.all(filePaths.map(path => {
      return new Promise(async resolve => {
        const res = await fetch(path.replace('#', '%23'));
        const decoded = await this.audioCtx.decodeAudioData(await res.arrayBuffer());
        this.audioSources[path.match(/([^\\^\/]*)\.ogg/)[1]] = decoded;
        resolve();
      });
    }));*/
  }
  async loadAudioSource(name) {
    this.audioCtx = this.audioCtx || new AudioContext();
    await new Promise(async resolve => {
      const res = await fetch(`sources/audio/${this.language}/${name.replace('#', '%23')}.ogg`);
      const decoded = await this.audioCtx.decodeAudioData(await res.arrayBuffer());
      this.audioSources[name] = decoded;
      resolve();
    })
  }
  openNewThing(name, list, factory) {
    document.querySelector('.new-thing-bg').classList.remove('hidden');
    document.querySelector('.new-thing-modal').classList.remove('hidden');
    document.querySelector('.new-thing-modal h3').innerText = `New ${name}`;
    document.querySelector('.new-thing-modal input[type=text]').value = '';
    this.newThingOk = () => {
      const newThingName = document.querySelector('.new-thing-modal input[type=text]').value.trim();
      if (newThingName) {
        const oldThing = list.find(thing => thing.name === newThingName);
        if (!oldThing) {
          list.push(factory(newThingName));
          this.refreshUploadSelects();
          document.querySelector(`.upload-${name} select`).value = newThingName;
          this.refreshUploadSelects();
        }
      }
      document.querySelector('.new-thing-bg').classList.add('hidden');
      document.querySelector('.new-thing-modal').classList.add('hidden');
    }
    this.newThingCancel = () => {
      document.querySelector('.new-thing-bg').classList.add('hidden');
      document.querySelector('.new-thing-modal').classList.add('hidden');
    }
  }
  refreshUploadSelects() {
    const uploadDetailsModal = document.querySelector('.upload-details-modal');
    const selectedRoomName = uploadDetailsModal.querySelector('.upload-room select').value;
    const selectedObjectName = (uploadDetailsModal.querySelector('.upload-object select') || {}).value;
    const selectedStateName = (uploadDetailsModal.querySelector('.upload-state select') || {}).value;
    const selectedRoom = this.game.rooms.find(room => room.name === selectedRoomName);
    const selectedObject = selectedRoom && selectedRoom.objects.find(object => object.name === selectedObjectName);
    const selectedState = selectedObject && selectedObject.states.find(state => state.name === selectedStateName);
    uploadDetailsModal.querySelector('.upload-room select').innerHTML = `<option>---</option>` + this.game.rooms.map(room => `<option>${room.name}</option>`);
    uploadDetailsModal.querySelector('.upload-object select').innerHTML = `<option>---</option>` + (selectedRoom || { objects: [] }).objects.map(object => `<option>${object.name}</option>`).join('');
    uploadDetailsModal.querySelector('.upload-state select').innerHTML = `<option>---</option>` + (selectedObject || { states: [] }).states.map(state => `<option>${state.name}</option>`).join('');
    uploadDetailsModal.querySelector('.upload-room select').value = selectedRoomName;
    uploadDetailsModal.querySelector('.upload-object select').value = selectedObjectName;
    uploadDetailsModal.querySelector('.upload-state select').value = selectedStateName;
    uploadDetailsModal.querySelector('.upload-object').classList[selectedRoom ? 'remove' : 'add']('hidden');
    uploadDetailsModal.querySelector('.upload-state').classList[selectedObject ? 'remove' : 'add']('hidden');
    uploadDetailsModal.querySelector('.upload-object-existing').classList[selectedRoom ? 'remove' : 'add']('hidden');
    uploadDetailsModal.querySelector('.upload-state-existing').classList[selectedObject ? 'remove' : 'add']('hidden');
  }
  openUploadDetails(id, type, roomName, objectName, stateName, noImages) {
    const components = {};
    components.uploadDetailsBg = document.querySelector('.upload-details-bg');
    components.uploadDetailsModal = document.querySelector('.upload-details-modal');
    components.uploadNewRow = document.querySelector('.upload-new');
    components.uploadExistingRow = document.querySelector('.upload-existing');
    components.audioRow = document.querySelector('.upload-audio');
    components.imageRow = document.querySelector('.upload-image');
    components.roomExistingRow = document.querySelector('.upload-room-existing');
    components.objectExistingRow = document.querySelector('.upload-object-existing');
    components.stateExistingRow = document.querySelector('.upload-state-existing');
    Object.values(components).forEach(component => component.classList.add('hidden'));
    Array.from(components.uploadDetailsModal.querySelectorAll('input[type=text], select')).forEach(component => (component.value = null));
    [components.uploadDetailsBg, components.uploadDetailsModal, components.uploadNewRow, components.roomExistingRow].forEach(component => component.classList.remove('hidden'));
    components[type + 'Row'].classList.remove('hidden');
    this.refreshUploadSelects();
    if(roomName) {
      document.querySelector('.upload-room select').value = roomName;
      this.refreshUploadSelects();
      if(objectName) {
        document.querySelector('.upload-object select').value = objectName;
        this.refreshUploadSelects();
        if(stateName) {
          document.querySelector('.upload-state select').value = stateName;
          this.refreshUploadSelects();
        }
      }
    }
    if(type==='image') {
      document.querySelector('.upload-image select').value = (noImages && (noImages > 1)) ? 'Animation' : 'Static';
    }
    this.newRoom = () => {
      this.openNewThing('room', this.game.rooms, (name) => ({ name, objects: [] }));
    }
    this.newObject = () => {
      const selectedRoomName = document.querySelector('.upload-room select').value;
      const selectedRoom = this.game.rooms.find(room => room.name === selectedRoomName);
      if (selectedRoom) {
        this.openNewThing('object', selectedRoom.objects, (name) => ({ name, states: [] }));
      }
    }
    this.newState = () => {
      const selectedRoomName = document.querySelector('.upload-room select').value;
      const selectedRoom = this.game.rooms.find(room => room.name === selectedRoomName);
      if (selectedRoom) {
        const selectedObjectName = document.querySelector('.upload-object select').value;
        const selectedObject = selectedRoom.objects.find(object => object.name === selectedObjectName);
        if (selectedObject) {
          this.openNewThing('state', selectedObject.states, (name) => ({ name, sources: [] }));
        }
      }
    }
    this.saveUploadDetails = () => {
      const selectedRoomName = document.querySelector('.upload-room select').value;
      const selectedRoom = this.game.rooms.find(room => room.name === selectedRoomName);
      if (selectedRoom) {
        const selectedObjectName = document.querySelector('.upload-object select').value;
        const selectedObject = selectedRoom.objects.find(object => object.name === selectedObjectName);
        if (selectedObject) {
          const selectedStateName = document.querySelector('.upload-state select').value;
          const selectedState = selectedObject.states.find(state => state.name === selectedStateName);
          if (selectedState) {
            const selectedType = document.querySelector(`.upload-${type} select`).value;
            if (selectedType && (selectedType !== '---')) {
              selectedState.sources.push({
                type, id,
                subtype: selectedType
              });
              this.saveGame();
              components.uploadDetailsBg.classList.add('hidden');
              components.uploadDetailsModal.classList.add('hidden');
              if (type === 'image') {
                //open masking
                this.openMaskingModal(id);
              }
            }
          }
        }
      }
    }
    this.cancelUploadDetails = () => {

    }
  }
  async openMaskingModal(sourceId) {
    this.sources = await this.loadSources();
    const maskingBg = document.querySelector('.masking-bg');
    const maskingModal = document.querySelector('.masking-modal');
    maskingBg.classList.remove('hidden');
    maskingModal.classList.remove('hidden');
    const mySources = this.sources.filter(source => source.id === sourceId);
    const canvas = maskingModal.querySelector('canvas');
    const ctx = canvas.getContext('2d');
    const img = new Image();
    const maskImg = new Image();
    let dragging = false;
    let startPos = null;
    let index = 0;
    const draw = () => {
      const maskBox = mySources[index].maskBox;
      if (maskBox) {
        if (mySources[index].hasMask) {
          ctx.drawImage(maskImg, 0, 0, img.width, img.height);
          ctx.globalCompositeOperation = 'source-in';
          ctx.drawImage(img, 0, 0, img.width, img.height);
        }
        else {
          ctx.drawImage(img, 0, 0, img.width, img.height);
          ctx.fillStyle = 'black';
          ctx.globalCompositeOperation = 'xor';
          ctx.globalAlpha = 0.5;
          ctx.fillRect(maskBox.x, maskBox.y, maskBox.w, maskBox.h);
        }
        ctx.globalCompositeOperation = 'source-over';
        ctx.globalAlpha = 1.0;
      }
      else {
        ctx.drawImage(img, 0, 0, img.width, img.height);
      }
    }
    img.onload = () => {
      canvas.width = img.width;
      canvas.height = img.height;
      draw();
    }
    maskImg.onload = () => {
      draw();
    }
    this.maskingCanvasMouseDown = () => {
      event.preventDefault();
      const ratio = canvas.width / canvas.clientWidth;
      const [x, y] = [event.offsetX * ratio, event.offsetY * ratio];
      startPos = { x, y };
      if (!mySources[index].hasMask) {
        dragging = true;
      }
    }
    this.maskingCanvasMouseUp = () => {
      event.preventDefault();
      const ratio = canvas.width / canvas.clientWidth;
      const [x, y] = [event.offsetX * ratio, event.offsetY * ratio];
      dragging = false;
    }
    this.maskingCanvasMouseOut = () => {
      event.preventDefault();
      const ratio = canvas.width / canvas.clientWidth;
      const [x, y] = [event.offsetX * ratio, event.offsetY * ratio];
      dragging = false;
    }
    this.maskingCanvasMouseMove = () => {
      event.preventDefault();
      const ratio = canvas.width / canvas.clientWidth;
      const [x, y] = [event.offsetX * ratio, event.offsetY * ratio];
      const currentPos = { x, y };
      if (dragging) {
        const min = {
          x: Math.min(startPos.x, currentPos.x),
          y: Math.min(startPos.y, currentPos.y)
        }
        const max = {
          x: Math.max(startPos.x, currentPos.x),
          y: Math.max(startPos.y, currentPos.y)
        }
        mySources[index].maskBox = { x: min.x, y: min.y, w: max.x - min.x, h: max.y - min.y };
        draw();
      }
    }
    this.openMaskingImage = (index) => {
      img.src = `${mySources[index].path}/${mySources[index].filename}.png`;
      if (mySources[index].hasMask) {
        maskImg.src = `${mySources[index].path}/${mySources[index].filename}-mask.png?r=${Math.floor(Math.random() * 99999)}`;
      }
      mySources[index].maskBox = mySources[index].maskBox || {};
      const maskingLayers = document.querySelector('.masking-layers');
      maskingLayers.innerHTML = new Array(mySources[index].numMasks).fill(0).map((m, i) => `
        <input type="checkbox" />
      `);
    }
    this.prevMaskingImage = () => {
      if (index > 0) this.openMaskingImage(--index);
    }
    this.nextMaskingImage = () => {
      if (index < mySources.length - 1) this.openMaskingImage(++index);
    }
    this.segmentImage = async (index) => {
      const source = mySources[index];
      const mb = source.maskBox;
      const expand = +maskingModal.querySelector('input[name=expand]').value;
      const blur = +maskingModal.querySelector('input[name=blur]').value;
      const fillHoles = maskingModal.querySelector('input[name=fillHoles]').checked;
      const response = await fetch('/segment', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          imgPath: `${source.path}/${source.filename}.png`,
          maskBox: [mb.x, mb.y, mb.x + mb.w, mb.y + mb.h],
          expand, blur, fillHoles
        }),
      });
      const json = await response.json();
      if (json.message = 'OK') {
        source.hasMask = true;
        source.numMasks = json.numMasks;
      }
    }
    this.segmentAll = async () => {
      this.openFeedback();
      for (let f = 0; f < mySources.length; f++) {
        this.progressFeedback(f, mySources.length, 'Segmenting');
        await this.segmentImage(f);
      }
      this.closeFeedback();
      this.openMaskingImage(index);
    }
    this.saveMasking = async () => {
      const response = await fetch('/save-sources', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          sources: this.sources
        })
      });
      this.filterList && this.filterList();
      this.saveGame();
      this.closeModal();
    }
    this.copyMaskBoxToFollowing = () => {
      for(let l=index + 1; l<mySources.length; l++) {
        mySources[l].maskBox = JSON.parse(JSON.stringify(mySources[index].maskBox));
      }
    }
    this.copyMaskBoxToPrevious = () => {
      for(let l=index - 1; l<-1; l--) {
        mySources[l].maskBox = JSON.parse(JSON.stringify(mySources[index].maskBox));
      }
    }
    this.clearMask = () => {
      mySources[index].maskBox = null;
      mySources[index].hasMask = null;
      this.openMaskingImage(image);
    }
    this.clearMaskAll = () => {
      for(let l=0; l<mySources.length; l++) {
        mySources[l].maskBox = null;
        mySources[l].hasMask = null;
      }
      this.openMaskingImage(image);
    }
    this.openMaskingImage(0);
  }
  updateWordRanges() {
    this.words.forEach((word, w) => {
      this.audioFiles.add(word.file);
      for (let i = 0; i < this.timeRanges.all.length; i++) {
        const range = this.timeRanges.all[i];
        if (w >= range[0] && w <= range[1]) {
          word.unused = true;
          break;
        }
        if (w < range[0]) {
          break;
        }
      }
    })
  }
  renderUnderConstruction(state) {
    const toolbar = document.querySelector('.toolbar');
    const body = document.querySelector('.body');
    toolbar.innerHTML = '';
    body.innerHTML = `<h2>${state}</h2><img src="images/under-construction90s-90s.gif" />`;
  }
  renderTranscript() {
    let index = 0;
    this.wordRange = [];
    const fileSelector = document.querySelector('.toolbar .audioFile');
    if (fileSelector) {
      index = fileSelector.selectedIndex;
    }
    const selectedFile = (fileSelector || {}).value || this.audioFiles[0];
    if (!this.audioSources[selectedFile]) this.loadAudioSource(selectedFile);
    const toolbar = document.querySelector('.toolbar');
    toolbar.innerHTML = `<select class="audioFile" onchange="app.renderTranscript()">` + this.audioFiles.map((audioFile, i) =>
      `<option${i === index ? ' selected' : ''}>${audioFile}</option>`
    ).join('') + `</select>`;
    toolbar.innerHTML += `<input type="button" class="assignButton" onclick="app.assignToLine()" value="Assign to line" disabled />`;
    toolbar.innerHTML += `<input type="button" class="playButton" onclick="app.playRange()" value="Play" disabled />`;
    toolbar.innerHTML += `<input type="button" class="stopButton" onclick="app.stopRange()" value="Stop" disabled />`;
    const lines = [];
    let line = '';
    this.words.forEach((word, w) => {
      if (word.file === this.audioFiles[index]) {
        line += `<span class="word ${!word.unused ? 'used' : ''}" onclick="app.wordClick(${w})" data-index="${w}">${word.text}</span> `;
        if (/[\.\?]$/.test(word.text)) {
          lines.push(line);
          line = '';
        }
      }
    })
    if (line) lines.push(line);
    const body = document.querySelector('.body');
    body.innerHTML = lines.map(line => `<div class="phrase">${line}</div>`).join('');
  }
  renderScript() {
    const toolbar = document.querySelector('.toolbar');
    toolbar.innerHTML = `
      <input type="text" placeholder="Search..." class="filterText" onkeyup="app.filterScript()" onchange="app.filterScript()" />
      <select class="foundSelect" onchange="app.filterScript()">
        <option>All</option>
        <option>Found</option>
        <option>Unfound</option>
        <option>Complete</option>
        <option>Incomplete</option>
      </select>
    `;
    const body = document.querySelector('.body');
    this.openScriptLine = async (index) => {
      const phrase = this.script[index];
      const modal = document.querySelector('.script-modal');
      const modalBg = document.querySelector('.script-modal-bg');
      let modalHtml = `<div class="modalToolbar"></div>
        <div class="modalScript"></div>
        <div class="controls"><input type="button" onclick="app.ok()" value="OK" /></div>
      `;
      modal.innerHTML = modalHtml;
      modal.classList.remove('hidden');
      modalBg.classList.remove('hidden');
      this.phraseAudioSources = await Promise.all(phrase.occurrences.map(occ => {
        return new Promise(async resolve => {
          const res = await fetch(occ.full_path.replace('.wav', '.ogg'));
          resolve(await this.audioCtx.decodeAudioData(await res.arrayBuffer()));
        })
      }))
      this.renderPhrase = () => {
        let html = `<h3>${phrase.line}</h3>`;
        html += phrase.occurrences.map((occ, o) => {
          return `<div class="occ">
            <div class="line" onclick="app.playOcc(${o}, this)">
              ${occ.text}
              <div class="pos" style="width: 0%"></div>
            </div>
            <div class="occ-controls">
              <select onchange="app.setOccStatus(${o}, this.value)">
                <option>---</option>
                <option ${occ.status === 'Good' ? 'selected' : ''}>Good</option>
                <option ${occ.status === 'Bad' ? 'selected' : ''}>Bad</option>
                <option ${occ.status === 'Edit' ? 'selected' : ''}>Edit</option>
              </select>
              <input type="button" onclick="app.editOcc(${o})" value="Edit" />
            </div>
          </div>
          `;
        }).join('');
        document.querySelector('.modalScript').innerHTML = html;
      }
      this.playOcc = (index, elm) => {
        const sourceNode = this.audioCtx.createBufferSource();
        sourceNode.buffer = this.phraseAudioSources[index];
        sourceNode.connect(this.audioCtx.destination);
        sourceNode.start();
        const startTime = this.audioCtx.currentTime;
        const endTime = startTime + sourceNode.buffer.duration;
        const pos = elm.querySelector('.pos');
        const tick = () => {
          const now = this.audioCtx.currentTime;
          if (now < endTime) {
            requestAnimationFrame(tick);
            const percent = ((now - startTime) / (endTime - startTime)) * 100;
            pos.style.width = percent + '%';
          }
          else {
            pos.style.width = '0%';
          }
        }
        tick();
      }
      this.editOcc = (index, elm) => {
        const modal = document.querySelector('.waveform-modal');
        const modalBg = document.querySelector('.waveform-bg');
        const subtitle = document.querySelector('.waveform-editor-subtitle input');
        subtitle.value = phrase.occurrences[index].text;
        modal.classList.remove('hidden');
        modalBg.classList.remove('hidden');
        this.editor = new WaveformEditor('.waveform-editor-container', this.phraseAudioSources[index], this.audioCtx, null, []);
        this.updateSubtitle = async (value) => {
          phrase.occurrences[index].text = value;
          const response = await fetch('/save-script', {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
            },
            body: JSON.stringify({ script: this.script, language: this.language }),
          });
          this.renderPhrase();
        }
        this.saveOccAudio = async () => {
          const occ = phrase.occurrences[index];
          occ.edited = true;
          const wavBlob = this.editor.getWav();
          const reader = new FileReader();
          reader.onload = async () => {
            const base64Wav = reader.result.split(',')[1];
            const requestData = { wavData: base64Wav, script: this.script, fullPath: occ.full_path, language: this.language };

            const response = await fetch('/save-waveform', {
              method: 'POST',
              headers: {
                'Content-Type': 'application/json',
              },
              body: JSON.stringify(requestData),
            });

            // Handle the response from the API, if needed
            const data = await response.json();
            this.editor.destroy();
            modal.classList.add('hidden');
            modalBg.classList.add('hidden');
          };
          reader.readAsDataURL(wavBlob);
          this.phraseAudioSources[index] = this.editor.audioBuffer;


        }
      }
      this.setOccStatus = async (index, value) => {
        const occ = phrase.occurrences[index];
        occ.status = value;
        const response = await fetch('/save-script', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({ script: this.script, language: this.language }),
        });
        this.filterScript()
      }
      this.renderPhrase();
    }
    this.filterScript = () => {
      const foundUnfound = document.querySelector('.foundSelect').value;
      const filterText = document.querySelector('.filterText').value;
      body.innerHTML = `<table>` + this.script.filter(phrase => {
        let truth = true;
        truth = truth && (!filterText || phrase.line.toLowerCase().includes(filterText.toLowerCase()));
        switch (foundUnfound) {
          case 'Found':
            truth = truth && !!phrase.occurrences.length;
            break;
          case "Unfound":
            truth = truth && !phrase.occurrences.length;
            break;
          case 'Complete':
            truth = truth && !!phrase.occurrences.filter(occ => occ.status).length;
            break;
          case "Incomplete":
            truth = truth && !phrase.occurrences.filter(occ => occ.status).length;
            break;
        }
        return truth;
      }).map(phrase => `
        <tr class="phrase ${phrase.occurrences.length ? '' : 'unfound'}" data-index="${phrase.index}" onclick="app.openScriptLine(${phrase.index})">
          <td class="line"><span>${('0000' + phrase.index).slice(-4)}</span> ${phrase.line}</td>
          <td class="good">${phrase.occurrences.filter(occ => occ.status === 'Good').length || ' '} <span>/ ${phrase.occurrences.length}</span></td>
          <td class="path">${phrase.path.join(' / ')}</td>
        </tr>
      `).join('') + `</table>`;
    }
    this.filterScript();
  }
  wordClick(index) {
    document.querySelectorAll('span.word.selected').forEach(elm => elm.classList.remove('selected'));
    if (index === this.wordRange[0]) {
      if (this.wordRange[0] === this.wordRange[1]) {
        this.wordRange = [];
      }
      else {
        this.wordRange = [index, index];
      }
    }
    else if (index < this.wordRange[0]) {
      this.wordRange[0] = index;
    }
    else if (index > this.wordRange[0]) {
      this.wordRange[1] = index;
    }
    else {
      this.wordRange = [index, index];
    }
    document.querySelectorAll('span.word').forEach((elm, i) => {
      if ((elm.dataset.index >= this.wordRange[0]) && (elm.dataset.index <= this.wordRange[1])) elm.classList.add('selected');
    });
    ['.assignButton', '.playButton', '.stopButton'].forEach(selector => {
      const elm = document.querySelector(selector);
      elm.disabled = !this.wordRange.length;
    });
  }
  renderRoomList() {
    const toolbar = document.querySelector('.toolbar');
    const body = document.querySelector('.body');
    toolbar.innerHTML = `
      <input type="text" placeholder="Search..." class="filterText" onkeyup="app.filterList()" onchange="app.filterList()" />
    `;
    this.filterList = () => {
      const filterText = document.querySelector('.filterText').value;
      body.innerHTML = `<div class="room-list-grid list-grid">` + this.game.rooms.filter(room => 
        !filterText || room.name.toLowerCase().includes(filterText.toLowerCase())
      ).map(room => {
        const background = room.objects.find(object => object.name.toLowerCase()==='background');
        let bgUrl = '';
        if(background) {
          const bgSource = this.sources.find(source => source.id === background.states[0].sources[0].id);
          if(bgSource) {
            bgUrl = `${bgSource.path}/${bgSource.filename}.png`;
          }
        }
        return `
          <div class="room-cell list-grid-cell" onclick="app.setState('rooms', '${room.name}')">
            <div class="room-name">${room.name}</div>
            <img src="${bgUrl}" />
          </div>
        `
      }).join('') + `</div>`;
    }
    this.filterList();
  }
  renderObjectList() {
    const toolbar = document.querySelector('.toolbar');
    const body = document.querySelector('.body');
    toolbar.innerHTML = `
      <input type="text" placeholder="Search..." class="filterText" onkeyup="app.filterList()" onchange="app.filterList()" />
    `;
    this.filterList = async () => {
      const filterText = (document.querySelector('.filterText').value || '').toLowerCase();
      const allObjects = [];
      for (const room of this.game.rooms) {
        for (const object of room.objects) {
          allObjects.push({ roomName: room.name, ...object });
        }
      }
      const results = await Promise.all(this.renderObjectCells(allObjects.filter(object => 
        !filterText || object.name.toLowerCase().includes(filterText) || object.roomName.toLowerCase().includes(filterText)
      )));
      body.innerHTML = `<div class="object-list-grid list-grid">` + results.join('') + `</div>`;
    }
    this.filterList();
  }
  async renderSourceImgUrl(source) {
    let imgUrl = '';
    if(source) {
      if(source.hasMask) {
        await new Promise(res => {
          const image = new Image();
          image.src = `${source.path}/${source.filename}.png`;
          image.onload = () => {
            const mask = new Image();
            mask.src = `${source.path}/${source.filename}-mask.png`;
            mask.onload = () => {
              const canvas = document.createElement('canvas');
              const context = canvas.getContext('2d');
              canvas.width = source.maskBox.w;
              canvas.height = source.maskBox.h;
              //context.globalCompositeOperation = 'multiply';
              context.drawImage(mask, -source.maskBox.x, -source.maskBox.y);
              context.globalCompositeOperation = 'source-in';
              context.drawImage(image, -source.maskBox.x, -source.maskBox.y);
              imgUrl = canvas.toDataURL();
              res();
            }
          }
        })
      }
      else {
        imgUrl = `${source.path}/${source.filename}.png`;
      }
    }
    return imgUrl;
  }
  renderObjectCells(list, roomName) {
    return list.map(async object => {
      console.log('i\'m cool', object);
      const source = this.sources.find(source => source.id === (object.states[0].sources[0] || {}).id);
      const imgUrl = await this.renderSourceImgUrl(source);
      return `
        <div class="object-cell list-grid-cell" onclick="app.setState('objects', '${object.name}-${roomName || object.roomName}')" data-room="${roomName || object.roomName}" data-object="${object.name}">
          <div class="object-name">${object.name} - ${roomName || object.roomName}</div>
          <center><img src="${imgUrl}" /></center>
        </div>
      `
    })
  }
  async renderRoomDetails(roomName) {
    console.log('rrd', roomName);
    const toolbar = document.querySelector('.toolbar');
    const body = document.querySelector('.body');
    body.dataset.room = roomName;
    body.dataset.object = null;
    body.dataset.state = null;
    toolbar.innerHTML = `
      <input type="text" placeholder="Search..." class="filterText" onkeyup="app.filterList()" onchange="app.filterList()" />
    `;
    const room = this.game.rooms.find(room => room.name === roomName);
    body.innerHTML = `<h1>ROOM: ${room.name}</h1><h3>Objects</h3>`;
    const results = await Promise.all(this.renderObjectCells(room.objects, room.name));
    body.innerHTML += `<div class="object-list-grid list-grid">` + results.join('') + `</div>`;
  }
  renderStateCells(list, objectName, roomName) {
    return list.map(async state => {
      const source = this.sources.find(source => source.id === (state.sources[0] || {}).id);
      const imgUrl = await this.renderSourceImgUrl(source);
      return `
        <div class="state-cell list-grid-cell" onclick="app.setState('states', '${state.name}-${objectName}-${roomName || object.roomName}')" data-room="${roomName}" data-object="${objectName}" data-state="${state.name}">
          <div class="state-name">${state.name}</div>
          <center><img src="${imgUrl}" /></center>
        </div>
      `
    })
  }
  async renderObjectDetails(objectName, roomName) {
    const toolbar = document.querySelector('.toolbar');
    const body = document.querySelector('.body');
    body.dataset.room = roomName;
    body.dataset.object = objectName;
    body.dataset.state = null;
    toolbar.innerHTML = `
      <input type="text" placeholder="Search..." class="filterText" onkeyup="app.filterList()" onchange="app.filterList()" />
    `;
    const room = this.game.rooms.find(room => room.name === roomName);
    const object = room.objects.find(object => object.name === objectName);
    body.innerHTML = `<h1>OBJECT: ${object.name} - ${room.name}</h1>`;
    const results = await Promise.all(this.renderStateCells(object.states, object.name, room.name));
    body.innerHTML += `<div class="state-list-grid list-grid">` + results.join('') + `</div>`;
  }
  renderSourceCells(list, stateName, objectName, roomName) {
    const allSources = [];
    list.forEach(item => {
      const sources = this.sources.filter(source => source.id === item.id);
      allSources.push(...sources);
    })
    return allSources.map(async source => {
      const imgUrl = await this.renderSourceImgUrl(source);
      return `
        <div class="source-cell list-grid-cell" data-room="${roomName}" data-object="${objectName}" data-state="${stateName}">
          <div class="source-name">${source.filename}</div>
          <center><img src="${imgUrl}" /></center>
        </div>
      `
    })
  }
  async renderStateDetails(stateName, objectName, roomName) {
    const toolbar = document.querySelector('.toolbar');
    const body = document.querySelector('.body');
    body.dataset.room = roomName;
    body.dataset.object = objectName;
    body.dataset.state = stateName;
    toolbar.innerHTML = `
      <input type="text" placeholder="Search..." class="filterText" onkeyup="app.filterList()" onchange="app.filterList()" />
    `;
    const room = this.game.rooms.find(room => room.name === roomName);
    const object = room.objects.find(object => object.name === objectName);
    const state = object.states.find(state => state.name === stateName);
    console.log(state.sources);
    body.innerHTML = `<h1>STATE: ${state.name} - ${object.name} - ${room.name}</h1>`;
    const results = await Promise.all(this.renderSourceCells(state.sources, state.name, room.name, object.name));
    body.innerHTML += `<div class="source-list-grid list-grid">` + results.join('') + `</div>`;
  }
  assignToLine() {
    const modal = document.querySelector('.script-modal');
    const modalBg = document.querySelector('.script-modal-bg');
    let modalHtml = `<div class="modalToolbar"><input type="text" onchange="app.filterScript(this.value)" onkeyup="app.filterScript(this.value)" /></div>`;
    modalHtml += `<div class="modalScript"></div>`;
    modalHtml += `<div class="controls"><input type="button" onclick="app.assign()" value="Assign" /></div>`;
    modal.innerHTML = modalHtml;
    modal.classList.remove('hidden');
    modalBg.classList.remove('hidden');
    this.filterScript = (filter) => {
      document.querySelector('.modalScript').innerHTML = this.script.filter(line => !filter || line.line.toLowerCase().includes(filter.toLowerCase())).map(line => {
        return `<div class="line ${line.occurrences.length ? 'used' : ''} ${line.index === this.selectedLine ? 'selected' : ''}" onclick="app.selectLine(${line.index})" data-index="${line.index}">${line.line}</div>`
      }).join('');
    }
    this.selectLine = (index) => {
      this.selectedLine = index;
      document.querySelectorAll('.line').forEach(elm => +elm.dataset.index === this.selectedLine ? elm.classList.add('selected') : elm.classList.remove('selected'))
    }
    this.assign = async () => {
      const response = await fetch('/assign-words-to-line', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          wordRange: this.wordRange,
          lineIndex: this.selectedLine,
          language: this.language
        })
      });
      const json = await response.json();
      this.script = json.script;
      this.timeRanges = json.timeRanges;
      modal.classList.add('hidden');
      modalBg.classList.add('hidden');
      this.updateWordRanges();
      this.renderTranscript();
      //add to line.occurrences
      //render ogg
      //update timeRanges
    }
    this.filterScript(null);
  }
  playRange() {
    const start = this.words[this.wordRange[0]].timestamp[0] / 22050;
    const end = this.words[this.wordRange[1]].timestamp[1] / 22050;
    const file = document.querySelector('.toolbar .audioFile').value;
    const sourceNode = this.audioCtx.createBufferSource();
    sourceNode.buffer = this.audioSources[file];
    sourceNode.connect(this.audioCtx.destination);
    sourceNode.start(0, start);
    sourceNode.stop(this.audioCtx.currentTime + (end - start));
  }
  stopRange() {

  }
  setState(state, name) {
    document.location.hash = state + (name ? `/${name}` : '');
  }
  async renderState(state, name) {
    const body = document.querySelector('.body');
    switch (state.toLowerCase()) {
      case 'script':
        this.renderScript();
        break;
      case 'transcript':
        this.renderTranscript();
        break;
      case 'music':
        this.renderUnderConstruction(state);
        break;
      case 'sfx':
        this.renderUnderConstruction(state);
        break;
      case 'animations':
        this.renderUnderConstruction(state);
        break;
      case 'rooms':
        if(name) {
          await this.renderRoomDetails(name);
        }
        else {
          await this.renderRoomList(state);
        }
        break;
      case 'objects':
        if(name) {
          const [objectName, roomName] = name.split('-');
          this.renderObjectDetails(objectName, roomName);
        }
        else {
          this.renderObjectList(state);
        }
        break;
      case 'states':
        if(name) {
          const [stateName, objectName, roomName] = name.split(/-/g);
          this.renderStateDetails(stateName, objectName, roomName);
        }
        break;
      case 'variables':
        this.renderUnderConstruction(state);
        break;
      case 'scripts':
        this.renderUnderConstruction(state);
        break;
    }

  }
  closeModal() {
    const topModal = Array.from(document.querySelectorAll('.modal:not(.hidden)')).slice(-1)[0];
    if (topModal) {
      if (topModal.classList.contains('block-esc')) return;
      const topModalBg = Array.from(document.querySelectorAll('.modal-bg:not(.hidden)')).slice(-1)[0];
      topModal.classList.add('hidden');
      topModalBg.classList.add('hidden')
      this.editor && this.editor.destroy();
    }
    else {
      this.wordRange[1] = this.wordRange[0];
      this.wordClick(this.wordRange[0]);
    }
  }
  async saveGame() {
    const response = await fetch('/save-game', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        game: this.game,
        language: 'en'
      }),
    });
  }
  ok() {
    this.closeModal();
  }
  keyup(event) {
    switch (event.keyCode) {
      case 27: //Escape
        this.closeModal();
        break;
    }
  }
}
window.app = new App();