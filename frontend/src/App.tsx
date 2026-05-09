import { Routes, Route, Navigate } from "react-router-dom";
import { AuthProvider } from "./context/AuthContext";
import { I18nProvider } from "./i18n/I18nContext";
import ProtectedRoute from "./components/ProtectedRoute";
import UploadPage from "./pages/UploadPage";
import AuditStatusPage from "./pages/AuditStatusPage";
import ResultsPage from "./pages/ResultsPage";
import BatchListPage from "./pages/BatchListPage";
import RulesPage from "./pages/RulesPage";
import LoginPage from "./pages/LoginPage";
import MonitorPage from "./pages/MonitorPage";
import HistoryPage from "./pages/HistoryPage";
import Layout from "./components/Layout";

function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        element={
          <ProtectedRoute>
            <Layout />
          </ProtectedRoute>
        }
      >
        <Route path="/" element={<Navigate to="/upload" replace />} />
        <Route path="/upload" element={<UploadPage />} />
        <Route path="/audit/:taskId" element={<AuditStatusPage />} />
        <Route path="/results/:taskId" element={<ResultsPage />} />
        <Route path="/batch" element={<BatchListPage />} />
        <Route path="/rules" element={<RulesPage />} />
        <Route path="/monitor" element={<MonitorPage />} />
        <Route path="/history" element={<HistoryPage />} />
      </Route>
    </Routes>
  );
}

export default function App() {
  return (
    <I18nProvider>
      <AuthProvider>
        <AppRoutes />
      </AuthProvider>
    </I18nProvider>
  );
}
