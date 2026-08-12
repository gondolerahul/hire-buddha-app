import React, { useState, InputHTMLAttributes } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import './GlassInput.css';

interface GlassInputProps extends InputHTMLAttributes<HTMLInputElement> {
    label?: string;
    error?: string;
    icon?: React.ReactNode;
}

export const GlassInput: React.FC<GlassInputProps> = ({
    label,
    error,
    icon,
    className = '',
    onFocus,
    onBlur,
    ...props
}) => {
    const [isFocused, setIsFocused] = useState(false);
    const hasValue = props.value !== undefined && props.value !== null && props.value.toString().length > 0;

    const handleFocus = (e: React.FocusEvent<HTMLInputElement>) => {
        setIsFocused(true);
        onFocus?.(e);
    };

    const handleBlur = (e: React.FocusEvent<HTMLInputElement>) => {
        setIsFocused(false);
        onBlur?.(e);
    };

    return (
        <div className={`glass-input-wrapper ${className}`}>
            <div className={`glass-input-container ${isFocused ? 'focused' : ''} ${error ? 'error' : ''} ${hasValue ? 'has-value' : ''}`}>
                {label && (
                    <motion.label
                        className="glass-input-label"
                        animate={{
                            y: (isFocused || hasValue) ? -28 : 0,
                            x: (isFocused || hasValue) ? -4 : 0,
                            scale: (isFocused || hasValue) ? 0.85 : 1,
                            color: isFocused ? 'var(--color-accent-primary)' : (hasValue ? 'var(--color-text-secondary)' : 'var(--color-text-tertiary)')
                        }}
                        transition={{ duration: 0.2, ease: "easeOut" }}
                    >
                        {label}
                    </motion.label>
                )}

                <div className="glass-input-inner">
                    {icon && <div className="glass-input-icon">{icon}</div>}
                    <input
                        className="glass-input-field"
                        onFocus={handleFocus}
                        onBlur={handleBlur}
                        {...props}
                        placeholder={(isFocused || hasValue || !label) ? props.placeholder : ''}
                    />
                </div>

                <motion.div
                    className="glass-input-border"
                    initial={{ scaleX: 0 }}
                    animate={{ scaleX: isFocused ? 1 : 0 }}
                    transition={{ duration: 0.3 }}
                />
            </div>

            <AnimatePresence>
                {error && (
                    <motion.span
                        className="glass-input-error-msg"
                        initial={{ opacity: 0, y: -10 }}
                        animate={{ opacity: 1, y: 0 }}
                        exit={{ opacity: 0, y: -10 }}
                    >
                        {error}
                    </motion.span>
                )}
            </AnimatePresence>
        </div>
    );
};
