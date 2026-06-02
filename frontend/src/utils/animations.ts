/**
 * GSAP 动画工具集 — Vue 3 可复用动画 composable
 */
import { nextTick, type Ref } from 'vue'
import gsap from 'gsap'

/** 页面入场：标题 + 副标题 + 按钮依次淡入上移 */
export function heroEntrance(container: HTMLElement) {
  const tl = gsap.timeline({ defaults: { ease: 'power3.out' } })
  tl.from(container.querySelectorAll('.hero-eyebrow, .hero-title, .hero-sub, .hero-actions'), {
    y: 30,
    opacity: 0,
    duration: 0.7,
    stagger: 0.12,
  })
  return tl
}

/** Dashboard 入场：header → calorie card → stat cards stagger */
export function dashboardEntrance(container: HTMLElement) {
  const tl = gsap.timeline({ defaults: { ease: 'power3.out' } })

  tl.from(container.querySelectorAll('.dash-header'), {
    y: 20, opacity: 0, duration: 0.5,
  })
  tl.from(container.querySelectorAll('.calorie-card'), {
    y: 30, opacity: 0, duration: 0.6, scale: 0.97,
  }, '-=0.3')
  tl.from(container.querySelectorAll('.stat-card'), {
    y: 25, opacity: 0, duration: 0.5, stagger: 0.1,
  }, '-=0.3')
  tl.from(container.querySelectorAll('.quick-item'), {
    y: 20, opacity: 0, duration: 0.4, stagger: 0.06,
  }, '-=0.2')
  tl.from(container.querySelectorAll('.plan-summary, .summary-card'), {
    y: 20, opacity: 0, duration: 0.5,
  }, '-=0.2')

  return tl
}

/** 四步流程卡片 stagger 入场 */
export function flowStepsEntrance(container: HTMLElement) {
  return gsap.from(container.querySelectorAll('.flow-step'), {
    y: 40,
    opacity: 0,
    scale: 0.95,
    duration: 0.6,
    stagger: 0.12,
    ease: 'power3.out',
  })
}

/** 卡片列表 stagger 入场（通用） */
export function cardStaggerIn(selector: string, container: HTMLElement) {
  return gsap.from(container.querySelectorAll(selector), {
    y: 30,
    opacity: 0,
    duration: 0.5,
    stagger: 0.08,
    ease: 'power2.out',
  })
}

/** 数字滚动（从 0 到目标值） */
export function countUp(el: HTMLElement, target: number, opts?: { duration?: number; suffix?: string }) {
  const obj = { val: 0 }
  gsap.to(obj, {
    val: target,
    duration: opts?.duration ?? 1.2,
    ease: 'power2.out',
    onUpdate() {
      el.textContent = Math.round(obj.val).toLocaleString() + (opts?.suffix ?? '')
    },
  })
}

/** 进度条从 0 宽度动画到目标宽度 */
export function progressFillIn(el: HTMLElement, targetPct: number) {
  gsap.fromTo(el, { width: '0%' }, {
    width: `${Math.min(targetPct, 100)}%`,
    duration: 1,
    ease: 'power2.out',
    delay: 0.3,
  })
}

/** 内容区块淡入（通用） */
export function sectionReveal(el: HTMLElement) {
  gsap.from(el, {
    y: 25,
    opacity: 0,
    duration: 0.6,
    ease: 'power2.out',
  })
}

/** 结果卡片入场（分析结果、识别结果等） */
export function resultEntrance(container: HTMLElement) {
  const tl = gsap.timeline({ defaults: { ease: 'power3.out' } })
  tl.from(container.querySelectorAll('.result-header'), {
    y: 20, opacity: 0, duration: 0.4,
  })
  tl.from(container.querySelectorAll('.card, .score-card, .total-card, .summary-card, .items-card'), {
    y: 30, opacity: 0, scale: 0.97, duration: 0.5, stagger: 0.1,
  }, '-=0.2')
  tl.from(container.querySelectorAll('.result-actions'), {
    y: 15, opacity: 0, duration: 0.3,
  }, '-=0.1')
  return tl
}

/** 表单区域入场 */
export function formEntrance(container: HTMLElement) {
  return gsap.from(container.querySelectorAll('.form-section, .el-form, form'), {
    y: 20,
    opacity: 0,
    duration: 0.5,
    stagger: 0.1,
    ease: 'power2.out',
  })
}

/** 列表项 stagger（打卡历史等） */
export function listStaggerIn(container: HTMLElement) {
  return gsap.from(container.querySelectorAll('.checkin-item, .history-item, .recipe-item'), {
    x: -20,
    opacity: 0,
    duration: 0.4,
    stagger: 0.06,
    ease: 'power2.out',
  })
}
