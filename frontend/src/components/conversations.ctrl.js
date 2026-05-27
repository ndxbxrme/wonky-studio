import {apiFetch} from '../api.js';
import {applyStatus} from '../status.js';
import {user} from '../state/user.js';

const ConversationsCtrl = app => async () => {
  const controller = {
    appName: 'Wonky Studio',
    user: user.current,
    conversations: [],
    selectedConversationId: null,
    selectedConversation: null,
    status: '',
    conversationFormStatus: '',
    globalHistoryUndoStack: [],
    globalHistoryRedoStack: [],
    canUndoGlobalHistory: false,
    canRedoGlobalHistory: false,
    suppressAutoSelectOnce: false,
    unloadHandlers: [],

    async postLoad() {
      this.root = document.querySelector('[data-conversations-page]');
      this.bind(this.root, 'click', event => this.onClick(event));
      this.bind(this.root, 'submit', event => this.onSubmit(event));
      this.bind(this.root, 'change', event => this.onChange(event));
      this.bind(window, 'keydown', event => this.onKeyDown(event));
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

    async refreshData() {
      this.conversations = await apiFetch('/api/conversations');
      this.prepareState();
    },

    prepareState() {
      this.conversations = (this.conversations ?? []).map(conversation => ({
        ...conversation,
        isSelected: Number(conversation.id) === Number(this.selectedConversationId)
      }));
      if (!this.conversations.some(conversation => Number(conversation.id) === Number(this.selectedConversationId))) {
        if (this.suppressAutoSelectOnce) {
          this.suppressAutoSelectOnce = false;
          this.selectedConversationId = null;
        } else {
          this.selectedConversationId = this.conversations[0]?.id ?? null;
        }
      }
      if (!this.selectedConversationId && this.suppressAutoSelectOnce) {
        this.suppressAutoSelectOnce = false;
      }
      this.selectedConversation = this.conversations.find(conversation => Number(conversation.id) === Number(this.selectedConversationId)) ?? null;
      this.canUndoGlobalHistory = this.globalHistoryUndoStack.length > 0;
      this.canRedoGlobalHistory = this.globalHistoryRedoStack.length > 0;
    },

    refreshView() {
      app.refresh();
      this.setControlValues();
    },

    setControlValues() {
      const form = this.root?.querySelector('[data-conversation-form]');
      if (!form) return;
      form.elements.conversation_id.value = this.selectedConversation?.id ?? '';
      form.elements.name.value = this.selectedConversation?.name ?? '';
      form.elements.description.value = this.selectedConversation?.description ?? '';
      applyStatus(this.root?.querySelector('[data-conversation-form-status]'), this.conversationFormStatus);
    },

    setStatus(message) {
      this.status = message;
      applyStatus(this.root?.querySelector('[data-conversations-status]'), message);
    },

    async onClick(event) {
      const selectConversation = event.target.closest('[data-action="select-conversation"]');
      if (selectConversation) {
        this.selectedConversationId = Number(selectConversation.dataset.conversationId);
        this.conversationFormStatus = '';
        this.prepareState();
        this.refreshView();
        return;
      }
      const newConversation = event.target.closest('[data-action="new-conversation"]');
      if (newConversation) {
        this.suppressAutoSelectOnce = true;
        this.selectedConversationId = null;
        this.conversationFormStatus = '';
        this.prepareState();
        this.refreshView();
        return;
      }
      const deleteConversation = event.target.closest('[data-action="delete-conversation"]');
      if (deleteConversation) {
        await this.deleteConversation(Number(deleteConversation.dataset.conversationId));
        return;
      }
      const moveConversation = event.target.closest('[data-action="move-conversation"]');
      if (moveConversation) {
        await this.moveConversation(Number(moveConversation.dataset.conversationId), String(moveConversation.dataset.direction || 'up'));
        return;
      }
      const undoButton = event.target.closest('[data-action="undo-conversation-change"]');
      if (undoButton) {
        await this.undoGlobalHistoryChange();
        return;
      }
      const redoButton = event.target.closest('[data-action="redo-conversation-change"]');
      if (redoButton) {
        await this.redoGlobalHistoryChange();
      }
    },

    async onChange(event) {
      const form = event.target.closest('[data-conversation-form]');
      if (!form) return;
      if (!Number(form.elements.conversation_id?.value || 0)) return;
      await this.autosaveSelectedConversationForm(form);
    },

    async onKeyDown(event) {
      if (!(event.ctrlKey || event.metaKey) || event.altKey) return;
      const target = event.target;
      if (
        target instanceof HTMLInputElement
        || target instanceof HTMLTextAreaElement
        || target instanceof HTMLSelectElement
        || target?.isContentEditable
      ) {
        return;
      }
      const key = String(event.key || '').toLowerCase();
      if (key === 'z' && !event.shiftKey) {
        event.preventDefault();
        await this.undoGlobalHistoryChange();
        return;
      }
      if (key === 'y' || (key === 'z' && event.shiftKey)) {
        event.preventDefault();
        await this.redoGlobalHistoryChange();
      }
    },

    async onSubmit(event) {
      const form = event.target.closest('[data-conversation-form]');
      if (!form) return;
      event.preventDefault();
      await this.saveConversation(form);
    },

    readConversationForm(form) {
      return {
        name: String(form.elements.name.value || '').trim(),
        description: String(form.elements.description.value || '')
      };
    },

    async saveConversation(form) {
      const payload = this.readConversationForm(form);
      if (!payload.name) return;
      const conversationId = Number(form.elements.conversation_id.value || 0);
      if (conversationId) {
        const saved = await this.saveConversationPayload(conversationId, payload);
        if (saved) this.selectedConversationId = conversationId;
        return;
      }
      this.setStatus('Creating conversation...');
      try {
        const saved = await apiFetch('/api/conversations', {
          method: 'POST',
          body: JSON.stringify(payload)
        });
        this.selectedConversationId = saved.id;
        this.conversationFormStatus = '';
        await this.refreshData();
        this.refreshView();
        this.setStatus('Conversation created.');
      } catch {
        this.setStatus('Could not create conversation.');
      }
    },

    async saveConversationPayload(conversationId, payload, {statusMessage = 'Saving...', successMessage = 'All conversation changes saved.', failureMessage = 'Could not save conversation.'} = {}) {
      this.conversationFormStatus = statusMessage;
      this.refreshView();
      try {
        await apiFetch(`/api/conversations/${conversationId}`, {
          method: 'PATCH',
          body: JSON.stringify(payload)
        });
        this.selectedConversationId = conversationId;
        await this.refreshData();
        this.conversationFormStatus = successMessage;
        this.refreshView();
        return true;
      } catch {
        this.conversationFormStatus = failureMessage;
        this.refreshView();
        return false;
      }
    },

    async autosaveSelectedConversationForm(form) {
      const conversationId = Number(form.elements.conversation_id.value || 0);
      if (!conversationId || !this.selectedConversation) return;
      const previousPayload = {
        name: String(this.selectedConversation.name ?? ''),
        description: String(this.selectedConversation.description ?? '')
      };
      const nextPayload = this.readConversationForm(form);
      if (JSON.stringify(previousPayload) === JSON.stringify(nextPayload)) return;
      const saved = await this.saveConversationPayload(conversationId, nextPayload);
      if (!saved) return;
      this.recordGlobalHistoryEntry({
        label: 'Edit conversation',
        undo: () => this.restoreConversationPayload(conversationId, previousPayload),
        redo: () => this.restoreConversationPayload(conversationId, nextPayload)
      });
    },

    async restoreConversationPayload(conversationId, payload) {
      await this.saveConversationPayload(conversationId, payload, {
        statusMessage: 'Saving...',
        successMessage: 'All conversation changes saved.',
        failureMessage: 'Could not restore conversation.'
      });
    },

    async deleteConversation(conversationId) {
      const conversation = this.conversations.find(item => Number(item.id) === Number(conversationId));
      if (!conversation) return;
      if (!window.confirm(`Remove conversation "${conversation.name}"?`)) return;
      this.setStatus('Removing conversation...');
      try {
        await apiFetch(`/api/conversations/${conversationId}`, {method: 'DELETE'});
        if (Number(this.selectedConversationId) === Number(conversationId)) {
          this.selectedConversationId = null;
        }
        this.conversationFormStatus = '';
        await this.refreshData();
        this.refreshView();
        this.setStatus('Conversation removed.');
      } catch {
        this.setStatus('Could not remove conversation.');
      }
    },

    async moveConversation(conversationId, direction) {
      const previousOrder = (this.conversations ?? []).map(conversation => Number(conversation.id));
      const conversations = [...(this.conversations ?? [])];
      const index = conversations.findIndex(item => Number(item.id) === Number(conversationId));
      if (index < 0) return;
      const targetIndex = direction === 'up' ? index - 1 : index + 1;
      if (targetIndex < 0 || targetIndex >= conversations.length) return;
      [conversations[index], conversations[targetIndex]] = [conversations[targetIndex], conversations[index]];
      this.conversations = conversations.map((conversation, nextIndex) => ({
        ...conversation,
        sort_order: nextIndex
      }));
      this.prepareState();
      this.refreshView();
      this.setStatus('Saving conversation order...');
      try {
        await Promise.all(conversations.map((conversation, nextIndex) => apiFetch(`/api/conversations/${conversation.id}`, {
          method: 'PATCH',
          body: JSON.stringify({sort_order: nextIndex})
        })));
        const nextOrder = conversations.map(conversation => Number(conversation.id));
        this.recordGlobalHistoryEntry({
          label: 'Reorder conversations',
          undo: () => this.restoreConversationOrder(previousOrder),
          redo: () => this.restoreConversationOrder(nextOrder)
        });
        this.setStatus('Conversation order updated.');
      } catch {
        await this.refreshData();
        this.refreshView();
        this.setStatus('Could not reorder conversations.');
      }
    },

    async restoreConversationOrder(orderedIds) {
      this.setStatus('Saving conversation order...');
      try {
        await Promise.all(
          orderedIds.map((conversationId, index) => apiFetch(`/api/conversations/${conversationId}`, {
            method: 'PATCH',
            body: JSON.stringify({sort_order: index})
          }))
        );
        await this.refreshData();
        this.refreshView();
        this.setStatus('Conversation order updated.');
      } catch {
        this.setStatus('Could not restore conversation order.');
      }
    },

    recordGlobalHistoryEntry(entry) {
      this.globalHistoryUndoStack.push(entry);
      if (this.globalHistoryUndoStack.length > 200) this.globalHistoryUndoStack.shift();
      this.globalHistoryRedoStack = [];
      this.prepareState();
      this.refreshView();
    },

    async undoGlobalHistoryChange() {
      const entry = this.globalHistoryUndoStack.pop();
      if (!entry) return;
      await entry.undo();
      this.globalHistoryRedoStack.push(entry);
      this.prepareState();
      this.refreshView();
    },

    async redoGlobalHistoryChange() {
      const entry = this.globalHistoryRedoStack.pop();
      if (!entry) return;
      await entry.redo();
      this.globalHistoryUndoStack.push(entry);
      this.prepareState();
      this.refreshView();
    }
  };

  await controller.refreshData();
  return controller;
};

export {ConversationsCtrl};
