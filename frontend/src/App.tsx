import React from 'react';
import { AuthProvider } from './hooks/useAuth';
import { ThemeProvider } from './hooks/useTheme';
import { FeatureFlagsProvider } from './hooks/useFeatureFlag';
import { AppRouter } from './router';
import { AnimatedBackground } from './components/layout/AnimatedBackground';
import './styles/tokens.css';
import './styles/theme.css';
import './styles/global.css';

const App: React.FC = () => {
    return (
        <ThemeProvider>
            <AuthProvider>
                <FeatureFlagsProvider>
                    <AnimatedBackground />
                    <AppRouter />
                </FeatureFlagsProvider>
            </AuthProvider>
        </ThemeProvider>
    );
};

export default App;
