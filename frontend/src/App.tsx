import { Navigate, Route, Routes } from 'react-router'
import { AppShell } from './app/AppShell'
import { AnalysisPage } from './pages/AnalysisPage'
import { DashboardPage } from './pages/DashboardPage'
import { DataQualityPage } from './pages/DataQualityPage'
import { DatasetDetailsPage, DatasetsPage } from './pages/DatasetsPage'
import { ImportWizardPage } from './pages/ImportWizardPage'
import { EmptyState } from './shared/ui/States'

function DeferredPage({ title }: { title: string }) {
  return <EmptyState title={title}><p>Цей функціональний модуль буде реалізовано окремим наступним завданням.</p></EmptyState>
}

function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<DashboardPage />} />
        <Route path="datasets" element={<DatasetsPage />} />
        <Route path="datasets/new" element={<ImportWizardPage />} />
        <Route path="datasets/:datasetId" element={<DatasetDetailsPage />} />
        <Route path="dataset-versions/:versionId/quality" element={<DataQualityPage />} />
        <Route path="dataset-versions/:versionId/analysis" element={<AnalysisPage />} />
        <Route path="experiments" element={<DeferredPage title="Експерименти" />} />
        <Route path="forecasts" element={<DeferredPage title="Прогнози" />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  )
}

export default App
