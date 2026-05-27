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
    nodeFormLineLabel: '',
    choiceFormLineLabel: '',
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
    nodeActionEditorStates: new Map(),
    choiceActionEditorStates: new Map(),
    nodeActionEditorState: null,
    choiceActionEditorState: null,
    canUndoNodeActionChange: false,
    canRedoNodeActionChange: false,
    canUndoChoiceActionChange: false,
    canRedoChoiceActionChange: false,
    nodeOrderState: null,
    choiceOrderStates: new Map(),
    choiceOrderState: null,
    canUndoNodeOrderChange: false,
    canRedoNodeOrderChange: false,
    canUndoChoiceOrderChange: false,
    canRedoChoiceOrderChange: false,
    nodeFormStates: new Map(),
    choiceFormStates: new Map(),
    nodeFormState: null,
    choiceFormState: null,
    nodeFormStatus: '',
    choiceFormStatus: '',
    hasNodeFormSaveError: false,
    hasChoiceFormSaveError: false,
    newNodeDraft: createBlankNodeDraft(),
    newChoiceDraft: createBlankChoiceDraft(),
    nodeOrderStatus: '',
    choiceOrderStatus: '',
    hasNodeOrderSaveError: false,
    hasChoiceOrderSaveError: false,
    nodeActionTreeStatus: '',
    choiceActionTreeStatus: '',
    hasNodeActionTreeSaveError: false,
    hasChoiceActionTreeSaveError: false,
    globalHistoryUndoStack: [],
    globalHistoryRedoStack: [],
    canUndoGlobalHistory: false,
    canRedoGlobalHistory: false,
    lastHistoryLabel: '',
    status: '',
    unloadHandlers: [],

    async postLoad() {
      this.root = document.querySelector('[data-conversation-editor-page]');
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
      this.syncActionEditorStatesFromServer();
      this.syncOrderEditorStatesFromServer();
      this.syncFormEditorStatesFromServer();
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
      const orderedNodeIds = this.ensureNodeOrderState(
        (this.conversation?.nodes ?? []).map(node => Number(node.id))
      ).workingIds;
      const orderedNodes = orderedNodeIds
        .map(nodeId => (this.conversation?.nodes ?? []).find(node => Number(node.id) === Number(nodeId)))
        .filter(Boolean);
      const nodes = orderedNodes.map(node => {
        const nodeFormState = this.ensureNodeFormState(node);
        const line = nodeFormState.workingValue.script_line_id
          ? this.scriptLineOptions.find(option => Number(option.id) === Number(nodeFormState.workingValue.script_line_id))
          : null;
        const nodeActionEditorState = this.ensureActionEditorState('node', node.id, node.enter_actions ?? []);
        const linePreview = line?.label || node?.script_line?.source_text || '';
        const orderedChoiceIds = this.ensureChoiceOrderState(
          node.id,
          (node.choices ?? []).map(choice => Number(choice.id))
        ).workingIds;
        const orderedChoices = orderedChoiceIds
          .map(choiceId => (node.choices ?? []).find(choice => Number(choice.id) === Number(choiceId)))
          .filter(Boolean);
        const choices = orderedChoices.map(choice => {
          const choiceWithDraft = this.applyChoiceFormStateToChoice(node.id, choice);
          return {
          ...choiceWithDraft,
          actions: structuredClone(
            this.ensureActionEditorState('choice', choice.id, choice.actions ?? []).workingActionTree
          ),
          isSelected: Number(choice.id) === Number(this.selectedChoiceId),
          linePreview: this.getChoiceLinePreview(node.id, choice),
          destinationLabel: choiceWithDraft.end_conversation
            ? 'Ends conversation'
            : choiceWithDraft.next_node_id
              ? `Next: ${findNodeName(this.conversation?.nodes ?? [], choiceWithDraft.next_node_id)}`
              : 'No next node set'
        };});
        return {
          ...this.applyNodeFormStateToNode(node),
          enter_actions: structuredClone(nodeActionEditorState.workingActionTree),
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
      this.nodeFormState = this.selectedNode ? this.ensureNodeFormState(this.selectedNode) : null;
      this.nodeActionEditorState = this.selectedNode
        ? this.ensureActionEditorState('node', this.selectedNode.id, this.selectedNode.enter_actions ?? [])
        : null;
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
      this.choiceFormState = this.selectedChoice ? this.ensureChoiceFormState(this.selectedNode.id, this.selectedChoice) : null;
      this.choiceActionEditorState = this.selectedChoice
        ? this.ensureActionEditorState('choice', this.selectedChoice.id, this.selectedChoice.actions ?? [])
        : null;
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
      this.canUndoNodeActionChange = Boolean(this.nodeActionEditorState?.undoStack?.length);
      this.canRedoNodeActionChange = Boolean(this.nodeActionEditorState?.redoStack?.length);
      this.canUndoChoiceActionChange = Boolean(this.choiceActionEditorState?.undoStack?.length);
      this.canRedoChoiceActionChange = Boolean(this.choiceActionEditorState?.redoStack?.length);
      this.hasNodeActionTreeSaveError = Boolean(this.nodeActionEditorState?.error);
      this.hasChoiceActionTreeSaveError = Boolean(this.choiceActionEditorState?.error);
      this.hasNodeFormSaveError = Boolean(this.nodeFormState?.error);
      this.hasChoiceFormSaveError = Boolean(this.choiceFormState?.error);
      this.nodeActionTreeStatus = formatActionTreeStatus(this.nodeActionEditorState);
      this.choiceActionTreeStatus = formatActionTreeStatus(this.choiceActionEditorState);
      this.nodeFormStatus = formatFormStatus(this.nodeFormState, 'node');
      this.choiceFormStatus = formatFormStatus(this.choiceFormState, 'choice');
      const nodeFormDraft = this.selectedNode ? this.nodeFormState?.workingValue : this.newNodeDraft;
      const choiceFormDraft = this.selectedChoice ? this.choiceFormState?.workingValue : this.newChoiceDraft;
      this.nodeFormLineLabel = this.findScriptLineLabel(nodeFormDraft?.script_line_id);
      this.choiceFormLineLabel = this.findScriptLineLabel(choiceFormDraft?.script_line_id);
      this.choiceOrderState = this.selectedNode
        ? this.ensureChoiceOrderState(this.selectedNode.id, (this.selectedNode.choices ?? []).map(choice => Number(choice.id)))
        : null;
      this.canUndoNodeOrderChange = Boolean(this.nodeOrderState?.undoStack?.length);
      this.canRedoNodeOrderChange = Boolean(this.nodeOrderState?.redoStack?.length);
      this.canUndoChoiceOrderChange = Boolean(this.choiceOrderState?.undoStack?.length);
      this.canRedoChoiceOrderChange = Boolean(this.choiceOrderState?.redoStack?.length);
      this.hasNodeOrderSaveError = Boolean(this.nodeOrderState?.error);
      this.hasChoiceOrderSaveError = Boolean(this.choiceOrderState?.error);
      this.nodeOrderStatus = formatActionTreeStatus(this.nodeOrderState);
      this.choiceOrderStatus = formatActionTreeStatus(this.choiceOrderState);
      this.canUndoGlobalHistory = this.globalHistoryUndoStack.length > 0;
      this.canRedoGlobalHistory = this.globalHistoryRedoStack.length > 0;
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
        const nodeDraft = this.selectedNode ? this.nodeFormState?.workingValue : this.newNodeDraft;
        nodeForm.elements.node_id.value = this.selectedNode?.id ?? '';
        nodeForm.elements.name.value = nodeDraft?.name ?? '';
        nodeForm.elements.script_line_id.value = nodeDraft?.script_line_id ?? '';
        nodeForm.elements.speaker_character_id.value = nodeDraft?.speaker_character_id ?? '';
      }
      const choiceForm = this.root?.querySelector('[data-choice-form]');
      if (choiceForm) {
        const choiceDraft = this.selectedChoice ? this.choiceFormState?.workingValue : this.newChoiceDraft;
        choiceForm.elements.choice_id.value = this.selectedChoice?.id ?? '';
        choiceForm.elements.script_line_id.value = choiceDraft?.script_line_id ?? '';
        choiceForm.elements.next_node_id.value = choiceDraft?.next_node_id ?? '';
        choiceForm.elements.end_conversation.checked = Boolean(choiceDraft?.end_conversation);
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
        this.newNodeDraft = createBlankNodeDraft();
        this.newChoiceDraft = createBlankChoiceDraft();
        this.prepareState();
        this.refreshView();
        return;
      }
      if (event.target.closest('[data-action="clear-choice-selection"]')) {
        this.selectedChoiceId = null;
        this.suppressChoiceAutoSelect = true;
        this.newChoiceDraft = createBlankChoiceDraft();
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
      const undoGlobalHistory = event.target.closest('[data-action="undo-conversation-change"]');
      if (undoGlobalHistory) {
        await this.undoGlobalHistoryChange();
        return;
      }
      const redoGlobalHistory = event.target.closest('[data-action="redo-conversation-change"]');
      if (redoGlobalHistory) {
        await this.redoGlobalHistoryChange();
        return;
      }
    },

    async onKeyDown(event) {
      if (!(event.ctrlKey || event.metaKey)) return;
      if (event.altKey) return;
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
      const nodeForm = event.target.closest('[data-node-form]');
      if (nodeForm && !event.target.closest('[data-node-line-search-form]')) {
        if (this.selectedNode) {
          this.captureNodeFormUndoSnapshot();
          this.updateNodeFormDraft(nodeForm);
          this.prepareState();
          this.refreshView();
          this.recordGlobalHistoryEntry({
            label: 'Edit node',
            undo: () => this.undoNodeFormChange(this.selectedNode.id),
            redo: () => this.redoNodeFormChange(this.selectedNode.id)
          });
          void this.persistNodeForm(this.selectedNode.id);
        } else {
          this.newNodeDraft = this.readNodeFormDraft(nodeForm);
        }
        return;
      }
      const choiceForm = event.target.closest('[data-choice-form]');
      if (choiceForm && !event.target.closest('[data-choice-line-search-form]')) {
        if (this.selectedChoice && this.selectedNode) {
          this.captureChoiceFormUndoSnapshot(this.selectedNode.id, this.selectedChoice.id);
          this.updateChoiceFormDraft(this.selectedNode.id, this.selectedChoice.id, choiceForm);
          this.prepareState();
          this.refreshView();
          this.recordGlobalHistoryEntry({
            label: 'Edit choice',
            undo: () => this.undoChoiceFormChange(this.selectedNode.id, this.selectedChoice.id),
            redo: () => this.redoChoiceFormChange(this.selectedNode.id, this.selectedChoice.id)
          });
          void this.persistChoiceForm(this.selectedNode.id, this.selectedChoice.id);
        } else {
          this.newChoiceDraft = this.readChoiceFormDraft(choiceForm);
        }
        return;
      }
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
        this.newNodeDraft = createBlankNodeDraft();
        this.newChoiceDraft = createBlankChoiceDraft();
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
        this.newChoiceDraft = createBlankChoiceDraft();
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
      if (target === 'node') {
        if (this.selectedNode) {
          this.captureNodeFormUndoSnapshot();
          this.updateNodeFormDraft(form);
          this.prepareState();
          this.refreshView();
          this.recordGlobalHistoryEntry({
            label: lineId ? 'Set node line' : 'Clear node line',
            undo: () => this.undoNodeFormChange(this.selectedNode.id),
            redo: () => this.redoNodeFormChange(this.selectedNode.id)
          });
          void this.persistNodeForm(this.selectedNode.id);
        } else {
          this.newNodeDraft = this.readNodeFormDraft(form);
          this.refreshView();
        }
      }
      if (target === 'choice') {
        if (this.selectedChoice && this.selectedNode) {
          this.captureChoiceFormUndoSnapshot(this.selectedNode.id, this.selectedChoice.id);
          this.updateChoiceFormDraft(this.selectedNode.id, this.selectedChoice.id, form);
          this.prepareState();
          this.refreshView();
          this.recordGlobalHistoryEntry({
            label: lineId ? 'Set choice line' : 'Clear choice line',
            undo: () => this.undoChoiceFormChange(this.selectedNode.id, this.selectedChoice.id),
            redo: () => this.redoChoiceFormChange(this.selectedNode.id, this.selectedChoice.id)
          });
          void this.persistChoiceForm(this.selectedNode.id, this.selectedChoice.id);
        } else {
          this.newChoiceDraft = this.readChoiceFormDraft(form);
          this.refreshView();
        }
      }
      if (target === 'node') this.nodeScriptSearchResults = [];
      else this.choiceScriptSearchResults = [];
      this.refreshView();
    },

    ensureNodeFormState(node) {
      const key = Number(node?.id);
      let state = this.nodeFormStates.get(key);
      if (!state) {
        state = createFormEditorState(this.extractNodeFormValue(node));
        this.nodeFormStates.set(key, state);
      }
      return state;
    },

    ensureChoiceFormState(nodeId, choice) {
      const key = Number(choice?.id);
      let state = this.choiceFormStates.get(key);
      if (!state) {
        state = createFormEditorState(this.extractChoiceFormValue(choice));
        state.nodeId = Number(nodeId);
        this.choiceFormStates.set(key, state);
      }
      return state;
    },

    syncFormEditorStatesFromServer() {
      const nextNodeStates = new Map();
      const nextChoiceStates = new Map();
      for (const node of this.conversation?.nodes ?? []) {
        const nodeId = Number(node.id);
        const serverNodeValue = this.extractNodeFormValue(node);
        const existingNodeState = this.nodeFormStates.get(nodeId);
        if (existingNodeState?.isDirty || existingNodeState?.isSaving) nextNodeStates.set(nodeId, existingNodeState);
        else nextNodeStates.set(nodeId, createFormEditorState(serverNodeValue));
        for (const choice of node.choices ?? []) {
          const choiceId = Number(choice.id);
          const serverChoiceValue = this.extractChoiceFormValue(choice);
          const existingChoiceState = this.choiceFormStates.get(choiceId);
          if (existingChoiceState?.isDirty || existingChoiceState?.isSaving) {
            existingChoiceState.nodeId = nodeId;
            nextChoiceStates.set(choiceId, existingChoiceState);
          } else {
            const state = createFormEditorState(serverChoiceValue);
            state.nodeId = nodeId;
            nextChoiceStates.set(choiceId, state);
          }
        }
      }
      this.nodeFormStates = nextNodeStates;
      this.choiceFormStates = nextChoiceStates;
    },

    extractNodeFormValue(node) {
      return {
        name: String(node?.name ?? ''),
        script_line_id: node?.script_line_id ? Number(node.script_line_id) : null,
        speaker_character_id: node?.speaker_character_id ? Number(node.speaker_character_id) : null
      };
    },

    extractChoiceFormValue(choice) {
      return {
        script_line_id: choice?.script_line_id ? Number(choice.script_line_id) : null,
        next_node_id: choice?.next_node_id ? Number(choice.next_node_id) : null,
        end_conversation: Boolean(choice?.end_conversation)
      };
    },

    readNodeFormDraft(form) {
      return {
        name: String(form.elements.name.value || ''),
        script_line_id: form.elements.script_line_id.value ? Number(form.elements.script_line_id.value) : null,
        speaker_character_id: form.elements.speaker_character_id.value ? Number(form.elements.speaker_character_id.value) : null
      };
    },

    readChoiceFormDraft(form) {
      return {
        script_line_id: form.elements.script_line_id.value ? Number(form.elements.script_line_id.value) : null,
        next_node_id: form.elements.next_node_id.value ? Number(form.elements.next_node_id.value) : null,
        end_conversation: Boolean(form.elements.end_conversation.checked)
      };
    },

    updateNodeFormDraft(form) {
      if (!this.selectedNode) return;
      const editorState = this.ensureNodeFormState(this.selectedNode);
      editorState.workingValue = this.readNodeFormDraft(form);
      editorState.isDirty = !formValuesEqual(editorState.workingValue, editorState.baseValue);
      editorState.mutationVersion += 1;
      editorState.error = '';
    },

    updateChoiceFormDraft(nodeId, choiceId, form) {
      const editorState = this.ensureChoiceFormState(nodeId, {id: choiceId, ...this.readChoiceFormDraft(form)});
      editorState.workingValue = this.readChoiceFormDraft(form);
      editorState.isDirty = !formValuesEqual(editorState.workingValue, editorState.baseValue);
      editorState.mutationVersion += 1;
      editorState.error = '';
    },

    applyNodeFormStateToNode(node) {
      const editorState = this.ensureNodeFormState(node);
      const workingValue = editorState.workingValue;
      const line = workingValue.script_line_id
        ? this.scriptLineOptions.find(option => Number(option.id) === Number(workingValue.script_line_id))
        : null;
      return {
        ...node,
        name: workingValue.name || 'Untitled node',
        script_line_id: workingValue.script_line_id,
        speaker_character_id: workingValue.speaker_character_id,
        scriptLineLabel: line?.label ?? (node?.script_line?.source_text || ''),
        linePreview: line?.label ?? (node?.script_line?.source_text || '')
      };
    },

    applyChoiceFormStateToChoice(nodeId, choice) {
      const editorState = this.ensureChoiceFormState(nodeId, choice);
      const workingValue = editorState.workingValue;
      return {
        ...choice,
        script_line_id: workingValue.script_line_id,
        next_node_id: workingValue.next_node_id,
        end_conversation: workingValue.end_conversation
      };
    },

    getChoiceLinePreview(nodeId, choice) {
      const editorState = this.ensureChoiceFormState(nodeId, choice);
      return this.findScriptLineLabel(editorState.workingValue.script_line_id)
        || choice?.script_line?.source_text
        || 'No player line selected';
    },

    findScriptLineLabel(lineId) {
      if (!lineId) return '';
      return this.scriptLineOptions.find(option => Number(option.id) === Number(lineId))?.label ?? '';
    },

    async persistNodeForm(nodeId) {
      const editorState = this.ensureNodeFormState({id: nodeId});
      editorState.saveQueued = true;
      if (editorState.isSaving) {
        this.prepareState();
        this.refreshView();
        return;
      }
      while (editorState.saveQueued) {
        editorState.saveQueued = false;
        if (!editorState.isDirty) break;
        const payloadValue = structuredClone(editorState.workingValue);
        const saveVersion = editorState.mutationVersion;
        editorState.isSaving = true;
        editorState.error = '';
        this.prepareState();
        this.refreshView();
        try {
          const saved = await apiFetch(`/api/conversation-nodes/${nodeId}`, {
            method: 'PATCH',
            body: JSON.stringify({
              name: String(payloadValue.name || '').trim(),
              script_line_id: payloadValue.script_line_id,
              clear_script_line_id: !payloadValue.script_line_id,
              speaker_character_id: payloadValue.speaker_character_id,
              clear_speaker_character_id: !payloadValue.speaker_character_id
            })
          });
          editorState.baseValue = this.extractNodeFormValue(saved);
          if (editorState.mutationVersion === saveVersion) {
            editorState.workingValue = structuredClone(editorState.baseValue);
            editorState.isDirty = false;
          } else {
            editorState.isDirty = !formValuesEqual(editorState.workingValue, editorState.baseValue);
            editorState.saveQueued = editorState.isDirty || editorState.saveQueued;
          }
          editorState.error = '';
        } catch {
          editorState.workingValue = structuredClone(editorState.baseValue);
          editorState.isDirty = false;
          editorState.error = 'Could not save the latest node changes. Reverted to the last saved version.';
          editorState.saveQueued = false;
        } finally {
          editorState.isSaving = false;
          this.prepareState();
          this.refreshView();
        }
      }
    },

    async persistChoiceForm(nodeId, choiceId) {
      const editorState = this.ensureChoiceFormState(nodeId, {id: choiceId});
      editorState.saveQueued = true;
      if (editorState.isSaving) {
        this.prepareState();
        this.refreshView();
        return;
      }
      while (editorState.saveQueued) {
        editorState.saveQueued = false;
        if (!editorState.isDirty) break;
        const payloadValue = structuredClone(editorState.workingValue);
        const saveVersion = editorState.mutationVersion;
        editorState.isSaving = true;
        editorState.error = '';
        this.prepareState();
        this.refreshView();
        try {
          const saved = await apiFetch(`/api/conversation-choices/${choiceId}`, {
            method: 'PATCH',
            body: JSON.stringify({
              script_line_id: payloadValue.script_line_id,
              clear_script_line_id: !payloadValue.script_line_id,
              next_node_id: payloadValue.next_node_id,
              clear_next_node_id: !payloadValue.next_node_id,
              end_conversation: Boolean(payloadValue.end_conversation)
            })
          });
          editorState.baseValue = this.extractChoiceFormValue(saved);
          if (editorState.mutationVersion === saveVersion) {
            editorState.workingValue = structuredClone(editorState.baseValue);
            editorState.isDirty = false;
          } else {
            editorState.isDirty = !formValuesEqual(editorState.workingValue, editorState.baseValue);
            editorState.saveQueued = editorState.isDirty || editorState.saveQueued;
          }
          editorState.error = '';
        } catch {
          editorState.workingValue = structuredClone(editorState.baseValue);
          editorState.isDirty = false;
          editorState.error = 'Could not save the latest choice changes. Reverted to the last saved version.';
          editorState.saveQueued = false;
        } finally {
          editorState.isSaving = false;
          this.prepareState();
          this.refreshView();
        }
      }
    },

    async moveNode(nodeId, direction) {
      const editorState = this.ensureNodeOrderState((this.conversation?.nodes ?? []).map(node => Number(node.id)));
      const orderedIds = [...editorState.workingIds];
      const index = orderedIds.findIndex(id => Number(id) === Number(nodeId));
      if (index < 0) return;
      const targetIndex = direction === 'up' ? index - 1 : index + 1;
      if (targetIndex < 0 || targetIndex >= orderedIds.length) return;
      [orderedIds[index], orderedIds[targetIndex]] = [orderedIds[targetIndex], orderedIds[index]];
      editorState.undoStack.push([...editorState.workingIds]);
      if (editorState.undoStack.length > 100) editorState.undoStack.shift();
      editorState.redoStack = [];
      editorState.mutationVersion += 1;
      editorState.error = '';
      this.setNodeOrder(editorState, orderedIds);
      this.prepareState();
      this.refreshView();
      this.recordGlobalHistoryEntry({
        label: 'Reorder nodes',
        undo: () => this.undoNodeOrderChange(),
        redo: () => this.redoNodeOrderChange()
      });
      void this.persistNodeOrder();
    },

    async moveChoice(choiceId, direction) {
      if (!this.selectedNode) return;
      const editorState = this.ensureChoiceOrderState(this.selectedNode.id, (this.selectedNode.choices ?? []).map(choice => Number(choice.id)));
      const orderedIds = [...editorState.workingIds];
      const index = orderedIds.findIndex(id => Number(id) === Number(choiceId));
      if (index < 0) return;
      const targetIndex = direction === 'up' ? index - 1 : index + 1;
      if (targetIndex < 0 || targetIndex >= orderedIds.length) return;
      [orderedIds[index], orderedIds[targetIndex]] = [orderedIds[targetIndex], orderedIds[index]];
      editorState.undoStack.push([...editorState.workingIds]);
      if (editorState.undoStack.length > 100) editorState.undoStack.shift();
      editorState.redoStack = [];
      editorState.mutationVersion += 1;
      editorState.error = '';
      this.setChoiceOrder(this.selectedNode.id, editorState, orderedIds);
      this.prepareState();
      this.refreshView();
      this.recordGlobalHistoryEntry({
        label: 'Reorder choices',
        undo: () => this.undoChoiceOrderChange(this.selectedNode.id),
        redo: () => this.redoChoiceOrderChange(this.selectedNode.id)
      });
      void this.persistChoiceOrder(this.selectedNode.id);
    },

    ensureNodeOrderState(nodeIds) {
      if (!this.nodeOrderState) this.nodeOrderState = createOrderEditorState(nodeIds ?? []);
      return this.nodeOrderState;
    },

    ensureChoiceOrderState(nodeId, choiceIds) {
      const key = Number(nodeId);
      let state = this.choiceOrderStates.get(key);
      if (!state) {
        state = createOrderEditorState(choiceIds ?? []);
        this.choiceOrderStates.set(key, state);
      }
      return state;
    },

    syncOrderEditorStatesFromServer() {
      const serverNodeIds = (this.conversation?.nodes ?? []).map(node => Number(node.id));
      if (!this.nodeOrderState || (!this.nodeOrderState.isDirty && !this.nodeOrderState.isSaving)) {
        this.nodeOrderState = createOrderEditorState(serverNodeIds);
      }
      const nextChoiceOrderStates = new Map();
      for (const node of this.conversation?.nodes ?? []) {
        const nodeId = Number(node.id);
        const choiceIds = (node.choices ?? []).map(choice => Number(choice.id));
        const existing = this.choiceOrderStates.get(nodeId);
        if (existing?.isDirty || existing?.isSaving) nextChoiceOrderStates.set(nodeId, existing);
        else nextChoiceOrderStates.set(nodeId, createOrderEditorState(choiceIds));
      }
      this.choiceOrderStates = nextChoiceOrderStates;
    },

    setNodeOrder(editorState, orderedIds) {
      editorState.workingIds = [...orderedIds];
      editorState.isDirty = !orderArraysEqual(editorState.workingIds, editorState.baseIds);
      const nodeById = new Map((this.conversation?.nodes ?? []).map(node => [Number(node.id), node]));
      this.conversation.nodes = orderedIds.map(id => nodeById.get(Number(id))).filter(Boolean);
    },

    setChoiceOrder(nodeId, editorState, orderedIds) {
      editorState.workingIds = [...orderedIds];
      editorState.isDirty = !orderArraysEqual(editorState.workingIds, editorState.baseIds);
      const node = (this.conversation?.nodes ?? []).find(item => Number(item.id) === Number(nodeId));
      if (!node) return;
      const choiceById = new Map((node.choices ?? []).map(choice => [Number(choice.id), choice]));
      node.choices = orderedIds.map(id => choiceById.get(Number(id))).filter(Boolean);
    },

    async persistNodeOrder() {
      const editorState = this.ensureNodeOrderState((this.conversation?.nodes ?? []).map(node => Number(node.id)));
      editorState.saveQueued = true;
      if (editorState.isSaving) {
        this.prepareState();
        this.refreshView();
        return;
      }
      while (editorState.saveQueued) {
        editorState.saveQueued = false;
        if (!editorState.isDirty) break;
        const orderedIds = [...editorState.workingIds];
        const saveVersion = editorState.mutationVersion;
        editorState.isSaving = true;
        editorState.error = '';
        this.prepareState();
        this.refreshView();
        try {
          await Promise.all(orderedIds.map((id, nextIndex) => apiFetch(`/api/conversation-nodes/${id}`, {
            method: 'PATCH',
            body: JSON.stringify({sort_order: nextIndex})
          })));
          editorState.baseIds = [...orderedIds];
          if (editorState.mutationVersion === saveVersion) editorState.isDirty = false;
          else editorState.saveQueued = editorState.saveQueued || editorState.isDirty;
          editorState.error = '';
        } catch {
          editorState.workingIds = [...editorState.baseIds];
          editorState.isDirty = false;
          editorState.redoStack = [];
          editorState.error = 'Could not save the latest node order. Reverted to the last saved version.';
          this.setNodeOrder(editorState, editorState.workingIds);
        } finally {
          editorState.isSaving = false;
          this.prepareState();
          this.refreshView();
        }
      }
    },

    async persistChoiceOrder(nodeId) {
      const editorState = this.ensureChoiceOrderState(nodeId, (this.selectedNode?.choices ?? []).map(choice => Number(choice.id)));
      editorState.saveQueued = true;
      if (editorState.isSaving) {
        this.prepareState();
        this.refreshView();
        return;
      }
      while (editorState.saveQueued) {
        editorState.saveQueued = false;
        if (!editorState.isDirty) break;
        const orderedIds = [...editorState.workingIds];
        const saveVersion = editorState.mutationVersion;
        editorState.isSaving = true;
        editorState.error = '';
        this.prepareState();
        this.refreshView();
        try {
          await Promise.all(orderedIds.map((id, nextIndex) => apiFetch(`/api/conversation-choices/${id}`, {
            method: 'PATCH',
            body: JSON.stringify({sort_order: nextIndex})
          })));
          editorState.baseIds = [...orderedIds];
          if (editorState.mutationVersion === saveVersion) editorState.isDirty = false;
          else editorState.saveQueued = editorState.saveQueued || editorState.isDirty;
          editorState.error = '';
        } catch {
          editorState.workingIds = [...editorState.baseIds];
          editorState.isDirty = false;
          editorState.redoStack = [];
          editorState.error = 'Could not save the latest choice order. Reverted to the last saved version.';
          this.setChoiceOrder(nodeId, editorState, editorState.workingIds);
        } finally {
          editorState.isSaving = false;
          this.prepareState();
          this.refreshView();
        }
      }
    },

    async undoNodeOrderChange() {
      const editorState = this.nodeOrderState;
      if (!editorState?.undoStack?.length) return;
      const previous = editorState.undoStack.pop();
      editorState.redoStack.push([...editorState.workingIds]);
      editorState.mutationVersion += 1;
      editorState.error = '';
      this.setNodeOrder(editorState, previous);
      this.prepareState();
      this.refreshView();
      void this.persistNodeOrder();
    },

    async redoNodeOrderChange() {
      const editorState = this.nodeOrderState;
      if (!editorState?.redoStack?.length) return;
      const nextOrder = editorState.redoStack.pop();
      editorState.undoStack.push([...editorState.workingIds]);
      editorState.mutationVersion += 1;
      editorState.error = '';
      this.setNodeOrder(editorState, nextOrder);
      this.prepareState();
      this.refreshView();
      void this.persistNodeOrder();
    },

    async undoChoiceOrderChange(nodeId = this.selectedNode?.id) {
      if (!nodeId) return;
      const node = (this.conversation?.nodes ?? []).find(item => Number(item.id) === Number(nodeId));
      const editorState = this.ensureChoiceOrderState(nodeId, (node?.choices ?? []).map(choice => Number(choice.id)));
      if (!editorState.undoStack.length) return;
      const previous = editorState.undoStack.pop();
      editorState.redoStack.push([...editorState.workingIds]);
      editorState.mutationVersion += 1;
      editorState.error = '';
      this.setChoiceOrder(nodeId, editorState, previous);
      this.prepareState();
      this.refreshView();
      void this.persistChoiceOrder(nodeId);
    },

    async redoChoiceOrderChange(nodeId = this.selectedNode?.id) {
      if (!nodeId) return;
      const node = (this.conversation?.nodes ?? []).find(item => Number(item.id) === Number(nodeId));
      const editorState = this.ensureChoiceOrderState(nodeId, (node?.choices ?? []).map(choice => Number(choice.id)));
      if (!editorState.redoStack.length) return;
      const nextOrder = editorState.redoStack.pop();
      editorState.undoStack.push([...editorState.workingIds]);
      editorState.mutationVersion += 1;
      editorState.error = '';
      this.setChoiceOrder(nodeId, editorState, nextOrder);
      this.prepareState();
      this.refreshView();
      void this.persistChoiceOrder(nodeId);
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

    async addActionStep(target, form) {
      const branchValue = form.elements.branch?.value ?? 'root';
      const nextTree = insertStep(this.getActionTree(target), branchValue, withLocalStepIds(readActionStepForm(form)));
      this.applyLocalActionTreeChange(target, nextTree);
      form.reset();
      this.clearSelectedActionStep(target);
      this.prepareState();
      this.refreshView();
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
      this.applyLocalActionTreeChange(target, nextTree);
      this.clearSelectedActionStep(target);
      this.prepareState();
      this.refreshView();
    },

    async removeActionStep(target, stepId) {
      const nextTree = removeStepById(this.getActionTree(target), stepId);
      this.applyLocalActionTreeChange(target, nextTree);
      if (String(target === 'choice' ? this.choiceSelectedStepId : this.nodeSelectedStepId) === String(stepId)) {
        this.clearSelectedActionStep(target);
      }
      this.prepareState();
      this.refreshView();
    },

    async moveActionStep(target, stepId, direction) {
      const nextTree = moveStepById(this.getActionTree(target), stepId, direction);
      this.applyLocalActionTreeChange(target, nextTree);
      this.prepareState();
      this.refreshView();
    },

    ensureActionEditorState(target, id, actionTree) {
      const states = target === 'choice' ? this.choiceActionEditorStates : this.nodeActionEditorStates;
      const key = Number(id);
      let state = states.get(key);
      if (!state) {
        state = createTreeEditorState(actionTree ?? []);
        states.set(key, state);
        return state;
      }
      return state;
    },

    syncActionEditorStatesFromServer() {
      const nextNodeStates = new Map();
      const nextChoiceStates = new Map();
      for (const node of this.conversation?.nodes ?? []) {
        const nodeId = Number(node.id);
        const serverTree = structuredClone(node.enter_actions ?? []);
        const existingNodeState = this.nodeActionEditorStates.get(nodeId);
        if (existingNodeState?.isDirty || existingNodeState?.isSaving) nextNodeStates.set(nodeId, existingNodeState);
        else nextNodeStates.set(nodeId, createTreeEditorState(serverTree));
        for (const choice of node.choices ?? []) {
          const choiceId = Number(choice.id);
          const choiceTree = structuredClone(choice.actions ?? []);
          const existingChoiceState = this.choiceActionEditorStates.get(choiceId);
          if (existingChoiceState?.isDirty || existingChoiceState?.isSaving) nextChoiceStates.set(choiceId, existingChoiceState);
          else nextChoiceStates.set(choiceId, createTreeEditorState(choiceTree));
        }
      }
      this.nodeActionEditorStates = nextNodeStates;
      this.choiceActionEditorStates = nextChoiceStates;
    },

    setWorkingActionTree(target, id, nextTree) {
      const editorState = this.ensureActionEditorState(target, id, nextTree);
      editorState.workingActionTree = structuredClone(nextTree);
      editorState.isDirty = !treesEqual(editorState.workingActionTree, editorState.baseActionTree);
      if (target === 'choice') {
        const node = this.conversation?.nodes?.find(item => Number(item.id) === Number(this.selectedNodeId));
        const choice = node?.choices?.find(item => Number(item.id) === Number(id));
        if (choice) choice.actions = structuredClone(editorState.workingActionTree);
      } else {
        const node = this.conversation?.nodes?.find(item => Number(item.id) === Number(id));
        if (node) node.enter_actions = structuredClone(editorState.workingActionTree);
      }
    },

    applyLocalActionTreeChange(target, nextTree) {
      const selected = target === 'choice' ? this.selectedChoice : this.selectedNode;
      if (!selected) return;
      const editorState = this.ensureActionEditorState(target, selected.id, this.getActionTree(target));
      editorState.undoStack.push(structuredClone(editorState.workingActionTree));
      if (editorState.undoStack.length > 100) editorState.undoStack.shift();
      editorState.redoStack = [];
      editorState.mutationVersion += 1;
      editorState.error = '';
      this.setWorkingActionTree(target, selected.id, withLocalStepIds(nextTree));
      this.recordGlobalHistoryEntry({
        label: target === 'choice' ? 'Edit choice actions' : 'Edit node actions',
        undo: () => this.undoActionTreeChange(target, selected.id),
        redo: () => this.redoActionTreeChange(target, selected.id)
      });
      void this.persistActionTree(target, selected.id);
    },

    async persistActionTree(target, id) {
      const editorState = this.ensureActionEditorState(target, id, []);
      editorState.saveQueued = true;
      if (editorState.isSaving) {
        this.prepareState();
        this.refreshView();
        return;
      }
      while (editorState.saveQueued) {
        editorState.saveQueued = false;
        if (!editorState.isDirty) break;
        const endpoint = target === 'choice'
          ? `/api/conversation-choices/${id}`
          : `/api/conversation-nodes/${id}`;
        const field = target === 'choice' ? 'actions' : 'enter_actions';
        const payloadTree = structuredClone(editorState.workingActionTree);
        const saveVersion = editorState.mutationVersion;
        editorState.isSaving = true;
        editorState.error = '';
        this.prepareState();
        this.refreshView();
        try {
          const saved = await apiFetch(endpoint, {
            method: 'PATCH',
            body: JSON.stringify({[field]: payloadTree})
          });
          const savedTree = structuredClone(saved[field] ?? []);
          editorState.baseActionTree = structuredClone(savedTree);
          if (editorState.mutationVersion === saveVersion) {
            editorState.workingActionTree = structuredClone(savedTree);
            editorState.isDirty = false;
          } else {
            editorState.isDirty = !treesEqual(editorState.workingActionTree, editorState.baseActionTree);
            editorState.saveQueued = editorState.isDirty || editorState.saveQueued;
          }
          editorState.error = '';
          this.setWorkingActionTree(target, id, editorState.workingActionTree);
        } catch {
          editorState.workingActionTree = structuredClone(editorState.baseActionTree);
          editorState.isDirty = false;
          editorState.error = 'Could not save the latest step changes. Reverted to the last saved version.';
          editorState.redoStack = [];
          this.setWorkingActionTree(target, id, editorState.workingActionTree);
          this.clearSelectedActionStep(target);
          editorState.saveQueued = false;
        } finally {
          editorState.isSaving = false;
          this.prepareState();
          this.refreshView();
        }
      }
    },

    async undoActionTreeChange(target, id = target === 'choice' ? this.selectedChoice?.id : this.selectedNode?.id) {
      if (!id) return;
      const editorState = this.ensureActionEditorState(target, id, []);
      if (!editorState || !editorState.undoStack.length) return;
      const previousTree = editorState.undoStack.pop();
      editorState.redoStack.push(structuredClone(editorState.workingActionTree));
      editorState.mutationVersion += 1;
      editorState.error = '';
      this.setWorkingActionTree(target, id, previousTree);
      this.clearSelectedActionStep(target);
      this.prepareState();
      this.refreshView();
      void this.persistActionTree(target, id);
    },

    async redoActionTreeChange(target, id = target === 'choice' ? this.selectedChoice?.id : this.selectedNode?.id) {
      if (!id) return;
      const editorState = this.ensureActionEditorState(target, id, []);
      if (!editorState || !editorState.redoStack.length) return;
      const nextTree = editorState.redoStack.pop();
      editorState.undoStack.push(structuredClone(editorState.workingActionTree));
      editorState.mutationVersion += 1;
      editorState.error = '';
      this.setWorkingActionTree(target, id, nextTree);
      this.clearSelectedActionStep(target);
      this.prepareState();
      this.refreshView();
      void this.persistActionTree(target, id);
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
    },

    recordGlobalHistoryEntry(entry) {
      this.globalHistoryUndoStack.push(entry);
      if (this.globalHistoryUndoStack.length > 200) this.globalHistoryUndoStack.shift();
      this.globalHistoryRedoStack = [];
      this.lastHistoryLabel = entry.label || '';
      this.prepareState();
      this.refreshView();
    },

    async undoGlobalHistoryChange() {
      const entry = this.globalHistoryUndoStack.pop();
      if (!entry) return;
      await entry.undo();
      this.globalHistoryRedoStack.push(entry);
      this.lastHistoryLabel = entry.label || '';
      this.prepareState();
      this.refreshView();
    },

    async redoGlobalHistoryChange() {
      const entry = this.globalHistoryRedoStack.pop();
      if (!entry) return;
      await entry.redo();
      this.globalHistoryUndoStack.push(entry);
      this.lastHistoryLabel = entry.label || '';
      this.prepareState();
      this.refreshView();
    },

    captureNodeFormUndoSnapshot() {
      if (!this.selectedNode) return;
      const editorState = this.ensureNodeFormState(this.selectedNode);
      editorState.undoStack.push(structuredClone(editorState.workingValue));
      if (editorState.undoStack.length > 100) editorState.undoStack.shift();
      editorState.redoStack = [];
    },

    captureChoiceFormUndoSnapshot(nodeId, choiceId) {
      const editorState = this.ensureChoiceFormState(nodeId, {id: choiceId});
      editorState.undoStack.push(structuredClone(editorState.workingValue));
      if (editorState.undoStack.length > 100) editorState.undoStack.shift();
      editorState.redoStack = [];
    },

    async undoNodeFormChange(nodeId = this.selectedNode?.id) {
      if (!nodeId) return;
      const node = (this.conversation?.nodes ?? []).find(item => Number(item.id) === Number(nodeId));
      const editorState = this.ensureNodeFormState(node ?? {id: nodeId});
      if (!editorState?.undoStack?.length) return;
      const previous = editorState.undoStack.pop();
      editorState.redoStack.push(structuredClone(editorState.workingValue));
      editorState.mutationVersion += 1;
      editorState.error = '';
      editorState.workingValue = structuredClone(previous);
      editorState.isDirty = !formValuesEqual(editorState.workingValue, editorState.baseValue);
      this.prepareState();
      this.refreshView();
      void this.persistNodeForm(nodeId);
    },

    async redoNodeFormChange(nodeId = this.selectedNode?.id) {
      if (!nodeId) return;
      const node = (this.conversation?.nodes ?? []).find(item => Number(item.id) === Number(nodeId));
      const editorState = this.ensureNodeFormState(node ?? {id: nodeId});
      if (!editorState?.redoStack?.length) return;
      const nextValue = editorState.redoStack.pop();
      editorState.undoStack.push(structuredClone(editorState.workingValue));
      editorState.mutationVersion += 1;
      editorState.error = '';
      editorState.workingValue = structuredClone(nextValue);
      editorState.isDirty = !formValuesEqual(editorState.workingValue, editorState.baseValue);
      this.prepareState();
      this.refreshView();
      void this.persistNodeForm(nodeId);
    },

    async undoChoiceFormChange(nodeId = this.selectedNode?.id, choiceId = this.selectedChoice?.id) {
      if (!nodeId || !choiceId) return;
      const editorState = this.ensureChoiceFormState(nodeId, {id: choiceId});
      if (!editorState?.undoStack?.length) return;
      const previous = editorState.undoStack.pop();
      editorState.redoStack.push(structuredClone(editorState.workingValue));
      editorState.mutationVersion += 1;
      editorState.error = '';
      editorState.workingValue = structuredClone(previous);
      editorState.isDirty = !formValuesEqual(editorState.workingValue, editorState.baseValue);
      this.prepareState();
      this.refreshView();
      void this.persistChoiceForm(nodeId, choiceId);
    },

    async redoChoiceFormChange(nodeId = this.selectedNode?.id, choiceId = this.selectedChoice?.id) {
      if (!nodeId || !choiceId) return;
      const editorState = this.ensureChoiceFormState(nodeId, {id: choiceId});
      if (!editorState?.redoStack?.length) return;
      const nextValue = editorState.redoStack.pop();
      editorState.undoStack.push(structuredClone(editorState.workingValue));
      editorState.mutationVersion += 1;
      editorState.error = '';
      editorState.workingValue = structuredClone(nextValue);
      editorState.isDirty = !formValuesEqual(editorState.workingValue, editorState.baseValue);
      this.prepareState();
      this.refreshView();
      void this.persistChoiceForm(nodeId, choiceId);
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

function createTreeEditorState(actionTree) {
  const clonedTree = structuredClone(actionTree ?? []);
  return {
    baseActionTree: structuredClone(clonedTree),
    workingActionTree: structuredClone(clonedTree),
    undoStack: [],
    redoStack: [],
    isDirty: false,
    isSaving: false,
    saveQueued: false,
    mutationVersion: 0,
    error: ''
  };
}

function treesEqual(left, right) {
  return JSON.stringify(left ?? []) === JSON.stringify(right ?? []);
}

function createOrderEditorState(ids) {
  const values = [...(ids ?? [])];
  return {
    baseIds: [...values],
    workingIds: [...values],
    undoStack: [],
    redoStack: [],
    isDirty: false,
    isSaving: false,
    saveQueued: false,
    mutationVersion: 0,
    error: ''
  };
}

function createFormEditorState(value) {
  const clonedValue = structuredClone(value ?? {});
  return {
    baseValue: structuredClone(clonedValue),
    workingValue: structuredClone(clonedValue),
    undoStack: [],
    redoStack: [],
    isDirty: false,
    isSaving: false,
    saveQueued: false,
    mutationVersion: 0,
    error: ''
  };
}

function createBlankNodeDraft() {
  return {
    name: '',
    script_line_id: null,
    speaker_character_id: null
  };
}

function createBlankChoiceDraft() {
  return {
    script_line_id: null,
    next_node_id: null,
    end_conversation: false
  };
}

function formValuesEqual(left, right) {
  return JSON.stringify(left ?? {}) === JSON.stringify(right ?? {});
}

function orderArraysEqual(left, right) {
  return JSON.stringify(left ?? []) === JSON.stringify(right ?? []);
}

function withLocalStepIds(stepOrTree) {
  if (Array.isArray(stepOrTree)) return stepOrTree.map(item => withLocalStepIds(item));
  if (!stepOrTree || typeof stepOrTree !== 'object') return stepOrTree;
  return {
    ...stepOrTree,
    id: String(stepOrTree.id || `local-${crypto.randomUUID()}`),
    then_steps: withLocalStepIds(stepOrTree.then_steps ?? []),
    else_steps: withLocalStepIds(stepOrTree.else_steps ?? [])
  };
}

function formatActionTreeStatus(editorState) {
  if (!editorState) return '';
  if (editorState.error) return editorState.error;
  if (editorState.isSaving) return 'Saving step changes...';
  if (editorState.isDirty) return 'Unsaved step changes';
  return 'All step changes saved';
}

function formatFormStatus(editorState, kind) {
  if (!editorState) return '';
  if (editorState.error) return editorState.error;
  if (editorState.isSaving) return `Saving ${kind} changes...`;
  if (editorState.isDirty) return `Unsaved ${kind} changes`;
  return `All ${kind} changes saved`;
}

export {ConversationEditorCtrl};
