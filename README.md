## 🌐 English (EN)
# EnergyForecast

**EnergyForecast** is a full-stack software system for importing, validating, analysing and forecasting hourly electricity consumption with machine-learning methods.

This repository is the implementation repository for the course project **“A Software System for Energy Consumption Analysis and Forecasting Based on Machine Learning Methods.”**

## Planned capabilities

- import the UCI household electricity dataset and compatible user CSV files;
- validate, clean and aggregate time-series measurements to hourly energy consumption;
- analyse data quality and consumption patterns;
- train and compare Seasonal Naive, Ridge, Random Forest and Histogram Gradient Boosting models;
- produce a direct 24-hour forecast;
- expose a FastAPI REST API and a React/TypeScript user interface;
- store time-series data in PostgreSQL with TimescaleDB;
- run locally through Docker Compose.

## Technology baseline

- **Frontend:** React, TypeScript, Vite, TanStack Query, Apache ECharts
- **Backend:** Python, FastAPI, Pydantic, SQLAlchemy, Alembic
- **Data and ML:** Pandas, NumPy, scikit-learn, joblib
- **Database:** PostgreSQL, TimescaleDB
- **Infrastructure:** Docker, Docker Compose, Nginx, GitHub Actions

## Repository status

The repository currently contains the architecture and contract baseline from the design stage. Code, tests and deployment configuration are added incrementally. Design-time files must be updated when implementation decisions change.

## Technical documentation

- `docs/api/openapi-design.yaml` — design-time OpenAPI contract
- `docs/database/schema-design.sql` — database schema baseline
- `docs/diagrams/` — C4, UML, sequence, ER and deployment diagrams
- `docs/sad/SAD_draft_v0.1.md` — English Software Architecture Document draft
- `docs/architecture/traceability.csv` — requirements traceability matrix

## Private development materials

Prompts, Codex instructions, coursework planning documents and implementation checklists are intentionally stored outside this Git repository in the sibling local directory `../EnergyForecast-private/`.

## License

MIT License. See `LICENSE`.


## 🌐 Українська (UK)
# EnergyForecast

**EnergyForecast** — це повнофункціональна програмна система для імпорту, перевірки, аналізу та прогнозування погодинного споживання електроенергії за допомогою методів машинного навчання.

Цей репозиторій містить реалізацію курсового проєкту **«Програмна система аналізу та прогнозування енергоспоживання на основі методів машинного навчання»**.

## Заплановані можливості

- імпорт набору даних UCI Household Electricity Consumption та сумісних CSV-файлів користувачів;
- перевірка, очищення й агрегація часових рядів до погодинного споживання електроенергії;
- аналіз якості даних і закономірностей енергоспоживання;
- навчання та порівняння моделей Seasonal Naive, Ridge, Random Forest і Histogram Gradient Boosting;
- формування прямого прогнозу на 24 години;
- надання REST API на основі FastAPI та користувацького інтерфейсу на React і TypeScript;
- зберігання часових рядів у PostgreSQL із використанням TimescaleDB;
- локальний запуск системи через Docker Compose.

## Базовий набір технологій

- **Frontend:** React, TypeScript, Vite, TanStack Query, Apache ECharts
- **Backend:** Python, FastAPI, Pydantic, SQLAlchemy, Alembic
- **Дані та машинне навчання:** Pandas, NumPy, scikit-learn, joblib
- **База даних:** PostgreSQL, TimescaleDB
- **Інфраструктура:** Docker, Docker Compose, Nginx, GitHub Actions

## Стан репозиторію

Наразі репозиторій містить базову архітектуру та контракти, створені на етапі проєктування. Програмний код, тести та конфігурації розгортання додаються поступово.

Файли, створені на етапі проєктування, повинні оновлюватися у разі зміни рішень під час реалізації системи.

## Технічна документація

- `docs/api/openapi-design.yaml` — проєктний контракт OpenAPI;
- `docs/database/schema-design.sql` — базова схема бази даних;
- `docs/diagrams/` — діаграми C4, UML, послідовностей, ER-діаграми та діаграми розгортання;
- `docs/sad/SAD_draft_v0.1.md` — чернетка документа Software Architecture Document англійською мовою;
- `docs/architecture/traceability.csv` — матриця трасування вимог.

## Приватні матеріали розробки

Промпти, інструкції для Codex, документи з планування курсової роботи та контрольні списки реалізації навмисно зберігаються поза цим Git-репозиторієм у сусідній локальній директорії:

```text
../EnergyForecast-private/