import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
// Self-hosted so a fresh clone renders correctly offline, with no font CDN request.
import '@fontsource-variable/inter'
import App from './App.tsx'
import './index.css'

// Applied before first paint to avoid a light flash for anyone on the dark theme.
const stored = localStorage.getItem('recourse.theme')
document.documentElement.dataset.theme =
  stored ?? (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light')

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </StrictMode>,
)
