# Design System: 减脂 Agent

## Color Strategy
- Register: Restrained（克制风格）
- Primary: 清新绿色系，代表健康与生命力
- Neutrals: 偏暖的灰色调，不使用纯黑纯白
- Accent: 绿色用于关键操作和正向反馈
- Warning: 琥珀色用于提醒，不使用刺眼红色

## Typography
- Headline: 粗体，20-28px，用于页面标题
- Body: 14-16px，行高 1.6-1.8，保证中文阅读舒适
- Caption: 12-13px，用于辅助信息和标签
- 数字数据使用等宽或半粗体突出

## Spacing
- 基础单位: 8px
- 卡片内边距: 20-24px
- 区块间距: 24-32px
- 紧凑元素间距: 8-12px

## Components
- 卡片：轻投影，圆角 8-12px，不嵌套
- 按钮：主操作用实色，次操作用文字按钮
- 表单：标签左对齐，输入框足够大（移动端友好）
- 数据展示：数字突出，标签辅助

## Motion
- 页面切换：轻柔淡入，200-300ms
- 数据加载：骨架屏优于旋转 loading
- 操作反馈：成功/失败 toast，3 秒自动消失
- 不使用弹跳/弹性动画

## Dark Mode
- 暂不支持，后续版本考虑

## Layout
- 最大宽度 1200px，居中
- 移动端优先响应式
- 导航固定顶部，简洁不占空间
