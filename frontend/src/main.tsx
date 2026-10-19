import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
// Inter is bundled rather than linked from Google Fonts: a third-party
// stylesheet cannot carry Subresource Integrity (Google varies it per browser),
// and serving it ourselves stops every page view telling Google who visited.
import '@fontsource/inter/300.css';
import '@fontsource/inter/400.css';
import '@fontsource/inter/500.css';
import '@fontsource/inter/600.css';
import '@fontsource/inter/700.css';
import './index.css';

ReactDOM.createRoot(document.getElementById('root')!).render(
    <React.StrictMode>
        <App />
    </React.StrictMode>,
);
