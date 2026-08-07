import { AnalyticsApi, DatasetsApi, ExperimentsApi, ExportsApi, ForecastsApi, ImportsApi, JobsApi, SystemApi } from '../../generated/api/apis'
import { Configuration } from '../../generated/api/runtime'

const basePath = import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, '') ?? ''
const configuration = new Configuration({ basePath })

export const api = {
  analytics: new AnalyticsApi(configuration),
  datasets: new DatasetsApi(configuration),
  experiments: new ExperimentsApi(configuration),
  exports: new ExportsApi(configuration),
  forecasts: new ForecastsApi(configuration),
  imports: new ImportsApi(configuration),
  jobs: new JobsApi(configuration),
  system: new SystemApi(configuration),
}
