import { useState, useEffect, useRef } from 'react';

interface SSEOptions {
    onMessage?: (data: any) => void;
    onError?: (error: Event) => void;
    onComplete?: () => void;
}

export const useSSE = (url: string | null, options: SSEOptions = {}) => {
    const [isConnected, setIsConnected] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const eventSourceRef = useRef<EventSource | null>(null);

    useEffect(() => {
        if (!url) return;

        const token = localStorage.getItem('access_token');
        const eventSource = new EventSource(`${url}?token=${token}`);
        eventSourceRef.current = eventSource;

        eventSource.onopen = () => {
            setIsConnected(true);
            setError(null);
        };

        eventSource.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                if (data.status === 'complete') {
                    options.onComplete?.();
                    eventSource.close();
                } else {
                    options.onMessage?.(data);
                }
            } catch (err) {
                console.error('Failed to parse SSE message:', err);
            }
        };

        eventSource.onerror = (err) => {
            setIsConnected(false);
            setError('Connection error');
            options.onError?.(err);
            eventSource.close();
        };

        return () => {
            eventSource.close();
        };
    }, [url]);

    const close = () => {
        eventSourceRef.current?.close();
        setIsConnected(false);
    };

    return { isConnected, error, close };
};
