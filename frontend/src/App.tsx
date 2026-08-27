import { Navigate, Route, Routes } from "react-router-dom";

import { Layout } from "./components/Layout";
import { BoardPage } from "./pages/BoardPage";
import { InventoryPage } from "./pages/InventoryPage";
import { KitsPage } from "./pages/KitsPage";
import { OrdersPage } from "./pages/OrdersPage";
import { RetailersPage } from "./pages/RetailersPage";
import { AboutSection } from "./pages/settings/AboutSection";
import { DataSection } from "./pages/settings/DataSection";
import { GeneralSection } from "./pages/settings/GeneralSection";
import { LanguageSection } from "./pages/settings/LanguageSection";
import { SettingsPage } from "./pages/settings/SettingsPage";

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Navigate to="/board" replace />} />
        <Route path="/board" element={<BoardPage />} />
        <Route path="/kits" element={<KitsPage />} />
        <Route path="/orders" element={<OrdersPage />} />
        <Route path="/inventory" element={<InventoryPage />} />
        <Route path="/retailers" element={<RetailersPage />} />
        <Route path="/settings" element={<SettingsPage />}>
          <Route index element={<Navigate to="general" replace />} />
          <Route path="general" element={<GeneralSection />} />
          <Route path="language" element={<LanguageSection />} />
          <Route path="data" element={<DataSection />} />
          <Route path="about" element={<AboutSection />} />
        </Route>
        {/* The pre-M5.1 home of Data management — old links and bookmarks land
            on the section it became. */}
        <Route path="/data" element={<Navigate to="/settings/data" replace />} />
      </Route>
    </Routes>
  );
}
