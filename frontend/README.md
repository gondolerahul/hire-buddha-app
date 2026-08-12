# HireBuddha Frontend

Modern React + TypeScript frontend with Liquid Glass design aesthetic for the HireBuddha AI Agent Platform.

## Tech Stack

- **Framework**: React 18 + TypeScript
- **Build Tool**: Vite
- **Routing**: React Router v6
- **Animations**: Framer Motion
- **Forms**: React Hook Form + Zod
- **API**: Axios
- **Icons**: Lucide React

## Design System

The app implements the "Liquid Glass / Rose Gold" aesthetic with:
- Glass morphism effects (backdrop-filter blur)
- Animated liquid background
- Rose Gold gradient accents
- Spring-based micro-animations

## Getting Started

### Prerequisites

- Node.js 18+ and npm

### Installation

```bash
# Install dependencies
npm install

# Start development server
npm run dev

# Build for production
npm run build

# Preview production build
npm run preview
```

The app will be available at `http://localhost:3000`

### Environment Variables

Copy `.env.example` to `.env` and configure:

```env
VITE_API_BASE_URL=http://localhost:8000/api/v1
VITE_GOOGLE_CLIENT_ID=your_google_client_id
VITE_MICROSOFT_CLIENT_ID=your_microsoft_client_id
```

## Project Structure

```
src/
├── components/
│   ├── ui/              # Reusable UI components (GlassCard, JellyButton, etc.)
│   └── layout/          # Layout components (MainLayout, etc.)
├── pages/
│   ├── auth/            # Authentication pages
│   ├── ai/              # AI agent pages
│   └── Dashboard.tsx    # Dashboard page
├── services/            # API services
├── hooks/               # Custom React hooks
├── router/              # Routing configuration
├── styles/              # Global styles and design tokens
├── types/               # TypeScript interfaces
└── utils/               # Utility functions
```

## Features

### Implemented
- ✅ Authentication (Login/Register)
- ✅ Protected routing
- ✅ Dashboard with stats
- ✅ Agent list view
- ✅ Glass morphism design system
- ✅ Responsive layout

### Coming Soon
- 🔜 Agent builder/editor
- 🔜 Workflow builder
- 🔜 Execution interface
- 🔜 Knowledge base management
- 🔜 Billing dashboard
- 🔜 System configuration

## Development

The frontend connects to the backend API at `http://localhost:8000/api/v1` (configurable via `.env`).

Make sure the backend is running before starting the development server.

## License

Proprietary - HireBuddha Platform
