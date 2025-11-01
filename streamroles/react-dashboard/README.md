# React Dashboard Build Instructions

## Development

1. Install dependencies:
```bash
cd streamroles/react-dashboard
npm install
```

2. Start development server:
```bash
npm run dev
```

The dev server will run on http://localhost:5173 with proxy to the bot API.

## Production Build

1. Build for production:
```bash
cd streamroles/react-dashboard
npm run build
```

This will compile and bundle the React app into `streamroles/static/react-build/`.

2. The bot will serve the built files from `/dashboard/react` endpoint.

## Project Structure

```
react-dashboard/
├── src/
│   ├── components/
│   │   ├── Header.jsx          # App header
│   │   ├── TabNavigation.jsx   # Tab switcher
│   │   ├── HelpModal.jsx       # Help modal
│   │   └── tabs/
│   │       ├── OverviewTab.jsx     # Top streamers & charts
│   │       ├── HeatmapTab.jsx      # Activity heatmap
│   │       ├── StreamersTab.jsx    # All streamers list
│   │       ├── BadgesTab.jsx       # Achievements
│   │       └── InsightsTab.jsx     # Community health
│   ├── utils/
│   │   └── api.js              # API client
│   ├── App.jsx                 # Main app component
│   ├── main.jsx                # React entry point
│   └── index.css               # Global styles
├── public/
│   └── index.html              # HTML template
├── package.json                # Dependencies
└── vite.config.js             # Build configuration
```

## Features

- **Component-based architecture**: Clean, maintainable React components
- **State management**: React hooks for efficient state handling
- **API integration**: Centralized API client
- **Responsive design**: Works on desktop and mobile
- **Chart.js integration**: Beautiful, interactive charts
- **Fast builds**: Vite for lightning-fast development and builds
- **Hot reload**: Instant updates during development

## Benefits over Vanilla JS

1. **Maintainability**: Components are isolated and reusable
2. **Testability**: Easy to unit test individual components
3. **Type Safety**: Can add TypeScript later if needed
4. **Performance**: Virtual DOM for efficient updates
5. **Developer Experience**: Hot reload, better error messages
6. **Scalability**: Easy to add new features and components

## Deploying

After building, the static files in `static/react-build/` can be served by:
1. The bot's built-in web server at `/dashboard/react`
2. Any static file server (nginx, Apache, etc.)
3. CDN for better performance

## Notes

- The vanilla JS dashboard in `static/dashboard.html` can remain as a fallback
- API endpoints remain unchanged - React just provides a better frontend
- No changes needed to the Python backend
