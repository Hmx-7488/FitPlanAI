<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'
import {
  Archive,
  BookOpen,
  BrainCircuit,
  Check,
  Menu,
  MessageSquare,
  Plus,
  Send,
  ShieldAlert,
  Square,
  Trash2,
  X,
} from '@lucide/vue'
import {
  archiveChatConversation,
  createChatConversation,
  getChatConversation,
  getChatConversations,
  getUserMemories,
  confirmUserMemory,
  rejectUserMemory,
  deleteUserMemory,
  streamChatMessage,
} from '../api'
import type {
  ChatCitation,
  ChatConversation,
  ChatMessage,
  ChatToolTrace,
  UserMemory,
  UserMemoryType,
} from '../types'
import { sanitizeHtml } from '../utils/sanitize'
import { safeExternalUrl } from '../utils/url'

const userId = Number(localStorage.getItem('userId')) || 0
const conversations = ref<ChatConversation[]>([])
const activeConversationId = ref<number | null>(null)
const messages = ref<ChatMessage[]>([])
const input = ref('')
const loading = ref(true)
const generating = ref(false)
const errorMessage = ref('')
const sidebarOpen = ref(false)
const memoryPanelOpen = ref(false)
const memories = ref<UserMemory[]>([])
const memoriesLoading = ref(false)
const memoryActionId = ref<number | null>(null)
const memoryError = ref('')
const messageList = ref<HTMLElement | null>(null)
let abortController: AbortController | null = null

const activeConversation = computed(() =>
  conversations.value.find(item => item.id === activeConversationId.value)
)
const pendingMemories = computed(() =>
  memories.value.filter(item => item.confirmation_status === 'candidate')
)
const confirmedMemories = computed(() =>
  memories.value.filter(item => item.confirmation_status === 'confirmed')
)

const memoryTypeLabels: Record<UserMemoryType, string> = {
  preference: '偏好',
  goal: '目标',
  habit: '习惯',
  constraint: '限制',
  experience: '经历',
}

const quickPrompts = [
  '根据我的目标，解释一下每天的热量和蛋白质安排',
  '我膝盖不舒服，训练时应该注意什么？',
  '帮我解读当前饮食计划，并给出更容易执行的建议',
]

function localMessage(role: 'user' | 'assistant', content: string): ChatMessage {
  return {
    id: -Date.now() - Math.floor(Math.random() * 1000),
    role,
    content,
    citations: [],
    context: role === 'assistant' ? { tool_calls: [] } : {},
    status: role === 'assistant' ? 'pending' : 'completed',
    created_at: new Date().toISOString(),
  }
}

function toolTracesFor(message: ChatMessage): ChatToolTrace[] {
  const value = message.context?.tool_calls
  if (!Array.isArray(value)) return []
  return value.filter(item => item && typeof item === 'object') as ChatToolTrace[]
}

function applyToolTrace(message: ChatMessage, trace: ChatToolTrace) {
  const traces = [...toolTracesFor(message)]
  const index = traces.findIndex(item => item.call_id === trace.call_id)
  if (index >= 0) traces[index] = trace
  else traces.push(trace)
  message.context = { ...message.context, tool_calls: traces }
}

async function scrollToBottom() {
  await nextTick()
  messageList.value?.scrollTo({
    top: messageList.value.scrollHeight,
    behavior: 'smooth',
  })
}

async function loadConversations() {
  if (!userId) {
    loading.value = false
    return
  }
  try {
    const [conversationResults, memoryResults] = await Promise.allSettled([
      getChatConversations(userId),
      getUserMemories(userId),
    ])
    if (conversationResults.status === 'rejected') throw conversationResults.reason
    conversations.value = conversationResults.value
    if (memoryResults.status === 'fulfilled') memories.value = memoryResults.value
    if (conversations.value.length) {
      await openConversation(conversations.value[0].id)
    }
  } catch {
    errorMessage.value = '会话列表加载失败'
  } finally {
    loading.value = false
  }
}

async function openMemoryPanel() {
  if (!userId) return
  memoryPanelOpen.value = true
  memoriesLoading.value = true
  memoryError.value = ''
  try {
    memories.value = await getUserMemories(userId)
  } catch {
    memoryError.value = '记忆列表加载失败，请稍后重试。'
  } finally {
    memoriesLoading.value = false
  }
}

async function confirmMemory(memory: UserMemory) {
  memoryActionId.value = memory.id
  memoryError.value = ''
  try {
    const updated = await confirmUserMemory(memory.id, userId)
    memories.value = memories.value.map(item => item.id === memory.id ? updated : item)
  } catch {
    memoryError.value = '确认失败，请稍后重试。'
  } finally {
    memoryActionId.value = null
  }
}

async function rejectMemory(memory: UserMemory) {
  memoryActionId.value = memory.id
  memoryError.value = ''
  try {
    await rejectUserMemory(memory.id, userId)
    memories.value = memories.value.filter(item => item.id !== memory.id)
  } catch {
    memoryError.value = '忽略失败，请稍后重试。'
  } finally {
    memoryActionId.value = null
  }
}

async function forgetMemory(memory: UserMemory) {
  memoryActionId.value = memory.id
  memoryError.value = ''
  try {
    await deleteUserMemory(memory.id, userId)
    memories.value = memories.value.filter(item => item.id !== memory.id)
  } catch {
    memoryError.value = '遗忘失败，请稍后重试。'
  } finally {
    memoryActionId.value = null
  }
}

async function openConversation(id: number) {
  if (generating.value) return
  try {
    const detail = await getChatConversation(id, userId)
    activeConversationId.value = id
    messages.value = detail.messages
    sidebarOpen.value = false
    errorMessage.value = ''
    await scrollToBottom()
  } catch {
    errorMessage.value = '会话加载失败'
  }
}

async function newConversation() {
  if (!userId || generating.value) return
  try {
    const created = await createChatConversation(userId)
    conversations.value.unshift(created)
    activeConversationId.value = created.id
    messages.value = []
    input.value = ''
    sidebarOpen.value = false
  } catch {
    errorMessage.value = '新建会话失败'
  }
}

async function archiveConversation(event: Event, id: number) {
  event.stopPropagation()
  if (generating.value) return
  await archiveChatConversation(id, userId)
  conversations.value = conversations.value.filter(item => item.id !== id)
  if (activeConversationId.value === id) {
    activeConversationId.value = null
    messages.value = []
    if (conversations.value.length) await openConversation(conversations.value[0].id)
  }
}

async function ensureConversation(): Promise<number | null> {
  if (activeConversationId.value) return activeConversationId.value
  await newConversation()
  return activeConversationId.value
}

async function sendMessage(content = input.value) {
  const text = content.trim()
  if (!text || generating.value || !userId) return
  const conversationId = await ensureConversation()
  if (!conversationId) return

  input.value = ''
  errorMessage.value = ''
  const userMessage = localMessage('user', text)
  const assistantMessage = localMessage('assistant', '')
  messages.value.push(userMessage, assistantMessage)
  generating.value = true
  abortController = new AbortController()
  await scrollToBottom()

  try {
    await streamChatMessage(
      conversationId,
      {
        user_id: userId,
        content: text,
        current_page: 'chat',
        page_context: {},
      },
      {
        onDelta(delta) {
          assistantMessage.content += delta
          scrollToBottom()
        },
        onTool(data) {
          applyToolTrace(assistantMessage, data as unknown as ChatToolTrace)
          scrollToBottom()
        },
        onCitations(data) {
          assistantMessage.citations = data as ChatCitation[]
        },
        onDone(data) {
          Object.assign(assistantMessage, data as ChatMessage)
        },
        onError(message) {
          errorMessage.value = message
          assistantMessage.status = 'failed'
          if (!assistantMessage.content) assistantMessage.content = '生成失败，请稍后重试。'
        },
      },
      abortController.signal
    )
    conversations.value = await getChatConversations(userId)
  } catch (error) {
    if ((error as Error).name !== 'AbortError') {
      errorMessage.value = (error as Error).message || '发送失败'
      assistantMessage.status = 'failed'
      if (!assistantMessage.content) assistantMessage.content = '发送失败，请稍后重试。'
    } else {
      assistantMessage.status = 'stopped'
      if (!assistantMessage.content) assistantMessage.content = '已停止生成。'
    }
  } finally {
    generating.value = false
    abortController = null
    await scrollToBottom()
  }
}

function stopGenerating() {
  abortController?.abort()
}

function handleKeydown(event: KeyboardEvent) {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault()
    sendMessage()
  }
}

function formatMessage(text: string): string {
  const rendered = text
    .replace(/^###\s(.+)$/gm, '<h4>$1</h4>')
    .replace(/^##\s(.+)$/gm, '<h4>$1</h4>')
    .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
    .replace(/\n/g, '<br>')
  return sanitizeHtml(rendered)
}

onMounted(loadConversations)
</script>

<template>
  <section class="chat-page">
    <div class="chat-toolbar">
      <button class="icon-button mobile-menu" title="打开会话列表" @click="sidebarOpen = true">
        <Menu :size="20" />
      </button>
      <div>
        <h1>AI 健康助手</h1>
        <p>{{ activeConversation?.title || '新对话' }}</p>
      </div>
      <button class="memory-button" :disabled="!userId" @click="openMemoryPanel">
        <BrainCircuit :size="17" />
        <span>记忆</span>
        <small v-if="pendingMemories.length">{{ pendingMemories.length }}</small>
      </button>
      <button class="new-chat-button" :disabled="!userId || generating" @click="newConversation">
        <Plus :size="17" />
        新对话
      </button>
    </div>

    <div
      v-if="memoryPanelOpen"
      class="memory-overlay"
      role="presentation"
      @click.self="memoryPanelOpen = false"
    >
      <section class="memory-panel" role="dialog" aria-modal="true" aria-labelledby="memory-title">
        <header class="memory-panel__header">
          <div class="memory-title-mark"><BrainCircuit :size="20" /></div>
          <div>
            <p class="memory-kicker">PERSONAL CONTEXT</p>
            <h2 id="memory-title">Agent 记住的内容</h2>
          </div>
          <button class="icon-button" title="关闭记忆面板" @click="memoryPanelOpen = false">
            <X :size="20" />
          </button>
        </header>

        <p class="memory-intro">
          高置信普通偏好可用于后续对话；低置信信息以及伤病、过敏等健康内容必须由你确认后才会生效。
        </p>
        <p v-if="memoryError" class="memory-error">{{ memoryError }}</p>
        <div v-if="memoriesLoading" class="memory-empty">正在读取记忆…</div>

        <div v-else class="memory-scroll">
          <section v-if="pendingMemories.length" class="memory-group memory-group--pending">
            <div class="memory-group__heading">
              <span><ShieldAlert :size="16" /> 待你确认</span>
              <small>{{ pendingMemories.length }} 条信息确认后才生效</small>
            </div>
            <article v-for="memory in pendingMemories" :key="memory.id" class="memory-card">
              <div class="memory-card__meta">
                <span>{{ memoryTypeLabels[memory.memory_type] }}</span>
                <code>#{{ memory.id }}</code>
              </div>
              <p>{{ memory.content_text }}</p>
              <div class="memory-card__actions">
                <button
                  class="memory-action memory-action--confirm"
                  :disabled="memoryActionId === memory.id"
                  @click="confirmMemory(memory)"
                >
                  <Check :size="15" /> 确认记住
                </button>
                <button
                  class="memory-action"
                  :disabled="memoryActionId === memory.id"
                  @click="rejectMemory(memory)"
                >
                  忽略
                </button>
              </div>
            </article>
          </section>

          <section v-if="confirmedMemories.length" class="memory-group">
            <div class="memory-group__heading">
              <span><Check :size="16" /> 已确认记忆</span>
              <small>{{ confirmedMemories.length }} 条正在参与个性化</small>
            </div>
            <article v-for="memory in confirmedMemories" :key="memory.id" class="memory-card">
              <div class="memory-card__meta">
                <span>{{ memoryTypeLabels[memory.memory_type] }}</span>
                <span v-if="memory.sensitivity === 'health_sensitive'" class="sensitive-tag">健康信息</span>
                <code>#{{ memory.id }}</code>
              </div>
              <p>{{ memory.content_text }}</p>
              <button
                class="forget-action"
                :disabled="memoryActionId === memory.id"
                title="让 Agent 遗忘这条内容"
                @click="forgetMemory(memory)"
              >
                <Trash2 :size="15" /> 遗忘
              </button>
            </article>
          </section>

          <div v-if="!pendingMemories.length && !confirmedMemories.length" class="memory-empty">
            <BrainCircuit :size="28" />
            <strong>还没有长期记忆</strong>
            <span>当你明确表达稳定偏好或长期目标后，它们会出现在这里。</span>
          </div>
        </div>
      </section>
    </div>

    <div v-if="!userId" class="profile-required">
      <MessageSquare :size="28" />
      <h2>请先完成建档</h2>
      <p>助手需要读取你的目标与健康限制后才能提供个性化建议。</p>
      <router-link to="/profile">前往建档</router-link>
    </div>

    <div v-else class="chat-layout">
      <div v-if="sidebarOpen" class="sidebar-backdrop" @click="sidebarOpen = false" />
      <aside class="conversation-sidebar" :class="{ 'conversation-sidebar--open': sidebarOpen }">
        <div class="sidebar-heading">
          <span>会话</span>
          <button class="icon-button sidebar-close" title="关闭会话列表" @click="sidebarOpen = false">
            <X :size="19" />
          </button>
        </div>
        <div class="conversation-list">
          <button
            v-for="conversation in conversations"
            :key="conversation.id"
            class="conversation-item"
            :class="{ 'conversation-item--active': conversation.id === activeConversationId }"
            @click="openConversation(conversation.id)"
          >
            <MessageSquare :size="17" />
            <span class="conversation-copy">
              <strong>{{ conversation.title }}</strong>
              <small>{{ conversation.last_message || '暂无消息' }}</small>
            </span>
            <span
              class="archive-action"
              role="button"
              tabindex="0"
              title="归档会话"
              @click="archiveConversation($event, conversation.id)"
            >
              <Archive :size="15" />
            </span>
          </button>
          <p v-if="!loading && !conversations.length" class="empty-list">暂无会话</p>
        </div>
      </aside>

      <main class="conversation-main">
        <div ref="messageList" class="message-list">
          <div v-if="!messages.length && !loading" class="empty-chat">
            <MessageSquare :size="34" />
            <h2>今天想解决什么问题？</h2>
            <div class="quick-prompts">
              <button v-for="prompt in quickPrompts" :key="prompt" @click="sendMessage(prompt)">
                {{ prompt }}
              </button>
            </div>
          </div>

          <article
            v-for="message in messages"
            :key="message.id"
            class="message-row"
            :class="`message-row--${message.role}`"
          >
            <div class="message-label">{{ message.role === 'user' ? '你' : '助手' }}</div>
            <div class="message-body">
              <div
                v-if="message.content"
                class="message-content"
                v-html="formatMessage(message.content)"
              />
              <span v-else class="typing-indicator"><i /><i /><i /></span>
              <section
                v-if="toolTracesFor(message).length"
                class="agent-ledger"
                aria-label="Agent 数据查询记录"
                aria-live="polite"
              >
                <header>
                  <BrainCircuit :size="15" />
                  <span>Agent 数据查询</span>
                  <small>{{ toolTracesFor(message).length }} 项</small>
                </header>
                <div
                  v-for="trace in toolTracesFor(message)"
                  :key="trace.call_id"
                  class="agent-ledger-row"
                  :class="`agent-ledger-row--${trace.status}`"
                >
                  <span class="agent-ledger-mark" aria-hidden="true">
                    <Check v-if="trace.status === 'completed'" :size="13" />
                    <ShieldAlert v-else :size="13" />
                  </span>
                  <span class="agent-ledger-copy">
                    <strong>{{ trace.label }}</strong>
                    <small>{{ trace.summary }}</small>
                  </span>
                  <span class="agent-ledger-state">
                    {{ trace.included_in_answer ? '已用于回答' : trace.status === 'failed' ? '已跳过' : '已查询' }}
                  </span>
                  <details v-if="trace.sources?.length" class="agent-sources">
                    <summary>{{ trace.sources.length }} 个数据来源</summary>
                    <a
                      v-for="source in trace.sources"
                      :key="`${source.source_type}-${source.source_id}`"
                      :href="safeExternalUrl(source.url)"
                      :target="safeExternalUrl(source.url) ? '_blank' : undefined"
                      rel="noopener noreferrer"
                    >
                      {{ source.title }}
                    </a>
                  </details>
                </div>
              </section>
              <details v-if="message.citations?.length" class="citations">
                <summary><BookOpen :size="15" /> {{ message.citations.length }} 条参考依据</summary>
                <a
                  v-for="citation in message.citations"
                  :key="citation.chunk_id"
                  :href="safeExternalUrl(citation.source_url)"
                  :target="safeExternalUrl(citation.source_url) ? '_blank' : undefined"
                  rel="noopener noreferrer"
                >
                  <strong>{{ citation.title }}</strong>
                  <span>{{ citation.source_name || citation.category }}</span>
                </a>
              </details>
            </div>
          </article>
        </div>

        <p v-if="errorMessage" class="chat-error">{{ errorMessage }}</p>
        <div class="composer">
          <textarea
            v-model="input"
            rows="2"
            maxlength="4000"
            placeholder="输入你的饮食、训练或计划问题"
            :disabled="generating"
            @keydown="handleKeydown"
          />
          <button
            v-if="generating"
            class="send-button send-button--stop"
            title="停止生成"
            @click="stopGenerating"
          >
            <Square :size="18" fill="currentColor" />
          </button>
          <button
            v-else
            class="send-button"
            title="发送"
            :disabled="!input.trim()"
            @click="sendMessage()"
          >
            <Send :size="19" />
          </button>
        </div>
      </main>
    </div>
  </section>
</template>

<style scoped>
.chat-page {
  height: calc(100vh - 120px);
  min-height: 620px;
  display: flex;
  flex-direction: column;
}

.chat-toolbar {
  min-height: 64px;
  display: flex;
  align-items: center;
  gap: var(--space-3);
  border-bottom: 1px solid var(--color-border);
}

.chat-toolbar h1 {
  font-size: var(--text-xl);
  line-height: 1.2;
}

.chat-toolbar p {
  color: var(--color-text-tertiary);
  font-size: var(--text-sm);
}

.new-chat-button {
  margin-left: auto;
  height: 38px;
  padding: 0 var(--space-4);
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  border: 1px solid var(--color-accent);
  border-radius: var(--radius-sm);
  background: var(--color-accent);
  color: white;
  font-weight: 600;
  cursor: pointer;
}

.memory-button {
  position: relative;
  margin-left: auto;
  height: 38px;
  padding: 0 var(--space-3);
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: var(--color-surface);
  color: var(--color-text-secondary);
  font-weight: 650;
  cursor: pointer;
}

.memory-button:hover {
  border-color: var(--color-accent);
  color: var(--color-text-primary);
}

.memory-button small {
  min-width: 19px;
  height: 19px;
  padding: 0 5px;
  display: inline-grid;
  place-items: center;
  border-radius: 999px;
  background: var(--color-danger);
  color: white;
  font-size: 11px;
}

.new-chat-button {
  margin-left: 0;
}

.memory-overlay {
  position: fixed;
  z-index: 320;
  inset: 0;
  display: grid;
  justify-items: end;
  background: rgb(20 28 24 / 0.3);
  backdrop-filter: blur(4px);
}

.memory-panel {
  width: min(92vw, 480px);
  height: 100%;
  padding: var(--space-6);
  display: flex;
  flex-direction: column;
  background:
    radial-gradient(circle at 92% 4%, color-mix(in srgb, var(--color-accent) 10%, transparent), transparent 28%),
    var(--color-surface);
  border-left: 1px solid var(--color-border);
  box-shadow: -24px 0 70px rgb(23 37 30 / 0.12);
  animation: memory-panel-in 220ms var(--ease-out);
}

@keyframes memory-panel-in {
  from { opacity: 0; transform: translateX(28px); }
}

.memory-panel__header {
  display: grid;
  grid-template-columns: 42px minmax(0, 1fr) 36px;
  align-items: center;
  gap: var(--space-3);
}

.memory-title-mark {
  width: 42px;
  height: 42px;
  display: grid;
  place-items: center;
  border-radius: 14px;
  background: var(--color-accent-subtle);
  color: var(--color-accent);
}

.memory-kicker {
  color: var(--color-accent);
  font-size: 10px;
  font-weight: 800;
  letter-spacing: 0.15em;
}

.memory-panel__header h2 {
  font-size: var(--text-lg);
}

.memory-intro {
  margin: var(--space-5) 0;
  padding: var(--space-3) var(--space-4);
  border-left: 3px solid var(--color-accent);
  background: var(--color-accent-subtle);
  color: var(--color-text-secondary);
  font-size: var(--text-sm);
  line-height: var(--leading-relaxed);
}

.memory-error {
  margin-bottom: var(--space-3);
  color: var(--color-danger);
  font-size: var(--text-sm);
}

.memory-scroll {
  min-height: 0;
  overflow-y: auto;
  padding-right: 3px;
}

.memory-group + .memory-group {
  margin-top: var(--space-6);
}

.memory-group__heading {
  margin-bottom: var(--space-3);
  display: flex;
  align-items: end;
  justify-content: space-between;
  gap: var(--space-3);
}

.memory-group__heading span {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--text-sm);
  font-weight: 750;
}

.memory-group__heading small {
  color: var(--color-text-tertiary);
  font-size: var(--text-xs);
}

.memory-group--pending .memory-group__heading span {
  color: var(--color-danger);
}

.memory-card {
  position: relative;
  margin-bottom: var(--space-2);
  padding: var(--space-4);
  border: 1px solid var(--color-border-subtle);
  border-radius: var(--radius-md);
  background: var(--color-surface-raised);
}

.memory-group--pending .memory-card {
  border-color: color-mix(in srgb, var(--color-danger) 22%, var(--color-border));
}

.memory-card__meta {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  color: var(--color-text-tertiary);
  font-size: var(--text-xs);
}

.memory-card__meta span:first-child {
  color: var(--color-accent);
  font-weight: 750;
}

.memory-card__meta code {
  margin-left: auto;
  font-size: 10px;
}

.sensitive-tag {
  padding: 2px 6px;
  border-radius: 999px;
  background: color-mix(in srgb, var(--color-danger) 10%, transparent);
  color: var(--color-danger) !important;
}

.memory-card > p {
  margin-top: var(--space-2);
  color: var(--color-text-primary);
  line-height: var(--leading-relaxed);
}

.memory-card__actions {
  margin-top: var(--space-3);
  display: flex;
  gap: var(--space-2);
}

.memory-action,
.forget-action {
  height: 32px;
  padding: 0 var(--space-3);
  display: inline-flex;
  align-items: center;
  gap: 6px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--color-text-secondary);
  font-size: var(--text-xs);
  font-weight: 700;
  cursor: pointer;
}

.memory-action--confirm {
  border-color: var(--color-accent);
  background: var(--color-accent);
  color: white;
}

.forget-action {
  margin-top: var(--space-3);
  padding-left: 0;
  border: 0;
  color: var(--color-text-tertiary);
}

.forget-action:hover {
  color: var(--color-danger);
}

.memory-action:disabled,
.forget-action:disabled {
  opacity: 0.45;
  cursor: wait;
}

.memory-empty {
  min-height: 180px;
  display: grid;
  align-content: center;
  justify-items: center;
  gap: var(--space-2);
  color: var(--color-text-tertiary);
  text-align: center;
  font-size: var(--text-sm);
}

.memory-empty strong {
  color: var(--color-text-primary);
}

.new-chat-button:disabled,
.send-button:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.icon-button.mobile-menu,
.icon-button.sidebar-close {
  display: none;
}

.icon-button {
  width: 36px;
  height: 36px;
  display: inline-grid;
  place-items: center;
  border: 0;
  background: transparent;
  color: var(--color-text-secondary);
  cursor: pointer;
}

.chat-layout {
  flex: 1;
  min-height: 0;
  display: grid;
  grid-template-columns: 250px minmax(0, 1fr);
}

.conversation-sidebar {
  min-height: 0;
  border-right: 1px solid var(--color-border);
  background: var(--color-surface);
}

.sidebar-heading {
  height: 48px;
  padding: 0 var(--space-4);
  display: flex;
  align-items: center;
  justify-content: space-between;
  color: var(--color-text-secondary);
  font-size: var(--text-sm);
  font-weight: 700;
}

.conversation-list {
  height: calc(100% - 48px);
  padding: 0 var(--space-2) var(--space-3);
  overflow-y: auto;
}

.conversation-item {
  width: 100%;
  min-height: 62px;
  padding: var(--space-3);
  display: grid;
  grid-template-columns: 20px minmax(0, 1fr) 26px;
  align-items: center;
  gap: var(--space-2);
  border: 0;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--color-text-secondary);
  text-align: left;
  cursor: pointer;
}

.conversation-item:hover,
.conversation-item--active {
  background: var(--color-accent-subtle);
  color: var(--color-text-primary);
}

.conversation-copy {
  min-width: 0;
  display: grid;
}

.conversation-copy strong,
.conversation-copy small {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.conversation-copy strong {
  font-size: var(--text-sm);
}

.conversation-copy small {
  color: var(--color-text-tertiary);
  font-size: var(--text-xs);
}

.archive-action {
  width: 26px;
  height: 26px;
  display: grid;
  place-items: center;
  border-radius: var(--radius-sm);
  opacity: 0;
}

.conversation-item:hover .archive-action,
.conversation-item--active .archive-action {
  opacity: 1;
}

.archive-action:hover {
  color: var(--color-danger);
}

.empty-list {
  padding: var(--space-6);
  color: var(--color-text-tertiary);
  text-align: center;
}

.conversation-main {
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
  background: var(--color-surface-raised);
}

.message-list {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: var(--space-6) clamp(20px, 7vw, 76px);
}

.empty-chat {
  min-height: 100%;
  display: grid;
  align-content: center;
  justify-items: center;
  gap: var(--space-4);
  color: var(--color-text-secondary);
}

.empty-chat h2 {
  font-size: var(--text-lg);
}

.quick-prompts {
  width: min(100%, 560px);
  display: grid;
  gap: var(--space-2);
}

.quick-prompts button {
  padding: var(--space-3) var(--space-4);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: var(--color-surface);
  color: var(--color-text-secondary);
  text-align: left;
  cursor: pointer;
}

.quick-prompts button:hover {
  border-color: var(--color-accent);
  color: var(--color-text-primary);
}

.message-row {
  margin-bottom: var(--space-6);
  display: grid;
  grid-template-columns: 52px minmax(0, 1fr);
  gap: var(--space-3);
}

.message-label {
  padding-top: 2px;
  color: var(--color-text-tertiary);
  font-size: var(--text-sm);
  font-weight: 700;
}

.message-body {
  min-width: 0;
}

.message-content {
  overflow-wrap: anywhere;
  line-height: var(--leading-relaxed);
}

.message-content :deep(h4) {
  margin: var(--space-3) 0 var(--space-1);
  font-size: var(--text-base);
}

.message-row--user .message-body {
  color: var(--color-text-secondary);
}

.typing-indicator {
  height: 24px;
  display: inline-flex;
  align-items: center;
  gap: 5px;
}

.typing-indicator i {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--color-accent);
  animation: typing 1s infinite ease-in-out;
}

.typing-indicator i:nth-child(2) { animation-delay: 0.12s; }
.typing-indicator i:nth-child(3) { animation-delay: 0.24s; }

@keyframes typing {
  0%, 80%, 100% { opacity: 0.25; transform: translateY(0); }
  40% { opacity: 1; transform: translateY(-3px); }
}

.agent-ledger {
  margin-top: var(--space-3);
  overflow: hidden;
  border: 1px solid color-mix(in srgb, var(--color-accent) 22%, var(--color-border));
  border-radius: var(--radius-sm);
  background:
    linear-gradient(135deg, color-mix(in srgb, var(--color-accent) 6%, transparent), transparent 52%),
    var(--color-surface);
}

.agent-ledger > header {
  min-height: 34px;
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: 0 var(--space-3);
  border-bottom: 1px solid var(--color-border-subtle);
  color: var(--color-text-secondary);
  font-size: var(--text-xs);
  font-weight: 650;
  letter-spacing: 0.02em;
}

.agent-ledger > header small {
  margin-left: auto;
  color: var(--color-text-tertiary);
  font-weight: 500;
}

.agent-ledger-row {
  display: grid;
  grid-template-columns: 22px minmax(0, 1fr) auto;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-3);
}

.agent-ledger-row + .agent-ledger-row {
  border-top: 1px dashed var(--color-border-subtle);
}

.agent-ledger-mark {
  width: 20px;
  height: 20px;
  display: grid;
  place-items: center;
  border-radius: 50%;
  color: var(--color-accent);
  background: color-mix(in srgb, var(--color-accent) 12%, transparent);
}

.agent-ledger-row--failed .agent-ledger-mark {
  color: var(--color-danger);
  background: color-mix(in srgb, var(--color-danger) 12%, transparent);
}

.agent-ledger-copy {
  min-width: 0;
  display: flex;
  flex-direction: column;
}

.agent-ledger-copy strong {
  color: var(--color-text-primary);
  font-size: var(--text-sm);
  font-weight: 620;
}

.agent-ledger-copy small,
.agent-ledger-state,
.agent-sources summary,
.agent-sources a {
  color: var(--color-text-tertiary);
  font-size: var(--text-xs);
}

.agent-ledger-copy small {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.agent-ledger-state {
  white-space: nowrap;
}

.agent-sources {
  grid-column: 2 / -1;
}

.agent-sources summary {
  width: fit-content;
  cursor: pointer;
}

.agent-sources a {
  display: block;
  width: fit-content;
  margin-top: 4px;
  text-decoration: none;
}

.agent-sources a:hover {
  color: var(--color-accent);
}

@media (max-width: 640px) {
  .agent-ledger-row {
    grid-template-columns: 22px minmax(0, 1fr);
  }

  .agent-ledger-state,
  .agent-sources {
    grid-column: 2;
  }
}

.citations {
  margin-top: var(--space-3);
  border-top: 1px solid var(--color-border-subtle);
  padding-top: var(--space-2);
}

.citations summary {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  color: var(--color-text-secondary);
  font-size: var(--text-sm);
  cursor: pointer;
}

.citations a {
  margin-top: var(--space-2);
  padding: var(--space-2) 0;
  display: grid;
  color: var(--color-text-secondary);
  text-decoration: none;
}

.citations a strong {
  font-size: var(--text-sm);
}

.citations a span {
  color: var(--color-text-tertiary);
  font-size: var(--text-xs);
}

.chat-error {
  padding: var(--space-2) var(--space-6);
  color: var(--color-danger);
  font-size: var(--text-sm);
}

.composer {
  margin: 0 clamp(20px, 7vw, 76px) var(--space-5);
  min-height: 72px;
  display: grid;
  grid-template-columns: minmax(0, 1fr) 44px;
  align-items: end;
  gap: var(--space-2);
  padding: var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-surface);
  box-shadow: var(--shadow-sm);
}

.composer:focus-within {
  border-color: var(--color-accent);
}

.composer textarea {
  width: 100%;
  max-height: 140px;
  resize: none;
  border: 0;
  background: transparent;
  color: var(--color-text-primary);
  font: inherit;
  line-height: var(--leading-normal);
}

.send-button {
  width: 40px;
  height: 40px;
  display: grid;
  place-items: center;
  border: 0;
  border-radius: var(--radius-sm);
  background: var(--color-accent);
  color: white;
  cursor: pointer;
}

.send-button--stop {
  background: var(--color-text-primary);
}

.profile-required {
  flex: 1;
  display: grid;
  align-content: center;
  justify-items: center;
  gap: var(--space-3);
  color: var(--color-text-secondary);
  text-align: center;
}

.profile-required h2 {
  font-size: var(--text-lg);
  color: var(--color-text-primary);
}

.profile-required a {
  color: var(--color-accent);
  font-weight: 700;
}

.sidebar-backdrop {
  display: none;
}

@media (max-width: 760px) {
  .chat-page {
    height: calc(100vh - 104px);
    min-height: 520px;
  }

  .icon-button.mobile-menu,
  .icon-button.sidebar-close {
    display: inline-grid;
  }

  .new-chat-button {
    width: 38px;
    padding: 0;
    justify-content: center;
    font-size: 0;
  }

  .memory-button span {
    display: none;
  }

  .memory-button {
    width: 38px;
    padding: 0;
    justify-content: center;
  }

  .memory-button small {
    position: absolute;
    margin: -28px 0 0 28px;
  }

  .memory-panel {
    width: 100%;
    padding: var(--space-5) var(--space-4);
  }

  .chat-layout {
    grid-template-columns: 1fr;
  }

  .conversation-sidebar {
    position: fixed;
    z-index: 220;
    top: 0;
    bottom: 0;
    left: 0;
    width: min(84vw, 320px);
    transform: translateX(-100%);
    transition: transform var(--duration-normal) var(--ease-out);
  }

  .conversation-sidebar--open {
    transform: translateX(0);
  }

  .sidebar-backdrop {
    position: fixed;
    z-index: 210;
    inset: 0;
    display: block;
    background: rgb(0 0 0 / 0.28);
  }

  .message-list {
    padding: var(--space-5) var(--space-4);
  }

  .composer {
    margin: 0 var(--space-4) var(--space-3);
  }

  .message-row {
    grid-template-columns: 40px minmax(0, 1fr);
  }
}
</style>
