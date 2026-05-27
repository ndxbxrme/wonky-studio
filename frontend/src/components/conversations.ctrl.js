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
    unloadHandlers: [],

    async postLoad() {
      this.root = document.querySelector('[data-conversations-page]');
      this.bind(this.root, 'click', event => this.onClick(event));
      this.bind(this.root, 'submit', event => this.onSubmit(event));
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
        this.selectedConversationId = this.conversations[0]?.id ?? null;
      }
      this.selectedConversation = this.conversations.find(conversation => Number(conversation.id) === Number(this.selectedConversationId)) ?? null;
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
    },

    setStatus(message) {
      this.status = message;
      applyStatus(this.root?.querySelector('[data-conversations-status]'), message);
    },

    async onClick(event) {
      const selectConversation = event.target.closest('[data-action="select-conversation"]');
      if (selectConversation) {
        this.selectedConversationId = Number(selectConversation.dataset.conversationId);
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
      }
    },

    async onSubmit(event) {
      const form = event.target.closest('[data-conversation-form]');
      if (!form) return;
      event.preventDefault();
      await this.saveConversation(form);
    },

    async saveConversation(form) {
      const payload = {
        name: String(form.elements.name.value || '').trim(),
        description: String(form.elements.description.value || '')
      };
      if (!payload.name) return;
      const conversationId = Number(form.elements.conversation_id.value || 0);
      this.setStatus(conversationId ? 'Saving conversation...' : 'Creating conversation...');
      try {
        const saved = await apiFetch(conversationId ? `/api/conversations/${conversationId}` : '/api/conversations', {
          method: conversationId ? 'PATCH' : 'POST',
          body: JSON.stringify(payload)
        });
        this.selectedConversationId = saved.id;
        await this.refreshData();
        this.refreshView();
        this.setStatus(conversationId ? 'Conversation saved.' : 'Conversation created.');
      } catch {
        this.setStatus(conversationId ? 'Could not save conversation.' : 'Could not create conversation.');
      }
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
        await this.refreshData();
        this.refreshView();
        this.setStatus('Conversation removed.');
      } catch {
        this.setStatus('Could not remove conversation.');
      }
    },

    async moveConversation(conversationId, direction) {
      const conversations = [...(this.conversations ?? [])];
      const index = conversations.findIndex(item => Number(item.id) === Number(conversationId));
      if (index < 0) return;
      const targetIndex = direction === 'up' ? index - 1 : index + 1;
      if (targetIndex < 0 || targetIndex >= conversations.length) return;
      [conversations[index], conversations[targetIndex]] = [conversations[targetIndex], conversations[index]];
      this.setStatus('Reordering conversations...');
      try {
        await Promise.all(conversations.map((conversation, nextIndex) => apiFetch(`/api/conversations/${conversation.id}`, {
          method: 'PATCH',
          body: JSON.stringify({sort_order: nextIndex})
        })));
        await this.refreshData();
        this.refreshView();
        this.setStatus('Conversation order updated.');
      } catch {
        this.setStatus('Could not reorder conversations.');
      }
    }
  };

  await controller.refreshData();
  return controller;
};

export {ConversationsCtrl};
