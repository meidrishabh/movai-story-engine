import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// The UI is its own app on port 5173; the API runs separately (see VITE_API_URL) and allows this origin through CORS.
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, strictPort: true },
})
