// First so the catalogue is registered before any module resolves a string.
import "./i18n";
// The interface typeface, bundled: no font host is contacted (§13.1).
import "@fontsource-variable/inter";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";

import App from "./App.tsx";
import { AuthGate } from "./components/AuthGate";
import { watchTheme } from "./lib/theme";
import "./index.css";

// public/theme.js put the theme on <html> before first paint; from here the app
// keeps it current (the device's scheme under "system", another tab's switch).
watchTheme();

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: 1, staleTime: 5_000 },
  },
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AuthGate>
          <App />
        </AuthGate>
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
);
