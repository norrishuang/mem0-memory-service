import { defineConfig } from 'vitepress'
import { withMermaid } from 'vitepress-plugin-mermaid'

export default withMermaid(defineConfig({
  title: 'mem0 Memory Service for OpenClaw',
  description: 'Unified persistent semantic memory service for AI agents, powered by mem0',
  base: '/mem0-memory-service/',
  locales: {
    root: {
      label: 'English',
      lang: 'en',
    },
    zh: {
      label: '中文',
      lang: 'zh-CN',
      link: '/zh/',
      themeConfig: {
        nav: [
          { text: '指南', link: '/zh/guide/getting-started' },
          { text: 'API', link: '/zh/api/cli' },
          { text: 'GitHub', link: 'https://github.com/norrishuang/mem0-memory-service' }
        ],
        sidebar: {
          '/zh/': [
            {
              text: '快速开始',
              items: [
                { text: '安装与部署', link: '/zh/guide/getting-started' },
                { text: '系统架构', link: '/zh/guide/architecture' },
                { text: '配置说明', link: '/zh/guide/configuration' },
                { text: '已知问题与 Patch', link: '/zh/guide/known-issues' },
              ]
            },
            {
              text: '向量存储',
              items: [
                { text: 'OpenSearch（默认）', link: '/zh/guide/vector-stores' },
                { text: 'AWS S3 Vectors', link: '/zh/guide/vector-stores#aws-s3-vectors' },
                { text: '数据迁移工具', link: '/zh/guide/migration' },
              ]
            },
            {
              text: '部署运维',
              items: [
                { text: 'systemd 配置', link: '/zh/deploy/systemd' },
              ]
            },
            {
              text: 'API 参考',
              items: [
                { text: 'CLI 命令', link: '/zh/api/cli' },
                { text: 'REST 接口', link: '/zh/api/server' },
              ]
            }
          ]
        }
      }
    }
  },
  themeConfig: {
    logo: '🧠',
    nav: [
      { text: 'Guide', link: '/guide/getting-started' },
      { text: 'API', link: '/api/cli' },
      { text: 'GitHub', link: 'https://github.com/norrishuang/mem0-memory-service' }
    ],
    sidebar: [
      {
        text: 'Getting Started',
        items: [
          { text: 'Introduction', link: '/guide/getting-started' },
          { text: 'Architecture', link: '/guide/architecture' },
          { text: 'Configuration', link: '/guide/configuration' },
          { text: 'Known Issues & Patches', link: '/guide/known-issues' },
        ]
      },
      {
        text: 'Vector Stores',
        items: [
          { text: 'OpenSearch (Default)', link: '/guide/vector-stores' },
          { text: 'AWS S3 Vectors', link: '/guide/vector-stores#aws-s3-vectors' },
          { text: 'Migration Tool', link: '/guide/migration' },
        ]
      },
      {
        text: 'Deployment',
        items: [
          { text: 'systemd Setup', link: '/deploy/systemd' },
        ]
      },
      {
        text: 'API Reference',
        items: [
          { text: 'CLI', link: '/api/cli' },
          { text: 'REST Server', link: '/api/server' },
        ]
      }
    ],
    socialLinks: [
      { icon: 'github', link: 'https://github.com/norrishuang/mem0-memory-service' }
    ],
    footer: {
      message: 'Released under the MIT License.',
      copyright: 'Copyright © 2025 norrishuang'
    }
  }
}))
