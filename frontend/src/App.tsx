import { Navigate, Route, Routes } from "react-router-dom";

import { Layout } from "./components/Layout";
import { BoardPage } from "./pages/BoardPage";
import { DataPage } from "./pages/DataPage";
import { InventoryPage } from "./pages/InventoryPage";
import { KitsPage } from "./pages/KitsPage";
import { OrdersPage } from "./pages/OrdersPage";
import { RetailersPage } from "./pages/RetailersPage";

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
        <Route path="/data" element={<DataPage />} />
      </Route>
    </Routes>
  );
}
