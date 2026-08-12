import React from 'react';
import { motion } from 'framer-motion';
import './JellyButton.css';

interface JellyButtonProps {
    children: React.ReactNode;
    onClick?: () => void;
    type?: 'button' | 'submit' | 'reset';
    variant?: 'primary' | 'secondary' | 'ghost' | 'danger';
    size?: 'sm' | 'md' | 'lg';
    disabled?: boolean;
    className?: string;
    style?: React.CSSProperties;
    roseGold?: boolean;
}

export const JellyButton: React.FC<JellyButtonProps> = ({
    children,
    onClick,
    type = 'button',
    variant = 'primary',
    size = 'md',
    disabled = false,
    className = '',
    style,
    roseGold = false
}) => {
    return (
        <motion.button
            type={type}
            onClick={onClick}
            disabled={disabled}
            className={`jelly-button jelly-button--${variant} jelly-button--${size} ${roseGold ? 'jelly-button--rose-gold' : ''} ${className}`}
            style={style}
            whileHover={!disabled ? { scale: 1.02, y: -2 } : {}}
            whileTap={!disabled ? { scale: 0.98, y: 0 } : {}}
            transition={{ type: "spring", stiffness: 400, damping: 10 }}
        >
            <span className="jelly-button-content">{children}</span>
            <div className="jelly-button-overlay" />
        </motion.button>
    );
};
