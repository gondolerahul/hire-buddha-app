/**
 * hooks/useFeatureFlag — Resolve a Phase 11 feature flag for the
 * current user / company / (optionally) run.
 *
 * Resolution order:
 *   1. ``opts.runMeta?.[flagKey]`` — per-run override embedded in
 *      ExecutionRun.input_data.feature_flags by the caller.
 *   2. Per-company override (from `/feature_flags/me`).
 *   3. Global override (same response).
 *   4. Hard-coded backend default.
 *   5. ``opts.defaultValue`` (the local fallback).
 *
 * The flag map is fetched once at boot via the `FeatureFlagsProvider`
 * (see below) and cached in a React context. Pages don't need to wait
 * on the network for individual flag reads.
 */
import React, { createContext, useContext, useEffect, useMemo, useState } from 'react';

import { featureFlagsService } from '@/services/feature_flags.service';
import type { FeatureFlagsResponse } from '@/types/agentKernel';

interface FeatureFlagsContextValue {
    loaded: boolean;
    response: FeatureFlagsResponse;
    refresh: () => Promise<void>;
}

const _EMPTY: FeatureFlagsResponse = {
    defaults: {},
    numeric_defaults: {},
    overrides: {},
};

const FeatureFlagsContext = createContext<FeatureFlagsContextValue>({
    loaded: false,
    response: _EMPTY,
    refresh: async () => undefined,
});

// Polling cadence — matches the backend FeatureFlags process-cache TTL
// so an admin change is visible to the SPA within one refresh window.
const _POLL_INTERVAL_MS = 60_000;

export const FeatureFlagsProvider: React.FC<{ children: React.ReactNode }> = ({
    children,
}) => {
    const [response, setResponse] = useState<FeatureFlagsResponse>(_EMPTY);
    const [loaded, setLoaded] = useState(false);

    const refresh = useMemo(
        () => async () => {
            try {
                const next = await featureFlagsService.fetchMine();
                setResponse(next);
            } catch (err) {
                // Silently fall back to defaults; pages will use their
                // local `defaultValue` instead.
                // eslint-disable-next-line no-console
                console.warn('[FeatureFlags] fetch failed', err);
            } finally {
                setLoaded(true);
            }
        },
        [],
    );

    useEffect(() => {
        void refresh();
        // Re-fetch when the tab regains focus (admin just toggled in
        // another window).
        const onVisibility = () => {
            if (document.visibilityState === 'visible') {
                void refresh();
            }
        };
        document.addEventListener('visibilitychange', onVisibility);

        // Background polling — quiet drift toward eventual consistency
        // without a WebSocket. Sixty-second cadence matches backend TTL.
        const handle = window.setInterval(() => {
            if (document.visibilityState === 'visible') {
                void refresh();
            }
        }, _POLL_INTERVAL_MS);

        return () => {
            document.removeEventListener('visibilitychange', onVisibility);
            window.clearInterval(handle);
        };
    }, [refresh]);

    const value = useMemo(
        () => ({ loaded, response, refresh }),
        [loaded, response, refresh],
    );
    return React.createElement(
        FeatureFlagsContext.Provider,
        { value },
        children,
    );
};

interface UseFeatureFlagOptions {
    defaultValue?: boolean;
    runMeta?: Record<string, boolean | undefined>;
}

export function useFeatureFlag(
    flagKey: string,
    opts: UseFeatureFlagOptions = {},
): boolean {
    const ctx = useContext(FeatureFlagsContext);
    const { defaultValue = false, runMeta } = opts;

    // 1. Per-run override
    if (runMeta && typeof runMeta[flagKey] === 'boolean') {
        return runMeta[flagKey] as boolean;
    }

    if (!ctx.loaded) return defaultValue;

    const override = ctx.response.overrides?.[flagKey];
    // 2. Company override beats global.
    if (override && typeof override.company === 'boolean') return override.company;
    if (override && typeof override.global === 'boolean') return override.global;

    // 3. Backend defaults.
    const fromDefault = ctx.response.defaults?.[flagKey];
    if (typeof fromDefault === 'boolean') return fromDefault;

    // 4. Caller fallback.
    return defaultValue;
}

/**
 * Read a numeric feature flag (e.g. `bandit.epsilon`).
 */
export function useNumericFlag(
    flagKey: string,
    fallback: number,
): number {
    const ctx = useContext(FeatureFlagsContext);
    if (!ctx.loaded) return fallback;
    const v = ctx.response.numeric_defaults?.[flagKey];
    return typeof v === 'number' ? v : fallback;
}
