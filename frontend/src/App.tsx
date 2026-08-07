import { Navigate, Route, Routes } from 'react-router'
import { AppShell } from './app/AppShell'
import { AnalysisPage } from './pages/AnalysisPage'
import { DashboardPage } from './pages/DashboardPage'
import { DataQualityPage } from './pages/DataQualityPage'
import { DatasetDetailsPage, DatasetsPage } from './pages/DatasetsPage'
import { ExperimentBuilderPage } from './pages/ExperimentBuilderPage'
import { ExperimentDetailsPage } from './pages/ExperimentDetailsPage'
import { ExperimentsPage } from './pages/ExperimentsPage'
import { ForecastBuilderPage, ForecastDetailsPage, ForecastsPage } from './pages/ForecastPages'
import { ImportWizardPage } from './pages/ImportWizardPage'
import { ModelComparisonPage } from './pages/ModelComparisonPage'

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
        <Route path="experiments" element={<ExperimentsPage />} />
        <Route path="experiments/new" element={<ExperimentBuilderPage />} />
        <Route path="experiments/:experimentId" element={<ExperimentDetailsPage />} />
        <Route path="experiments/:experimentId/comparison" element={<ModelComparisonPage />} />
        <Route path="forecasts" element={<ForecastsPage />} />
        <Route path="forecasts/new" element={<ForecastBuilderPage />} />
        <Route path="forecasts/:forecastId" element={<ForecastDetailsPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  )
}

export default App
