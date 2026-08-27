import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
// Self-hosted so a fresh clone renders correctly offline, with no font CDN request.
import '@fontsource-variable/inter'
import App from './App.tsx'
import './index.css'

// Dark-mode first (Addendum 4, 35.1). The system preference is deliberately NOT
// consulted: most machines report light, so deferring to it would mean a dark-first
// product almost never appears dark. Dark is the default; the toggle in the sidebar is
// how someone chooses otherwise, and that choice is what persists.
//
// Applied before first paint, because a light flash on a dark-first product is the most
// visible bug a theme can have.
const stored = localStorage.getItem('recourse.theme')
document.documentElement.dataset.theme = stored === 'light' ? 'light' : 'dark'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </StrictMode>,
)
