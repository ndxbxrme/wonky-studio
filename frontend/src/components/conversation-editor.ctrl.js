import {apiFetch} from '../api.js';
import {applyStatus} from '../status.js';
import {user} from '../state/user.js';
import {
  ACTION_TYPES,
  actionTypeHelp,
  buildBranchOptions,
  findStepById,
  flattenActionRows,
  insertStep,
  moveStepById,
  readActionStepForm,
  removeStepById,
  replaceStepById,
  setActionStepFormValues
} from './actions.ctrl.js';

const ConversationEditorCtrl = app => async params => {
  const conversationId = Number(params[0]);
  const controller = {
    appName: 'Wonky Studio',
    user: user.current,
    conversationId,
    conversation: null,
    conversationFound: false,
    scriptLineOptions: [],
    characterOptions: [],
    variables: [],
    sceneOptions: [],
    conversationOptions: [],
    overlaySceneOptions: [],
    baseSceneOptions: [],
    inventoryObjectOptions: [],
    targetObjectOptions: [],
    audioAssetOptions: [],
    bgmOptions: [],
    sfxOptions: [],
    animationOptions: [],
    animationNameOptions: [],
    characterAnimationOptions: [],
    randomIdleCharacterAnimationOptions: [],
    actionTypes: ACTION_TYPES,
    nodeScriptSearchResults: [],
    choiceScriptSearchResults: [],
    selectedNodeId: null,
    selectedNode: null,
    suppressNodeAutoSelect: false,
    selectedChoiceId: null,
    selectedChoice: null,
    suppressChoiceAutoSelect: false,
    nodeSelectedStepId: null,
    nodeSelectedStep: null,
    nodeActionRows: [],
    nodeBranchOptions: [],
    choiceSelectedStepId: null,
    choiceSelectedStep: null,
    choiceActionRows: [],
    choiceBranchOptions: [],
    status: '',
    unloadHandlers: [],

    async postLoad() {
      this.root = document.querySelector('[data-conversation-editor-page]');
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

    async refreshData() {
      const [conversation, scriptLines, characters, variables, scenes, inventoryObjects, audioAssets, conversations] = await Promise.all([
        apiFetch(`/api/conversations/${this.conversationId}`),
        apiFetch('/api/script-lines?limit=500&offset=0'),
        apiFetch('/api/characters'),
        apiFetch('/api/variables'),
        apiFetch('/api/scenes'),
        apiFetch('/api/scene-objects'),
        apiFetch('/api/audio-assets'),
        apiFetch('/api/conversations')
      ]);
      this.conversation = conversation;
      this.conversationFound = true;
      this.scriptLineOptions = (scriptLines?.items ?? []).map(line => ({
        id: line.line_id,
        label: formatScriptLineLabel(line)
      }));
      this.characterOptions = characters ?? [];
      this.variables = variables ?? [];
      this.sceneOptions = scenes ?? [];
      this.conversationOptions = (conversations ?? []).filter(item => Number(item.id) !== Number(this.conversationId));
      this.baseSceneOptions = this.sceneOptions.filter(item => item.presentation_mode !== 'overlay');
      this.overlaySceneOptions = this.sceneOptions.filter(item => item.presentation_mode === 'overlay');
      this.inventoryObjectOptions = inventoryObjects ?? [];
      this.audioAssetOptions = audioAssets ?? [];
      this.bgmOptions = this.audioAssetOptions.filter(asset => asset.kind === 'bgm');
      this.sfxOptions = this.audioAssetOptions.filter(asset => asset.kind === 'sfx');
      this.targetObjectOptions = [
        ...(this.inventoryObjectOptions ?? []).map(object => ({
          id: object.id,
          name: `Scene ${object.scene_id} / ${object.name}`
        })),
        ...(this.characterOptions ?? []).flatMap(character => (
          (character.scene?.objects ?? []).map(object => ({
            id: object.id,
            name: `${character.name} / ${object.name}`
          }))
        ))
      ];
      this.characterAnimationOptions = (this.characterOptions ?? []).flatMap(character => (
        (character.animations ?? []).map(animation => ({
          characterId: character.id,
          animationId: animation.id,
          label: `${character.name} / ${animation.name}`
        }))
      ));
      await this.loadAnimations();
      this.prepareState();
    },

    async loadAnimations() {
      const staticTargets = [
        ...(this.inventoryObjectOptions ?? []).map(object => ({
          id: object.id,
          labelPrefix: `Scene ${object.scene_id} / ${object.name}`
        })),
        ...(this.characterOptions ?? []).flatMap(character => (
          (character.scene?.objects ?? []).map(object => ({
            id: object.id,
            labelPrefix: `${character.name} / ${object.name}`
          }))
        ))
      ];
      const uniqueTargets = new Map();
      for (const target of staticTargets) {
        if (!uniqueTargets.has(Number(target.id))) uniqueTargets.set(Number(target.id), target);
      }
      const animationGroups = await Promise.all(
        [...uniqueTargets.values()].map(async target => {
          try {
            const animations = await apiFetch(`/api/scene-objects/${target.id}/animations`);
            return (animations ?? []).map(animation => ({
              objectId: target.id,
              animationId: animation.id,
              name: animation.name,
              label: `${target.labelPrefix} / ${animation.name}`
            }));
          } catch {
            return [];
          }
        })
      );
      this.animationOptions = animationGroups.flat();
      this.animationNameOptions = [...new Set(this.animationOptions.map(animation => animation.name || ''))]
        .filter(Boolean)
        .sort((left, right) => left.localeCompare(right))
        .map(name => ({value: name, label: name}));
      const characterObjectIds = new Set(
        (this.characterOptions ?? []).flatMap(character => (
          (character.scene?.objects ?? []).map(object => Number(object.id))
        ))
      );
      this.randomIdleCharacterAnimationOptions = [
        ...this.characterAnimationOptions.map(animation => ({
          ...animation,
          scope: 'character'
        })),
        ...this.animationOptions
          .filter(animation => characterObjectIds.has(Number(animation.objectId)))
          .map(animation => {
            const owner = (this.characterOptions ?? []).find(character => (
              (character.scene?.objects ?? []).some(object => Number(object.id) === Number(animation.objectId))
            ));
            return {
              characterId: owner?.id ?? null,
              animationId: animation.animationId,
              objectId: animation.objectId,
              label: animation.label,
              scope: 'object'
            };
          })
          .filter(animation => Number(animation.characterId) > 0)
      ];
    },

    prepareState() {
      const startNodeId = Number(this.conversation?.start_node_id ?? 0);
      const nodes = (this.conversation?.nodes ?? []).map(node => {
        const linePreview = node?.script_line?.source_text || '';
        const choices = (node.choices ?? []).map(choice => ({
          ...choice,
          isSelected: Number(choice.id) === Number(this.selectedChoiceId),
          linePreview: choice?.script_line?.source_text || 'Untitled choice',
          destinationLabel: choice.end_conversation
            ? 'Ends conversation'
            : choice.next_node_id
              ? `Next: ${findNodeName(this.conversation?.nodes ?? [], choice.next_node_id)}`
              : 'No next node set'
        }));
        return {
          ...node,
          isSelected: Number(node.id) === Number(this.selectedNodeId),
          isStartNode: Number(node.id) === startNodeId,
          linePreview: linePreview ? truncate(linePreview, 72) : '',
          scriptLineLabel: linePreview || '',
          choiceCount: choices.length,
          choices
        };
      });
      if (!nodes.some(node => Number(node.id) === Number(this.selectedNodeId))) {
        this.selectedNodeId = this.suppressNodeAutoSelect ? null : (nodes[0]?.id ?? null);
        this.selectedChoiceId = null;
      }
      this.suppressNodeAutoSelect = false;
      this.conversation.nodes = nodes;
      this.selectedNode = nodes.find(node => Number(node.id) === Number(this.selectedNodeId)) ?? null;
      const choices = this.selectedNode?.choices ?? [];
      if (!choices.some(choice => Number(choice.id) === Number(this.selectedChoiceId))) {
        this.selectedChoiceId = this.suppressChoiceAutoSelect ? null : (choices[0]?.id ?? null);
      }
      this.suppressChoiceAutoSelect = false;
      if (this.selectedNode) {
        this.selectedNode.choices = choices.map(choice => ({
          ...choice,
          isSelected: Number(choice.id) === Number(this.selectedChoiceId)
        }));
      }
      this.selectedChoice = (this.selectedNode?.choices ?? []).find(choice => Number(choice.id) === Number(this.selectedChoiceId)) ?? null;
      this.nodeSelectedStep = this.selectedNode
        ? findStepById(this.selectedNode.enter_actions ?? [], this.nodeSelectedStepId)
        : null;
      if (!this.nodeSelectedStep) this.nodeSelectedStepId = null;
      this.nodeBranchOptions = buildBranchOptions(this.selectedNode?.enter_actions ?? [], {
        selectedStepId: this.nodeSelectedStepId,
        targetObjectOptions: this.targetObjectOptions,
        inventoryObjectOptions: this.inventoryObjectOptions,
        variables: this.variables,
        baseSceneOptions: this.baseSceneOptions,
        overlaySceneOptions: this.overlaySceneOptions,
        bgmOptions: this.bgmOptions,
        sfxOptions: this.sfxOptions,
        scriptLineSummaryById: {},
        characterOptions: this.characterOptions,
        characterAnimationOptions: this.characterAnimationOptions,
        randomIdleCharacterAnimationOptions: this.randomIdleCharacterAnimationOptions,
        animationOptions: this.animationOptions,
        animationNameOptions: this.animationNameOptions,
        conversationOptions: this.conversationOptions
      });
      this.nodeActionRows = flattenActionRows(this.selectedNode?.enter_actions ?? [], {
        selectedStepId: this.nodeSelectedStepId,
        targetObjectOptions: this.targetObjectOptions,
        inventoryObjectOptions: this.inventoryObjectOptions,
        variables: this.variables,
        baseSceneOptions: this.baseSceneOptions,
        overlaySceneOptions: this.overlaySceneOptions,
        bgmOptions: this.bgmOptions,
        sfxOptions: this.sfxOptions,
        scriptLineSummaryById: {},
        characterOptions: this.characterOptions,
        characterAnimationOptions: this.characterAnimationOptions,
        randomIdleCharacterAnimationOptions: this.randomIdleCharacterAnimationOptions,
        animationOptions: this.animationOptions,
        animationNameOptions: this.animationNameOptions,
        conversationOptions: this.conversationOptions
      });
      this.choiceSelectedStep = this.selectedChoice
        ? findStepById(this.selectedChoice.actions ?? [], this.choiceSelectedStepId)
        : null;
      if (!this.choiceSelectedStep) this.choiceSelectedStepId = null;
      this.choiceBranchOptions = buildBranchOptions(this.selectedChoice?.actions ?? [], {
        selectedStepId: this.choiceSelectedStepId,
        targetObjectOptions: this.targetObjectOptions,
        inventoryObjectOptions: this.inventoryObjectOptions,
        variables: this.variables,
        baseSceneOptions: this.baseSceneOptions,
        overlaySceneOptions: this.overlaySceneOptions,
        bgmOptions: this.bgmOptions,
        sfxOptions: this.sfxOptions,
        scriptLineSummaryById: {},
        characterOptions: this.characterOptions,
        characterAnimationOptions: this.characterAnimationOptions,
        randomIdleCharacterAnimationOptions: this.randomIdleCharacterAnimationOptions,
        animationOptions: this.animationOptions,
        animationNameOptions: this.animationNameOptions,
        conversationOptions: this.conversationOptions
      });
      this.choiceActionRows = flattenActionRows(this.selectedChoice?.actions ?? [], {
        selectedStepId: this.choiceSelectedStepId,
        targetObjectOptions: this.targetObjectOptions,
        inventoryObjectOptions: this.inventoryObjectOptions,
        variables: this.variables,
        baseSceneOptions: this.baseSceneOptions,
        overlaySceneOptions: this.overlaySceneOptions,
        bgmOptions: this.bgmOptions,
        sfxOptions: this.sfxOptions,
        scriptLineSummaryById: {},
        characterOptions: this.characterOptions,
        characterAnimationOptions: this.characterAnimationOptions,
        randomIdleCharacterAnimationOptions: this.randomIdleCharacterAnimationOptions,
        animationOptions: this.animationOptions,
        animationNameOptions: this.animationNameOptions,
        conversationOptions: this.conversationOptions
      });
    },

    refreshView() {
      app.refresh();
      this.setControlValues();
    },

    setControlValues() {
      const settingsForm = this.root?.querySelector('[data-conversation-settings-form]');
      if (settingsForm && this.conversation) {
        settingsForm.elements.name.value = this.conversation.name ?? '';
        settingsForm.elements.description.value = this.conversation.description ?? '';
        settingsForm.elements.start_node_id.value = this.conversation.start_node_id ?? '';
      }
      const nodeForm = this.root?.querySelector('[data-node-form]');
      if (nodeForm) {
        nodeForm.elements.node_id.value = this.selectedNode?.id ?? '';
        nodeForm.elements.name.value = this.selectedNode?.name ?? '';
        nodeForm.elements.script_line_id.value = this.selectedNode?.script_line_id ?? '';
        nodeForm.elements.speaker_character_id.value = this.selectedNode?.speaker_character_id ?? '';
      }
      const choiceForm = this.root?.querySelector('[data-choice-form]');
      if (choiceForm) {
        choiceForm.elements.choice_id.value = this.selectedChoice?.id ?? '';
        choiceForm.elements.script_line_id.value = this.selectedChoice?.script_line_id ?? '';
        choiceForm.elements.next_node_id.value = this.selectedChoice?.next_node_id ?? '';
        choiceForm.elements.end_conversation.checked = Boolean(this.selectedChoice?.end_conversation);
      }
      this.root?.querySelectorAll('[data-conversation-action-form]').forEach(form => {
        const target = String(form.dataset.actionTarget || 'node');
        const selectedStep = target === 'choice' ? this.choiceSelectedStep : this.nodeSelectedStep;
        setActionStepFormValues(form, selectedStep);
        this.updateActionFormVisibility(form);
      });
    },

    setStatus(message) {
      this.status = message;
      applyStatus(this.root?.querySelector('[data-conversation-editor-status]'), message);
    },

    async onClick(event) {
      const selectNode = event.target.closest('[data-action="select-node"]');
      if (selectNode) {
        this.selectedNodeId = Number(selectNode.dataset.nodeId);
        this.selectedChoiceId = null;
        this.suppressNodeAutoSelect = false;
        this.suppressChoiceAutoSelect = false;
        this.prepareState();
        this.refreshView();
        return;
      }
      const selectChoice = event.target.closest('[data-action="select-choice"]');
      if (selectChoice) {
        this.selectedChoiceId = Number(selectChoice.dataset.choiceId);
        this.prepareState();
        this.refreshView();
        return;
      }
      if (event.target.closest('[data-action="clear-node-selection"]')) {
        this.selectedNodeId = null;
        this.selectedChoiceId = null;
        this.suppressNodeAutoSelect = true;
        this.suppressChoiceAutoSelect = true;
        this.prepareState();
        this.refreshView();
        return;
      }
      if (event.target.closest('[data-action="clear-choice-selection"]')) {
        this.selectedChoiceId = null;
        this.suppressChoiceAutoSelect = true;
        this.prepareState();
        this.refreshView();
        return;
      }
      const deleteNode = event.target.closest('[data-action="delete-node"]');
      if (deleteNode) {
        await this.deleteNode(Number(deleteNode.dataset.nodeId));
        return;
      }
      const deleteChoice = event.target.closest('[data-action="delete-choice"]');
      if (deleteChoice) {
        await this.deleteChoice(Number(deleteChoice.dataset.choiceId));
        return;
      }
      const selectNodeLine = event.target.closest('[data-action="select-node-line"]');
      if (selectNodeLine) {
        this.applySelectedLine('node', Number(selectNodeLine.dataset.lineId));
        return;
      }
      const searchNodeLines = event.target.closest('[data-action="search-node-lines"]');
      if (searchNodeLines) {
        const searchPanel = this.root?.querySelector('[data-node-line-search-form]');
        if (searchPanel) await this.searchScriptLines(searchPanel, 'node');
        return;
      }
      const clearNodeLine = event.target.closest('[data-action="clear-node-line"]');
      if (clearNodeLine) {
        this.applySelectedLine('node', null);
        return;
      }
      const selectChoiceLine = event.target.closest('[data-action="select-choice-line"]');
      if (selectChoiceLine) {
        this.applySelectedLine('choice', Number(selectChoiceLine.dataset.lineId));
        return;
      }
      const searchChoiceLines = event.target.closest('[data-action="search-choice-lines"]');
      if (searchChoiceLines) {
        const searchPanel = this.root?.querySelector('[data-choice-line-search-form]');
        if (searchPanel) await this.searchScriptLines(searchPanel, 'choice');
        return;
      }
      const clearChoiceLine = event.target.closest('[data-action="clear-choice-line"]');
      if (clearChoiceLine) {
        this.applySelectedLine('choice', null);
        return;
      }
      const moveNode = event.target.closest('[data-action="move-node"]');
      if (moveNode) {
        await this.moveNode(Number(moveNode.dataset.nodeId), String(moveNode.dataset.direction || 'up'));
        return;
      }
      const moveChoice = event.target.closest('[data-action="move-choice"]');
      if (moveChoice) {
        await this.moveChoice(Number(moveChoice.dataset.choiceId), String(moveChoice.dataset.direction || 'up'));
        return;
      }
      const selectActionStep = event.target.closest('[data-action="select-conversation-step"]');
      if (selectActionStep) {
        const target = String(selectActionStep.dataset.actionTarget || 'node');
        this.setSelectedActionStepId(target, String(selectActionStep.dataset.stepId || ''));
        this.prepareState();
        this.refreshView();
        return;
      }
      const cancelActionStep = event.target.closest('[data-action="cancel-conversation-step-edit"]');
      if (cancelActionStep) {
        const target = String(cancelActionStep.dataset.actionTarget || 'node');
        this.clearSelectedActionStep(target);
        this.prepareState();
        this.refreshView();
        return;
      }
      const removeActionStep = event.target.closest('[data-action="remove-conversation-step"]');
      if (removeActionStep) {
        await this.removeActionStep(
          String(removeActionStep.dataset.actionTarget || 'node'),
          String(removeActionStep.dataset.stepId || '')
        );
        return;
      }
      const moveActionStep = event.target.closest('[data-action="move-conversation-step"]');
      if (moveActionStep) {
        await this.moveActionStep(
          String(moveActionStep.dataset.actionTarget || 'node'),
          String(moveActionStep.dataset.stepId || ''),
          String(moveActionStep.dataset.direction || 'up')
        );
        return;
      }
    },

    async onSubmit(event) {
      const conversationForm = event.target.closest('[data-conversation-settings-form]');
      if (conversationForm) {
        event.preventDefault();
        await this.saveConversationSettings(conversationForm);
        return;
      }
      const nodeForm = event.target.closest('[data-node-form]');
      if (nodeForm) {
        event.preventDefault();
        await this.saveNode(nodeForm);
        return;
      }
      const choiceForm = event.target.closest('[data-choice-form]');
      if (choiceForm) {
        event.preventDefault();
        await this.saveChoice(choiceForm);
        return;
      }
      const actionForm = event.target.closest('[data-conversation-action-form]');
      if (actionForm) {
        event.preventDefault();
        const target = String(actionForm.dataset.actionTarget || 'node');
        if (this.getSelectedActionStep(target)) await this.updateActionStep(target, actionForm);
        else await this.addActionStep(target, actionForm);
      }
    },

    async onChange(event) {
      if (event.target.matches('[name="action_type"], [name="target_scope"], [name="target_object_mode"], [name="scene_object_mode"], [name="random_idle_scope"]')) {
        this.updateActionFormVisibility(event.target.closest('[data-conversation-action-form]'));
        return;
      }
      if (event.target.matches('[name="property"]')) {
        this.updateActionFormVisibility(event.target.closest('[data-conversation-action-form]'));
      }
    },

    async saveConversationSettings(form) {
      this.setStatus('Saving conversation...');
      try {
        this.conversation = await apiFetch(`/api/conversations/${this.conversationId}`, {
          method: 'PATCH',
          body: JSON.stringify({
            name: String(form.elements.name.value || '').trim(),
            description: String(form.elements.description.value || ''),
            start_node_id: form.elements.start_node_id.value ? Number(form.elements.start_node_id.value) : null,
            clear_start_node_id: !form.elements.start_node_id.value
          })
        });
        this.prepareState();
        this.refreshView();
        this.setStatus('Conversation saved.');
      } catch {
        this.setStatus('Could not save conversation.');
      }
    },

    async saveNode(form) {
      this.setStatus(form.elements.node_id.value ? 'Saving node...' : 'Adding node...');
      try {
        const payload = {
          name: String(form.elements.name.value || '').trim(),
          script_line_id: form.elements.script_line_id.value ? Number(form.elements.script_line_id.value) : null,
          clear_script_line_id: !form.elements.script_line_id.value,
          speaker_character_id: form.elements.speaker_character_id.value ? Number(form.elements.speaker_character_id.value) : null,
          clear_speaker_character_id: !form.elements.speaker_character_id.value
        };
        const nodeId = Number(form.elements.node_id.value || 0);
        const saved = await apiFetch(nodeId ? `/api/conversation-nodes/${nodeId}` : `/api/conversations/${this.conversationId}/nodes`, {
          method: nodeId ? 'PATCH' : 'POST',
          body: JSON.stringify(payload)
        });
        this.selectedNodeId = saved.id;
        this.selectedChoiceId = null;
        await this.refreshData();
        this.refreshView();
        this.setStatus(nodeId ? 'Node saved.' : 'Node added.');
      } catch {
        this.setStatus('Could not save node.');
      }
    },

    async saveChoice(form) {
      if (!this.selectedNode) return;
      this.setStatus(form.elements.choice_id.value ? 'Saving choice...' : 'Adding choice...');
      try {
        const payload = {
          script_line_id: form.elements.script_line_id.value ? Number(form.elements.script_line_id.value) : null,
          clear_script_line_id: !form.elements.script_line_id.value,
          next_node_id: form.elements.next_node_id.value ? Number(form.elements.next_node_id.value) : null,
          clear_next_node_id: !form.elements.next_node_id.value,
          end_conversation: form.elements.end_conversation.checked
        };
        const choiceId = Number(form.elements.choice_id.value || 0);
        const saved = await apiFetch(choiceId ? `/api/conversation-choices/${choiceId}` : `/api/conversation-nodes/${this.selectedNode.id}/choices`, {
          method: choiceId ? 'PATCH' : 'POST',
          body: JSON.stringify(payload)
        });
        this.selectedChoiceId = saved.id;
        await this.refreshData();
        this.refreshView();
        this.setStatus(choiceId ? 'Choice saved.' : 'Choice added.');
      } catch {
        this.setStatus('Could not save choice.');
      }
    },

    async deleteNode(nodeId) {
      const node = (this.conversation?.nodes ?? []).find(item => Number(item.id) === Number(nodeId));
      if (!node) return;
      if (!window.confirm(`Remove node "${node.name}"? Choices pointing to it will end the conversation until you reconnect them.`)) return;
      this.setStatus('Removing node...');
      try {
        await apiFetch(`/api/conversation-nodes/${nodeId}`, {method: 'DELETE'});
        if (Number(this.selectedNodeId) === Number(nodeId)) {
          this.selectedNodeId = null;
          this.selectedChoiceId = null;
        }
        await this.refreshData();
        this.refreshView();
        this.setStatus('Node removed.');
      } catch {
        this.setStatus('Could not remove node.');
      }
    },

    async deleteChoice(choiceId) {
      const choice = (this.selectedNode?.choices ?? []).find(item => Number(item.id) === Number(choiceId));
      if (!choice) return;
      if (!window.confirm(`Remove choice "${choice.linePreview}"?`)) return;
      this.setStatus('Removing choice...');
      try {
        await apiFetch(`/api/conversation-choices/${choiceId}`, {method: 'DELETE'});
        if (Number(this.selectedChoiceId) === Number(choiceId)) this.selectedChoiceId = null;
        await this.refreshData();
        this.refreshView();
        this.setStatus('Choice removed.');
      } catch {
        this.setStatus('Could not remove choice.');
      }
    },

    async searchScriptLines(form, target) {
      const q = String(form?.querySelector('[name="q"]')?.value ?? '').trim();
      if (!q) return;
      this.setStatus('Searching script lines...');
      try {
        const result = await apiFetch(`/api/script-lines?${new URLSearchParams({q, language: 'en', limit: '12', offset: '0'})}`);
        const mapped = (result.items ?? []).map(line => ({
          id: line.line_id,
          label: formatScriptLineLabel(line)
        }));
        if (target === 'node') this.nodeScriptSearchResults = mapped;
        else this.choiceScriptSearchResults = mapped;
        this.refreshView();
        this.setStatus('');
      } catch {
        this.setStatus('Could not search script lines.');
      }
    },

    applySelectedLine(target, lineId) {
      const form = this.root?.querySelector(target === 'node' ? '[data-node-form]' : '[data-choice-form]');
      if (!form) return;
      form.elements.script_line_id.value = lineId ? String(lineId) : '';
      const line = lineId
        ? this.scriptLineOptions.find(option => Number(option.id) === Number(lineId))
        : null;
      if (target === 'node' && this.selectedNode) {
        this.selectedNode.script_line_id = lineId || null;
        this.selectedNode.scriptLineLabel = line?.label ?? '';
        this.selectedNode.linePreview = line?.label ?? '';
        const nodeIndex = (this.conversation?.nodes ?? []).findIndex(node => Number(node.id) === Number(this.selectedNode.id));
        if (nodeIndex >= 0) {
          this.conversation.nodes[nodeIndex] = {
            ...this.conversation.nodes[nodeIndex],
            script_line_id: lineId || null,
            scriptLineLabel: line?.label ?? '',
            linePreview: line?.label ?? ''
          };
        }
      }
      if (target === 'choice' && this.selectedChoice) {
        this.selectedChoice.script_line_id = lineId || null;
        this.selectedChoice.linePreview = line?.label ?? 'No player line selected';
        const choiceIndex = (this.selectedNode?.choices ?? []).findIndex(choice => Number(choice.id) === Number(this.selectedChoice.id));
        if (choiceIndex >= 0 && this.selectedNode) {
          this.selectedNode.choices[choiceIndex] = {
            ...this.selectedNode.choices[choiceIndex],
            script_line_id: lineId || null,
            linePreview: line?.label ?? 'No player line selected'
          };
        }
      }
      if (target === 'node') this.nodeScriptSearchResults = [];
      else this.choiceScriptSearchResults = [];
      this.refreshView();
    },

    async moveNode(nodeId, direction) {
      const nodes = [...(this.conversation?.nodes ?? [])];
      const index = nodes.findIndex(node => Number(node.id) === Number(nodeId));
      if (index < 0) return;
      const targetIndex = direction === 'up' ? index - 1 : index + 1;
      if (targetIndex < 0 || targetIndex >= nodes.length) return;
      [nodes[index], nodes[targetIndex]] = [nodes[targetIndex], nodes[index]];
      this.setStatus('Reordering nodes...');
      try {
        await Promise.all(nodes.map((node, nextIndex) => apiFetch(`/api/conversation-nodes/${node.id}`, {
          method: 'PATCH',
          body: JSON.stringify({sort_order: nextIndex})
        })));
        await this.refreshData();
        this.refreshView();
        this.setStatus('Node order updated.');
      } catch {
        this.setStatus('Could not reorder nodes.');
      }
    },

    async moveChoice(choiceId, direction) {
      const choices = [...(this.selectedNode?.choices ?? [])];
      const index = choices.findIndex(choice => Number(choice.id) === Number(choiceId));
      if (index < 0) return;
      const targetIndex = direction === 'up' ? index - 1 : index + 1;
      if (targetIndex < 0 || targetIndex >= choices.length) return;
      [choices[index], choices[targetIndex]] = [choices[targetIndex], choices[index]];
      this.setStatus('Reordering choices...');
      try {
        await Promise.all(choices.map((choice, nextIndex) => apiFetch(`/api/conversation-choices/${choice.id}`, {
          method: 'PATCH',
          body: JSON.stringify({sort_order: nextIndex})
        })));
        await this.refreshData();
        this.refreshView();
        this.setStatus('Choice order updated.');
      } catch {
        this.setStatus('Could not reorder choices.');
      }
    },

    getActionTree(target) {
      return target === 'choice'
        ? (this.selectedChoice?.actions ?? [])
        : (this.selectedNode?.enter_actions ?? []);
    },

    getSelectedActionStep(target) {
      return target === 'choice' ? this.choiceSelectedStep : this.nodeSelectedStep;
    },

    setSelectedActionStepId(target, stepId) {
      if (target === 'choice') this.choiceSelectedStepId = stepId || null;
      else this.nodeSelectedStepId = stepId || null;
    },

    clearSelectedActionStep(target) {
      this.setSelectedActionStepId(target, null);
      if (target === 'choice') this.choiceSelectedStep = null;
      else this.nodeSelectedStep = null;
    },

    async persistActionTree(target, nextTree, pendingStatus, successStatus) {
      const endpoint = target === 'choice'
        ? `/api/conversation-choices/${this.selectedChoice?.id}`
        : `/api/conversation-nodes/${this.selectedNode?.id}`;
      const field = target === 'choice' ? 'actions' : 'enter_actions';
      this.setStatus(pendingStatus);
      try {
        await apiFetch(endpoint, {
          method: 'PATCH',
          body: JSON.stringify({[field]: nextTree})
        });
        await this.refreshData();
        this.refreshView();
        this.setStatus(successStatus);
      } catch {
        this.setStatus('Could not save action steps.');
      }
    },

    async addActionStep(target, form) {
      const branchValue = form.elements.branch?.value ?? 'root';
      const nextTree = insertStep(this.getActionTree(target), branchValue, readActionStepForm(form));
      await this.persistActionTree(
        target,
        nextTree,
        'Adding action step...',
        'Action step added.'
      );
      form.reset();
      this.clearSelectedActionStep(target);
    },

    async updateActionStep(target, form) {
      const selectedStep = this.getSelectedActionStep(target);
      if (!selectedStep) return;
      const selectedStepId = target === 'choice' ? this.choiceSelectedStepId : this.nodeSelectedStepId;
      const updatedStep = {
        ...selectedStep,
        ...readActionStepForm(form),
        id: selectedStep.id,
        then_steps: selectedStep.then_steps ?? [],
        else_steps: selectedStep.else_steps ?? []
      };
      const nextTree = replaceStepById(this.getActionTree(target), selectedStepId, updatedStep);
      await this.persistActionTree(
        target,
        nextTree,
        'Updating action step...',
        'Action step updated.'
      );
      this.clearSelectedActionStep(target);
    },

    async removeActionStep(target, stepId) {
      const nextTree = removeStepById(this.getActionTree(target), stepId);
      await this.persistActionTree(
        target,
        nextTree,
        'Removing action step...',
        'Action step removed.'
      );
      if (String(target === 'choice' ? this.choiceSelectedStepId : this.nodeSelectedStepId) === String(stepId)) {
        this.clearSelectedActionStep(target);
      }
    },

    async moveActionStep(target, stepId, direction) {
      const nextTree = moveStepById(this.getActionTree(target), stepId, direction);
      await this.persistActionTree(
        target,
        nextTree,
        'Reordering action steps...',
        'Action step order updated.'
      );
    },

    updateActionFormVisibility(form) {
      if (!form) return;
      const selectedType = form.elements.action_type?.value ?? 'play_animation';
      const selectedProperty = form.elements.property?.value ?? 'visible';
      const targetScope = form.elements.target_scope?.value ?? 'object';
      const targetObjectMode = form.elements.target_object_mode?.value ?? 'static';
      const sceneObjectMode = form.elements.scene_object_mode?.value ?? 'static';
      const randomIdleScope = form.elements.random_idle_scope?.value ?? 'scene_object';
      form.querySelector('[data-action-type-help]')?.replaceChildren(
        document.createTextNode(actionTypeHelp(selectedType))
      );
      form.querySelectorAll('[data-visible-for]').forEach(field => {
        const visibleFor = (field.dataset.visibleFor ?? '').split(/\s+/);
        field.hidden = !visibleFor.includes(selectedType);
      });
      const targetObjectField = form.querySelector('[data-form-field="target-object"]');
      if (targetObjectField) {
        targetObjectField.hidden = !(
          ((selectedType === 'go_to_frame') && targetScope !== 'pickup_background' && targetScope !== 'background' && targetObjectMode === 'static')
          || (selectedType === 'set_object_property' && targetObjectMode === 'static')
        );
      }
      const frameIndexField = form.querySelector('[data-form-field="frame-index"]');
      if (frameIndexField) {
        frameIndexField.hidden = !(selectedType === 'go_to_frame' && targetScope !== 'pickup_background');
      }
      const animationField = form.querySelector('[data-form-field="animation"]');
      if (animationField) animationField.hidden = !(selectedType === 'play_animation' && targetObjectMode === 'static');
      const animationNameField = form.querySelector('[data-form-field="animation-name"]');
      if (animationNameField) animationNameField.hidden = !(selectedType === 'play_animation' && targetObjectMode !== 'static');
      const targetObjectModeField = form.querySelector('[data-form-field="target-object-mode"]');
      if (targetObjectModeField) {
        targetObjectModeField.hidden = !(
          selectedType === 'play_animation'
          || selectedType === 'set_object_property'
          || (selectedType === 'go_to_frame' && targetScope !== 'background')
        );
      }
      const sceneObjectModeField = form.querySelector('[data-form-field="scene-object-mode"]');
      if (sceneObjectModeField) sceneObjectModeField.hidden = !(selectedType === 'add_inventory_item' || selectedType === 'remove_inventory_item');
      const inventoryObjectField = form.querySelector('[data-form-field="inventory-object"]');
      if (inventoryObjectField) {
        inventoryObjectField.hidden = !(
          (selectedType === 'add_inventory_item' || selectedType === 'remove_inventory_item')
          && sceneObjectMode === 'static'
        );
      }
      form.querySelectorAll('[data-property-visible-for]').forEach(field => {
        const visibleFor = (field.dataset.propertyVisibleFor ?? '').split(/\s+/);
        field.hidden = selectedType !== 'set_object_property' || !visibleFor.includes(selectedProperty);
      });
      const randomIdleSceneObjectField = form.querySelector('[data-form-field="random-idle-scene-object"]');
      if (randomIdleSceneObjectField) {
        randomIdleSceneObjectField.hidden = !(['start_random_idle', 'stop_random_idle'].includes(selectedType) && randomIdleScope === 'scene_object');
      }
      const randomIdleCharacterField = form.querySelector('[data-form-field="random-idle-character"]');
      if (randomIdleCharacterField) {
        randomIdleCharacterField.hidden = !(['start_random_idle', 'stop_random_idle'].includes(selectedType) && randomIdleScope === 'character');
      }
      const randomIdleObjectAnimationsField = form.querySelector('[data-form-field="random-idle-object-animations"]');
      if (randomIdleObjectAnimationsField) {
        randomIdleObjectAnimationsField.hidden = !(selectedType === 'start_random_idle' && randomIdleScope === 'scene_object');
      }
      const randomIdleCharacterAnimationsField = form.querySelector('[data-form-field="random-idle-character-animations"]');
      if (randomIdleCharacterAnimationsField) {
        randomIdleCharacterAnimationsField.hidden = !(selectedType === 'start_random_idle' && randomIdleScope === 'character');
      }
      const randomIdleMinDelayField = form.querySelector('[data-form-field="random-idle-min-delay"]');
      if (randomIdleMinDelayField) randomIdleMinDelayField.hidden = selectedType !== 'start_random_idle';
      const randomIdleMaxDelayField = form.querySelector('[data-form-field="random-idle-max-delay"]');
      if (randomIdleMaxDelayField) randomIdleMaxDelayField.hidden = selectedType !== 'start_random_idle';
      const randomIdleAvoidRepeatField = form.querySelector('[data-form-field="random-idle-avoid-repeat"]');
      if (randomIdleAvoidRepeatField) randomIdleAvoidRepeatField.hidden = selectedType !== 'start_random_idle';
    }
  };

  try {
    await controller.refreshData();
  } catch {
    controller.conversationFound = false;
  }
  return controller;
};

function formatScriptLineLabel(line) {
  const path = Array.isArray(line.path_parts) && line.path_parts.length
    ? `${line.path_parts.join(' / ')} · `
    : '';
  const text = String(line.source_text || '').trim() || '(blank line)';
  return `#${line.line_id} ${path}${truncate(text, 80)}`;
}

function truncate(value, limit) {
  if (value.length <= limit) return value;
  return `${value.slice(0, Math.max(0, limit - 1))}…`;
}

function findNodeName(nodes, nodeId) {
  return nodes.find(node => Number(node.id) === Number(nodeId))?.name ?? `Node ${nodeId}`;
}

export {ConversationEditorCtrl};
