import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';

// The font index.html preloaded, applied once the app starts (FE-22: never render-blocking;
// no inline onload handler, which the content security policy would refuse).
const FONT_CSS = document.querySelector<HTMLLinkElement>('link[rel="preload"][as="style"]');
if (FONT_CSS) {
    const sheet = document.createElement('link');
    sheet.rel = 'stylesheet';
    sheet.href = FONT_CSS.href;
    document.head.appendChild(sheet);
}

ReactDOM.createRoot(document.getElementById('root')!).render(
    <React.StrictMode>
        <App />
    </React.StrictMode>
);
