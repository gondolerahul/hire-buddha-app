// Design-only entry. Reuses the application background without changing it.
import React from '../../../frontend/node_modules/react';
import { createRoot } from '../../../frontend/node_modules/react-dom/client';
import { AnimatedBackground } from '../../../frontend/src/components/layout/AnimatedBackground';
createRoot(document.getElementById('background-root')!).render(<AnimatedBackground />);
