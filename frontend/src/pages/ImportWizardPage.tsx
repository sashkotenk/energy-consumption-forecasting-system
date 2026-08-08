import { useMutation, useQuery } from '@tanstack/react-query'
import { useEffect, useMemo, useState } from 'react'
import { useForm, useWatch } from 'react-hook-form'
import { Link, useSearchParams } from 'react-router'
import { z } from 'zod'
import { ImportProfile } from '../generated/api/models'
import { api } from '../shared/api/client'
import { isTerminalJob, useJobPolling } from '../shared/query/useJobPolling'
import { ErrorState, PageHeader, StatusBadge } from '../shared/ui/States'

const schema = z.object({
  datasetName: z.string().trim().min(2, 'Вкажіть назву набору даних'),
  profile: z.enum(['uci', 'generic_csv']),
  delimiter: z.string().max(2),
  timestampColumn: z.string().trim(),
  valueColumn: z.string().trim(),
  targetSemantic: z.enum(['energy', 'active_power']),
  unit: z.enum(['kwh', 'wh', 'kw', 'w']),
  timezone: z.string().trim().min(1, 'Вкажіть часовий пояс'),
  duplicatePolicy: z.enum(['reject', 'keep_first', 'keep_last', 'mean']),
})

type FormValues = z.infer<typeof schema>
const steps = ['Джерело', 'Файл', 'Попередній перегляд', 'Відповідність колонок', 'Одиниці й час', 'Дублікати', 'Підтвердження', 'Виконання']

export function ImportWizardPage() {
  const [params] = useSearchParams()
  const existingDatasetId = params.get('dataset')
  const [step, setStep] = useState(0)
  const [file, setFile] = useState<File | null>(null)
  const [accepted, setAccepted] = useState<{ importId: string; jobId: string } | null>(null)
  const { control, register, getValues, formState: { errors }, setError, setValue } = useForm<FormValues>({ defaultValues: { datasetName: 'Новий набір', profile: 'uci', delimiter: ',', timestampColumn: 'timestamp', valueColumn: 'energy_kwh', targetSemantic: 'active_power', unit: 'kw', timezone: 'Europe/Paris', duplicatePolicy: 'reject' } })
  const profile = useWatch({ control, name: 'profile' })
  const timezone = useWatch({ control, name: 'timezone' })
  const unit = useWatch({ control, name: 'unit' })
  const targetSemantic = useWatch({ control, name: 'targetSemantic' })
  const duplicatePolicy = useWatch({ control, name: 'duplicatePolicy' })
  const job = useJobPolling(accepted?.jobId)
  const importResult = useQuery({ queryKey: ['dataset-import', accepted?.importId], queryFn: () => api.imports.getDatasetImport({ importId: accepted!.importId }), enabled: Boolean(accepted?.importId) && isTerminalJob(job.data?.status) })

  useEffect(() => {
    if (profile === 'uci') {
      setValue('targetSemantic', 'active_power')
      setValue('unit', 'kw')
      setValue('timezone', 'Europe/Paris')
    } else {
      setValue('targetSemantic', 'energy')
      setValue('unit', 'kwh')
      setValue('timezone', 'UTC')
    }
  }, [profile, setValue])

  const submit = useMutation({
    mutationFn: async () => {
      const parsed = schema.safeParse(getValues())
      if (!parsed.success) {
        for (const issue of parsed.error.issues) setError(issue.path[0] as keyof FormValues, { message: issue.message })
        throw new Error('Перевірте поля форми перед запуском імпорту.')
      }
      if (!file) throw new Error('Оберіть CSV або TXT-файл.')
      if (parsed.data.profile === 'generic_csv' && (!parsed.data.timestampColumn || !parsed.data.valueColumn)) throw new Error('Для користувацького CSV потрібно зіставити часову та цільову колонки.')
      const datasetId = existingDatasetId ?? (await api.datasets.createDataset({ datasetCreate: { name: parsed.data.datasetName, description: 'Імпортовано через вебінтерфейс EnergyForecast' } })).id
      const generic = parsed.data.profile === 'generic_csv'
      const result = await api.imports.createDatasetImport({
        datasetId,
        file,
        importProfile: generic ? ImportProfile.GenericCsv : ImportProfile.Uci,
        delimiter: generic ? parsed.data.delimiter : undefined,
        duplicatePolicy: parsed.data.duplicatePolicy,
        timestampColumn: generic ? parsed.data.timestampColumn : undefined,
        energyColumn: generic && parsed.data.targetSemantic === 'energy' ? parsed.data.valueColumn : undefined,
        powerColumn: generic && parsed.data.targetSemantic === 'active_power' ? parsed.data.valueColumn : undefined,
        targetSemantic: generic ? parsed.data.targetSemantic : 'active_power',
        timestampSemantics: 'interval_start',
        timezone: parsed.data.timezone,
        unit: generic ? parsed.data.unit : 'kw',
      })
      setAccepted({ importId: result.importId, jobId: result.jobId })
      setStep(7)
      return result
    },
  })

  const preview = useMemo(() => file ? `${file.name} · ${(file.size / 1024 / 1024).toFixed(2)} МБ · ${file.type || 'тип не вказано'}` : 'Файл ще не обрано', [file])
  const canContinue = step === 0 || (step !== 1 || Boolean(file))

  return (
    <>
      <PageHeader title="Майстер імпорту" description="Створіть незмінну сиру версію даних із відтворюваними параметрами імпорту." />
      <ol className="stepper" aria-label="Етапи імпорту">{steps.map((label, index) => <li key={label} className={index === step ? 'current' : index < step ? 'done' : ''}><span>{index + 1}</span>{label}</li>)}</ol>
      <section className="panel wizard" aria-live="polite">
        {step === 0 && <><h2>Джерело</h2><label>Профіль імпорту<select {...register('profile')}><option value="uci">UCI Individual Household Electric Power Consumption</option><option value="generic_csv">Користувацький CSV</option></select></label>{!existingDatasetId && <label>Назва набору<input {...register('datasetName')} aria-invalid={Boolean(errors.datasetName)} />{errors.datasetName && <small className="field-error">{errors.datasetName.message}</small>}</label>}<p className="muted">Профіль автоматично встановлює безпечні початкові одиниці та часовий контекст; для користувацького CSV їх можна змінити на наступних кроках.</p></>}
        {step === 1 && <><h2>Файл</h2><label className="file-drop">CSV або TXT<input type="file" accept=".csv,.txt,text/csv,text/plain" onChange={(event) => setFile(event.target.files?.[0] ?? null)} /><span>{preview}</span></label><p className="muted">Файл передається через керований multipart endpoint; шлях до локального сховища не розкривається.</p></>}
        {step === 2 && <><h2>Попередній перегляд</h2><p><strong>{preview}</strong></p><p>Після постановки імпорту backend збереже визначений формат і preview у записі операції. Вміст файлу не інтерпретується браузером як джерело істини.</p></>}
        {step === 3 && <><h2>Відповідність колонок</h2>{profile === 'uci' ? <p>Для UCI застосовується зафіксований профіль Date + Time + Global_active_power; цільова семантика — активна потужність.</p> : <div className="form-grid"><label>Роздільник<input {...register('delimiter')} /></label><label>Часова колонка<input {...register('timestampColumn')} /></label><label>Цільова колонка<input {...register('valueColumn')} /></label><label>Семантика<select {...register('targetSemantic')}><option value="energy">Енергія за інтервал</option><option value="active_power">Середня активна потужність</option></select></label></div>}</>}
        {step === 4 && <><h2>Одиниці й часовий контекст</h2>{profile === 'uci' ? <div className="form-grid"><label>Одиниця<input value="кВт" readOnly aria-describedby="uci-unit-note" /><small id="uci-unit-note" className="muted">Global_active_power в офіційному UCI-профілі інтерпретується як кВт.</small></label><label>Часовий пояс<input {...register('timezone')} />{errors.timezone && <small className="field-error">{errors.timezone.message}</small>}</label></div> : <div className="form-grid"><label>Одиниця<select {...register('unit')}><option value="kwh">кВт·год</option><option value="wh">Вт·год</option><option value="kw">кВт</option><option value="w">Вт</option></select></label><label>Часовий пояс<input {...register('timezone')} />{errors.timezone && <small className="field-error">{errors.timezone.message}</small>}</label></div>}</>}
        {step === 5 && <><h2>Політика дублікатів</h2><label>Оброблення однакових часових міток<select {...register('duplicatePolicy')}><option value="reject">Відхилити конфлікт</option><option value="keep_first">Залишити перше</option><option value="keep_last">Залишити останнє</option><option value="mean">Середнє значення</option></select></label><p className="muted">Конфліктний дублікат не зникає без явно обраної політики.</p></>}
        {step === 6 && <><h2>Підтвердження</h2><dl className="details-grid"><div><dt>Профіль</dt><dd>{profile === 'uci' ? 'UCI household power' : 'Користувацький CSV'}</dd></div><div><dt>Файл</dt><dd>{file?.name ?? '—'}</dd></div><div><dt>Ціль</dt><dd>{profile === 'uci' ? 'active_power · kW' : `${targetSemantic} · ${unit}`}</dd></div><div><dt>Часовий пояс</dt><dd>{timezone}</dd></div><div><dt>Дублікати</dt><dd>{duplicatePolicy}</dd></div></dl>{submit.error && <ErrorState error={submit.error} />}<button className="button primary" type="button" onClick={() => submit.mutate()} disabled={submit.isPending}>{submit.isPending ? 'Ставимо в чергу…' : 'Запустити імпорт'}</button></>}
        {step === 7 && <><h2>Виконання</h2>{accepted ? <><p>Завдання <code>{accepted.jobId}</code></p><p>Стан: <StatusBadge value={job.data?.status ?? 'queued'} /></p>{job.data && <progress max="100" value={job.data.progressPct} aria-label="Прогрес імпорту" />}{job.error && <ErrorState error={job.error} retry={() => void job.refetch()} />}{importResult.data && <div className="success-box"><strong>Імпорт завершено.</strong><p>Сира незмінна версія: <code>{importResult.data.datasetVersionId}</code></p><p className="muted">Наступний крок — перевірити якість і підготувати погодинну версію. Аналіз запускається вже для підготовлених даних.</p><div className="inline-actions"><Link className="button primary" to={`/dataset-versions/${importResult.data.datasetVersionId}/quality`}>Перевірити якість</Link></div></div>}</> : <p>Очікуємо запуск.</p>}</>}
        {step < 6 && <div className="wizard-actions"><button type="button" onClick={() => setStep((value) => Math.max(0, value - 1))} disabled={step === 0}>Назад</button><button className="button primary" type="button" onClick={() => canContinue && setStep((value) => Math.min(6, value + 1))} disabled={!canContinue}>Далі</button></div>}
      </section>
    </>
  )
}
