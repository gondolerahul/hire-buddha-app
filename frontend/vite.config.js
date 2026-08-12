import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'path';
// https://vitejs.dev/config/
export default defineConfig({
    plugins: [react()],
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
                target: 'http://gateway.hirebuddha.com',
                changeOrigin: true,
                secure: false
            },
            '/reports': {
                target: 'http://gateway.hirebuddha.com',
                changeOrigin: true,
            },
            '/artifact': {
                target: 'http://gateway.hirebuddha.com',
                changeOrigin: true,
            },
        },
    },
});
