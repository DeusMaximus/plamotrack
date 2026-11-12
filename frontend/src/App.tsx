import { Navigate, Route, Routes } from "react-router-dom";

import { Layout } from "./components/Layout";
import { HomePage } from "./pages/HomePage";
import { InventoryPage } from "./pages/InventoryPage";
import { KitsPage } from "./pages/KitsPage";
import { MorePage } from "./pages/MorePage";
import { OrdersPage } from "./pages/OrdersPage";
import { RetailersPage } from "./pages/RetailersPage";
import { AboutSection } from "./pages/settings/AboutSection";
import { AccessTokensSection } from "./pages/settings/AccessTokensSection";
import { DataSection } from "./pages/settings/DataSection";
import { GeneralSection } from "./pages/settings/GeneralSection";
import { LanguageSection } from "./pages/settings/LanguageSection";
import { SettingsIndex, SettingsPage } from "./pages/settings/SettingsPage";

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<HomePage />} />
        {/* The former kanban board (§13.2, #233): old links and bookmarks land
            on Home, the way /data lands on Settings below. */}
        <Route path="/board" element={<Navigate to="/" replace />} />
        <Route path="/kits" element={<KitsPage />} />
        <Route path="/orders" element={<OrdersPage />} />
        <Route path="/inventory" element={<InventoryPage />} />
        <Route path="/retailers" element={<RetailersPage />} />
        {/* The phone shell's fifth tab (§13.7); no other shell links to it. */}
        <Route path="/more" element={<MorePage />} />
        <Route path="/settings" element={<SettingsPage />}>
          <Route index element={<SettingsIndex />} />
          <Route path="general" element={<GeneralSection />} />
          <Route path="language" element={<LanguageSection />} />
          <Route path="data" element={<DataSection />} />
          <Route path="tokens" element={<AccessTokensSection />} />
          <Route path="about" element={<AboutSection />} />
        </Route>
        {/* The former Data-management route; old links and bookmarks land on
            the Settings section that superseded it. */}
        <Route path="/data" element={<Navigate to="/settings/data" replace />} />
      </Route>
    </Routes>
  );
}
