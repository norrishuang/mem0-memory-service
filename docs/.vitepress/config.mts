import { defineConfig } from 'vitepress'

export default defineConfig({
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
      themeConfig: {
        nav: [
          { text: '指南', link: '/zh/guide/getting-started' },
          { text: 'GitHub', link: 'https://github.com/norrishuang/mem0-memory-service' }
        ],
        sidebar: [
          {
            text: '指南',
            items: [
              { text: '快速开始', link: '/zh/guide/getting-started' },
            ]
          }
        ]
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
          { text: 'Configuration', link: '/guide/configuration' },
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
})
