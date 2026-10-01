import React, { Suspense, lazy } from 'react';
import { AuthProvider } from './hooks/useAuth';
import { ThemeProvider } from './hooks/useTheme';
import { FeatureFlagsProvider } from './hooks/useFeatureFlag';
import { AppRouter } from './router';
// Loaded on its own: it brings in three.js (~600 KB), which kept the login form
// waiting in the entry chunk (FE-17). It is decorative, so nothing waits for it.
const AnimatedBackground = lazy(() =>
    import('./components/layout/AnimatedBackground').then(m => ({ default: m.AnimatedBackground })));
import './styles/tokens.css';
import './styles/theme.css';
import './styles/global.css';

const App: React.FC = () => {
    return (
        <ThemeProvider>
            <AuthProvider>
                <FeatureFlagsProvider>
                    <Suspense fallback={null}>
                        <AnimatedBackground />
                    </Suspense>
                    <AppRouter />
                </FeatureFlagsProvider>
            </AuthProvider>
        </ThemeProvider>
    );
};

export default App;
