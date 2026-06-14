<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'
import {
  Archive,
  BookOpen,
  Menu,
  MessageSquare,
  Plus,
  Send,
  Square,
  X,
} from '@lucide/vue'
import {
  archiveChatConversation,
  createChatConversation,
  getChatConversation,
  getChatConversations,
  streamChatMessage,
} from '../api'
import type {
  ChatCitation,
  ChatConversation,
  ChatMessage,
} from '../types'
import { sanitizeHtml } from '../utils/sanitize'

const userId = Number(localStorage.getItem('userId')) || 0
const conversations = ref<ChatConversation[]>([])
const activeConversationId = ref<number | null>(null)
const messages = ref<ChatMessage[]>([])
const input = ref('')
const loading = ref(true)
const generating = ref(false)
const errorMessage = ref('')
const sidebarOpen = ref(false)
const messageList = ref<HTMLElement | null>(null)
let abortController: AbortController | null = null

const activeConversation = computed(() =>
  conversations.value.find(item => item.id === activeConversationId.value)
)

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
    context: {},
    status: role === 'assistant' ? 'pending' : 'completed',
    created_at: new Date().toISOString(),
  }
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
    conversations.value = await getChatConversations(userId)
    if (conversations.value.length) {
      await openConversation(conversations.value[0].id)
    }
  } catch {
    errorMessage.value = '会话列表加载失败'
  } finally {
    loading.value = false
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
      <button class="new-chat-button" :disabled="!userId || generating" @click="newConversation">
        <Plus :size="17" />
        新对话
      </button>
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
              <details v-if="message.citations?.length" class="citations">
                <summary><BookOpen :size="15" /> {{ message.citations.length }} 条参考依据</summary>
                <a
                  v-for="citation in message.citations"
                  :key="citation.chunk_id"
                  :href="citation.source_url || undefined"
                  :target="citation.source_url ? '_blank' : undefined"
                  rel="noreferrer"
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
