import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

// A page load (the browser asks for HTML) is the SPA's, not the API's: the
// SPA's own /reports/* pages share the prefix of the API's static /reports
// mount (FE-24). Returning a path serves it from the dev server instead.
const spaPageLoad = (req: { headers: { accept?: string } }) =>
    (req.headers.accept || '').includes('text/html') ? '/index.html' : undefined

// https://vitejs.dev/config/
export default defineConfig(({ mode }) => {
    // Proxy targets come from the environment; the default is the local API,
    // not production (FE-04).
    const env = loadEnv(mode, process.cwd(), '')
    const target = env.VITE_PROXY_TARGET || 'http://localhost:8000'

    return {
        plugins: [react()],
        build: {
            rollupOptions: {
                output: {
                    // Shared libraries get their own chunks, named and stable,
                    // instead of wherever Rollup's heuristics put them (FE-22).
                    manualChunks: {
                        'vendor-react': ['react', 'react-dom', 'react-router-dom'],
                        'vendor-charts': ['recharts'],
                        'vendor-flow': ['reactflow', 'dagre'],
                    },
                },
            },
        },
        resolve: {
            alias: {
                '@': path.resolve(__dirname, './src'),
                '@/components': path.resolve(__dirname, './src/components'),
                '@/pages': path.resolve(__dirname, './src/pages'),
                '@/services': path.resolve(__dirname, './src/services'),
                '@/hooks': path.resolve(__dirname, './src/hooks'),
                '@/styles': path.resolve(__dirname, './src/styles'),
                '@/types': path.resolve(__dirname, './src/types'),
                '@/utils': path.resolve(__dirname, './src/utils'),
            },
        },
        server: {
            allowedHosts: ["dev.hirebuddha.com", "app.hirebuddha.com"],
            hmr: false, // Completely disable HMR for testing
            host: '0.0.0.0', // Listen on all interfaces
            port: 3000,
            watch: {
                // Prevent watching too many files and false positives
                usePolling: false,
                interval: 1000,
                ignored: ['**/node_modules/**', '**/.git/**']
            },
            proxy: {
                '/api': {
                    target,
                    changeOrigin: true,
                    secure: false
                },
                '/reports': {
                    target,
                    changeOrigin: true,
                    bypass: spaPageLoad,
                },
                '/artifact': {
                    target,
                    changeOrigin: true,
                },
            },
        },
    }
})
