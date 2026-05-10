import {apiFetch, scriptAudioCandidateUrl} from '../api.js';
import {user} from '../state/user.js';

const LANGUAGES = ['en', 'de', 'es', 'fr', 'it', 'pt'];

const ScriptReviewCtrl = app => async () => {
  const controller = {
    appName: 'Wonky Studio',
    user: user.current,
    isAdmin: user.isAdmin,
    languages: LANGUAGES.map(language => ({value: language, label: language.toUpperCase()})),
    query: '',
    path: '',
    language: 'en',
    translationStatus: '',
    audioStatus: '',
    audioSource: '',
    missingAudio: false,
    limit: 50,
    offset: 0,
    total: 0,
    lines: [],
    pathOptions: [],
    selectedLineId: null,
    selectedLine: null,
    status: '',
    hasLines: false,
    hasSelectedLine: false,
    hasPreviousPage: false,
    hasNextPage: false,
    unloadHandlers: [],

    async postLoad() {
      this.root = document.querySelector('[data-script-review-page]');
      this.bind(this.root, 'click', event => this.onClick(event));
      this.bind(this.root, 'submit', event => this.onSubmit(event));
      this.bind(this.root, 'change', event => this.onChange(event));
      this.setControlValues();
    },

    unload() {
      this.unloadHandlers.forEach(unload => unload());
      this.unloadHandlers = [];
    },

    bind(target, type, handler) {
      if (!target) return;
      target.addEventListener(type, handler);
      this.unloadHandlers.push(() => target.removeEventListener(type, handler));
    },

    async onClick(event) {
      const lineButton = event.target.closest('[data-action="select-script-line"]');
      if (lineButton) {
        await this.selectLine(Number(lineButton.dataset.lineId));
        return;
      }

      const previousButton = event.target.closest('[data-action="previous-page"]');
      if (previousButton) {
        this.offset = Math.max(0, this.offset - this.limit);
        await this.loadLines();
        return;
      }

      const nextButton = event.target.closest('[data-action="next-page"]');
      if (nextButton) {
        this.offset += this.limit;
        await this.loadLines();
        return;
      }

      const importButton = event.target.closest('[data-action="import-script-audio"]');
      if (importButton) {
        await this.importScriptAudio(importButton);
      }
    },

    async onSubmit(event) {
      const filtersForm = event.target.closest('[data-script-filters]');
      if (filtersForm) {
        event.preventDefault();
        this.readFilters(filtersForm);
        this.offset = 0;
        await this.loadLines();
        return;
      }

      const translationForm = event.target.closest('[data-translation-form]');
      if (translationForm) {
        event.preventDefault();
        await this.saveTranslation(translationForm);
        return;
      }

      const audioForm = event.target.closest('[data-audio-candidate-form]');
      if (audioForm) {
        event.preventDefault();
        await this.saveAudioCandidate(audioForm);
      }
    },

    async onChange(event) {
      if (event.target.closest('[data-script-filters]')) {
        const form = event.target.closest('[data-script-filters]');
        this.readFilters(form);
        this.offset = 0;
        await this.loadLines();
      }
    },

    readFilters(form) {
      const formData = new FormData(form);
      this.query = String(formData.get('q') ?? '').trim();
      this.path = String(formData.get('path') ?? '').trim();
      this.language = String(formData.get('language') ?? 'en');
      this.translationStatus = String(formData.get('translation_status') ?? '');
      this.audioStatus = String(formData.get('audio_status') ?? '');
      this.audioSource = String(formData.get('audio_source') ?? '');
      this.missingAudio = formData.get('missing_audio') === 'on';
    },

    async loadLines() {
      this.setStatus('Loading script lines...');
      const query = new URLSearchParams({
        q: this.query,
        path: this.path,
        language: this.language,
        translation_status: this.translationStatus,
        audio_status: this.audioStatus,
        audio_source: this.audioSource,
        missing_audio: String(this.missingAudio),
        limit: String(this.limit),
        offset: String(this.offset)
      });
      try {
        const response = await apiFetch(`/api/script-lines?${query.toString()}`);
        this.total = response.total;
        this.lines = response.items.map(line => ({
          ...line,
          isSelected: line.line_id === this.selectedLineId,
          pathLabel: line.path_text || 'Unsorted',
          translationStatusLabel: statusLabel(line.selected_translation?.review_status),
          audioSummary: `${line.audio_candidate_count} audio`
        }));
        if (!this.selectedLineId && this.lines.length) {
          await this.selectLine(this.lines[0].line_id, {skipListRefresh: true});
        } else if (this.selectedLineId && this.lines.some(line => line.line_id === this.selectedLineId)) {
          await this.selectLine(this.selectedLineId, {skipListRefresh: true});
        } else {
          this.selectedLineId = null;
          this.selectedLine = null;
          this.hasSelectedLine = false;
        }
        this.preparePaging();
        this.setStatus('');
        this.refreshView();
      } catch {
        this.setStatus('Could not load script lines.');
      }
    },

    async selectLine(lineId, options = {}) {
      this.selectedLineId = lineId;
      if (!options.skipListRefresh) {
        this.lines = this.lines.map(line => ({...line, isSelected: line.line_id === lineId}));
      }
      try {
        const detail = await apiFetch(`/api/script-lines/${lineId}`);
        this.selectedLine = prepareLineDetail(detail, this.language);
        this.hasSelectedLine = true;
        this.refreshView();
      } catch {
        this.setStatus('Could not load the selected line.');
      }
    },

    preparePaging() {
      this.hasLines = this.lines.length > 0;
      this.hasPreviousPage = this.offset > 0;
      this.hasNextPage = this.offset + this.limit < this.total;
    },

    async importScriptAudio(button) {
      button.disabled = true;
      this.setStatus('Importing script and audio manifests...');
      try {
        const result = await apiFetch('/api/admin/import-script-audio', {
          method: 'POST',
          body: JSON.stringify({})
        });
        this.setStatus(
          `Imported ${result.script_lines} lines, ${result.translations} translations, ` +
            `${result.narrator_candidates + result.tts_candidates} audio records.`
        );
        this.pathOptions = await loadPathOptions();
        await this.loadLines();
      } catch {
        this.setStatus('Could not import the script/audio files.');
      } finally {
        button.disabled = false;
      }
    },

    async saveTranslation(form) {
      if (!this.selectedLine) return;
      const formData = new FormData(form);
      const language = String(formData.get('language') ?? this.language);
      this.setStatus('Saving translation...');
      try {
        await apiFetch(`/api/script-lines/${this.selectedLine.line_id}/translations/${language}`, {
          method: 'PATCH',
          body: JSON.stringify({
            text: String(formData.get('text') ?? ''),
            review_status: String(formData.get('review_status') ?? 'needs_review'),
            notes: String(formData.get('notes') ?? '')
          })
        });
        await this.selectLine(this.selectedLine.line_id);
        await this.loadLines();
        this.setStatus('Translation saved.');
      } catch {
        this.setStatus('Could not save translation.');
      }
    },

    async saveAudioCandidate(form) {
      const formData = new FormData(form);
      const candidateId = Number(formData.get('candidate_id'));
      if (!candidateId) return;
      this.setStatus('Saving audio review...');
      try {
        await apiFetch(`/api/script-audio-candidates/${candidateId}`, {
          method: 'PATCH',
          body: JSON.stringify({
            review_status: String(formData.get('review_status') ?? 'needs_review'),
            notes: String(formData.get('notes') ?? ''),
            selected: formData.get('selected') === 'on'
          })
        });
        await this.selectLine(this.selectedLineId);
        await this.loadLines();
        this.setStatus('Audio review saved.');
      } catch {
        this.setStatus('Could not save audio review.');
      }
    },

    setStatus(message) {
      this.status = message;
      const status = this.root?.querySelector('[data-script-status]');
      if (status) status.textContent = message;
    },

    setControlValues() {
      const form = this.root?.querySelector('[data-script-filters]');
      if (!form) return;
      form.elements.q.value = this.query;
      form.elements.path.value = this.path;
      form.elements.language.value = this.language;
      form.elements.translation_status.value = this.translationStatus;
      form.elements.audio_status.value = this.audioStatus;
      form.elements.audio_source.value = this.audioSource;
      form.elements.missing_audio.checked = this.missingAudio;
      const translationForm = this.root?.querySelector('[data-translation-form]');
      if (translationForm && this.selectedLine?.activeTranslation) {
        translationForm.elements.review_status.value = this.selectedLine.activeTranslation.review_status;
      }
      this.root?.querySelectorAll('[data-audio-candidate-form]').forEach(formElement => {
        const candidate = this.selectedLine?.audio_candidates?.find(
          item => String(item.id) === String(formElement.elements.candidate_id.value)
        );
        if (candidate) {
          formElement.elements.review_status.value = candidate.review_status;
          formElement.elements.selected.checked = candidate.selected;
        }
      });
      const previousButton = this.root?.querySelector('[data-action="previous-page"]');
      const nextButton = this.root?.querySelector('[data-action="next-page"]');
      if (previousButton) previousButton.disabled = !this.hasPreviousPage;
      if (nextButton) nextButton.disabled = !this.hasNextPage;
    },

    refreshView() {
      if (!this.root) return;
      app.refresh();
      requestAnimationFrame(() => this.setControlValues());
    }
  };

  controller.pathOptions = await loadPathOptions();
  await controller.loadLines();
  return controller;
};

async function loadPathOptions() {
  try {
    return (await apiFetch('/api/script-lines/paths')).map(path => ({path}));
  } catch {
    return [];
  }
}

function prepareLineDetail(line, activeLanguage) {
  const activeTranslation = line.translations.find(
    translation => translation.language === activeLanguage
  ) ?? {
    id: null,
    script_line_id: line.id,
    language: activeLanguage,
    text: '',
    source: '',
    review_status: 'missing',
    notes: '',
    manually_edited: false,
    meta: {}
  };
  return {
    ...line,
    pathLabel: line.path_text || 'Unsorted',
    activeTranslation: {
      ...activeTranslation,
      statusLabel: statusLabel(activeTranslation.review_status)
    },
    audio_candidates: line.audio_candidates
      .filter(candidate => candidate.language === activeLanguage)
      .map(candidate => ({
        ...candidate,
        audioUrl: candidate.relative_path ? scriptAudioCandidateUrl(candidate.id) : '',
        sourceLabel: sourceLabel(candidate.source_type),
        statusLabel: statusLabel(candidate.review_status),
        durationLabel: candidate.duration_seconds
          ? `${Number(candidate.duration_seconds).toFixed(2)}s`
          : '',
        scoreLabel: candidate.score ? `${Number(candidate.score).toFixed(1)}` : '',
        hasAudio: Boolean(candidate.relative_path)
      })),
    hasAudioCandidates: line.audio_candidates.some(candidate => candidate.language === activeLanguage)
  };
}

function sourceLabel(value) {
  if (value === 'narrator_candidate') return 'Narrator';
  if (value === 'tts') return 'TTS';
  return value;
}

function statusLabel(value) {
  return String(value || 'missing').replace(/_/g, ' ');
}

export {ScriptReviewCtrl};
