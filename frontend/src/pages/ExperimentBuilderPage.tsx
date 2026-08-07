import { useMutation, useQuery } from '@tanstack/react-query'
import { useForm } from 'react-hook-form'
import { useNavigate, useSearchParams } from 'react-router'
import { z } from 'zod'
import { AlgorithmType, SensitivityMode, WeatherMode } from '../generated/api/models'
import { api } from '../shared/api/client'
import { ErrorState, LoadingState, PageHeader } from '../shared/ui/States'

const builderSchema = z.object({
  name: z.string().trim().min(3, 'Вкажіть назву експерименту'),
  datasetVersionId: z.string().trim().min(1, 'Вкажіть ідентифікатор підготовленої версії'),
  sensitivityMode: z.enum([SensitivityMode.CompleteOnly, SensitivityMode.Coverage90]),
  algorithms: z.array(z.string()).min(1, 'Оберіть щонайменше одну ML-модель'),
})

type BuilderValues = z.infer<typeof builderSchema>

const optionalAlgorithms = [
  AlgorithmType.Ridge,
  AlgorithmType.RandomForest,
  AlgorithmType.HistGradientBoosting,
  AlgorithmType.SeasonalNaive168,
] as const

export function ExperimentBuilderPage() {
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const algorithms = useQuery({ queryKey: ['algorithms'], queryFn: () => api.experiments.listAlgorithms() })
  const { register, handleSubmit, setError, formState: { errors } } = useForm<BuilderValues>({
    defaultValues: {
      name: 'Порівняння моделей',
      datasetVersionId: params.get('datasetVersionId') ?? '',
      sensitivityMode: SensitivityMode.Coverage90,
      algorithms: [AlgorithmType.Ridge, AlgorithmType.RandomForest, AlgorithmType.HistGradientBoosting],
    },
  })

  const create = useMutation({
    mutationFn: async (form: BuilderValues) => {
      const parsed = builderSchema.safeParse(form)
      if (!parsed.success) {
        for (const issue of parsed.error.issues) setError(issue.path[0] as keyof BuilderValues, { message: issue.message })
        throw new Error('Перевірте конфігурацію експерименту.')
      }
      const allowed = new Set(optionalAlgorithms)
      const selected = parsed.data.algorithms.filter((algorithm): algorithm is (typeof optionalAlgorithms)[number] => allowed.has(algorithm as (typeof optionalAlgorithms)[number]))
      const result = await api.experiments.createExperiment({
        experimentCreate: {
          name: parsed.data.name,
          datasetVersionId: parsed.data.datasetVersionId,
          weatherMode: WeatherMode.W0,
          sensitivityMode: parsed.data.sensitivityMode,
          algorithms: [AlgorithmType.SeasonalNaive24, ...selected],
        },
      })
      return result
    },
    onSuccess: (result) => navigate(`/experiments/${result.experimentId}`),
  })

  if (algorithms.isLoading) return <LoadingState label="Завантажуємо каталог алгоритмів…" />
  if (algorithms.error) return <ErrorState error={algorithms.error} retry={() => void algorithms.refetch()} />

  const names = new Map(algorithms.data?.map((algorithm) => [algorithm.algorithm, algorithm.displayName]))

  return (
    <>
      <PageHeader title="Новий експеримент" description="Оберіть підготовлену версію й моделі. Baseline Seasonal Naive-24 додається автоматично та не може бути вилучений з порівняння." />
      <form className="panel experiment-form" onSubmit={handleSubmit((values) => create.mutate(values))}>
        <div className="form-grid">
          <label>Назва експерименту<input {...register('name')} aria-invalid={Boolean(errors.name)} />{errors.name && <small className="field-error">{errors.name.message}</small>}</label>
          <label>Версія набору даних<input {...register('datasetVersionId')} placeholder="UUID підготовленої погодинної версії" aria-invalid={Boolean(errors.datasetVersionId)} />{errors.datasetVersionId && <small className="field-error">{errors.datasetVersionId.message}</small>}</label>
          <label>Політика якості<select {...register('sensitivityMode')}><option value={SensitivityMode.Coverage90}>Покриття ≥ 90% (основний режим)</option><option value={SensitivityMode.CompleteOnly}>Тільки повні години</option></select></label>
          <label>Погодні ознаки<select disabled aria-describedby="weather-note"><option>W0 — без майбутньої погоди</option></select><small id="weather-note" className="muted">W1 залишається дослідницьким режимом і недоступний без підключеного погодного набору.</small></label>
        </div>

        <fieldset className="model-picker">
          <legend>Моделі</legend>
          <label className="model-option locked"><input type="checkbox" checked disabled /><span><strong>{names.get(AlgorithmType.SeasonalNaive24) ?? 'Seasonal Naive-24'}</strong><small>Обов’язковий baseline для чесного порівняння.</small></span></label>
          {optionalAlgorithms.map((algorithm) => (
            <label className="model-option" key={algorithm}>
              <input type="checkbox" value={algorithm} {...register('algorithms')} />
              <span><strong>{names.get(algorithm) ?? algorithm}</strong><small>{algorithm === AlgorithmType.SeasonalNaive168 ? 'Додаткова тижнева діагностика.' : 'Модель оцінюється на тих самих хронологічних fold.'}</small></span>
            </label>
          ))}
          {errors.algorithms && <small className="field-error">{errors.algorithms.message}</small>}
        </fieldset>

        {create.error && <ErrorState error={create.error} />}
        <div className="inline-actions"><button className="button primary" type="submit" disabled={create.isPending}>{create.isPending ? 'Створюємо…' : 'Запустити експеримент'}</button></div>
      </form>
    </>
  )
}
