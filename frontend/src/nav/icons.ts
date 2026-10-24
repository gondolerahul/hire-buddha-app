/** nav/icons — the lucide icons the navigation config names (Phase 15 T9-1). */
import {
    Activity, AlertTriangle, AppWindow, Archive, BadgeCheck, BarChart3, Blocks, BookOpen, Bot, BrainCircuit,
    Building2, ClipboardCheck, Code2, Coins, Database, FileText, Flag, Gauge, HeartHandshake, KeyRound, Layers,
    LayoutGrid, LineChart, Megaphone, Network, Phone, PhoneCall, PiggyBank, Plug, Receipt, Route, Scale, ScrollText,
    Settings, ShieldAlert, ShieldCheck, Sigma, Sparkles, Star, Tag, Target, TerminalSquare, Timer, TrendingUp, Users,
    Wallet, Wrench, type LucideIcon,
} from 'lucide-react';

export const ICONS: Record<string, LucideIcon> = {
    Activity, AlertTriangle, AppWindow, Archive, BadgeCheck, BarChart3, Blocks, BookOpen, Bot, BrainCircuit,
    Building2, ClipboardCheck, Code2, Coins, Database, FileText, Flag, Gauge, HeartHandshake, KeyRound, Layers,
    LayoutGrid, LineChart, Megaphone, Network, Phone, PhoneCall, PiggyBank, Plug, Receipt, Route, Scale, ScrollText,
    Settings, ShieldAlert, ShieldCheck, Sigma, Sparkles, Star, Tag, Target, TerminalSquare, Timer, TrendingUp, Users,
    Wallet, Wrench,
};

export function iconFor(name: string): LucideIcon {
    return ICONS[name] ?? LayoutGrid;
}
