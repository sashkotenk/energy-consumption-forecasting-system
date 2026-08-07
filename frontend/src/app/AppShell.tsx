import { NavLink, Outlet } from 'react-router'

const navigation = [
  ['/', 'Огляд'],
  ['/datasets', 'Набори даних'],
  ['/experiments', 'Експерименти'],
  ['/forecasts', 'Прогнози'],
] as const

export function AppShell() {
  return (
    <div className="application-shell">
      <a className="skip-link" href="#main-content">До основного вмісту</a>
      <aside className="sidebar" aria-label="Основна навігація">
        <NavLink className="brand" to="/" aria-label="EnergyForecast — головна">
          <span className="brand-mark" aria-hidden="true">EF</span>
          <span><strong>EnergyForecast</strong><small>аналіз енергоспоживання</small></span>
        </NavLink>
        <nav>
          {navigation.map(([to, label]) => (
            <NavLink key={to} to={to} end={to === '/'} className={({ isActive }) => isActive ? 'nav-link active' : 'nav-link'}>
              {label}
            </NavLink>
          ))}
        </nav>
        <p className="sidebar-note">Погодинний аналіз і прогноз на 24 години</p>
      </aside>
      <main id="main-content" className="content" tabIndex={-1}><Outlet /></main>
    </div>
  )
}
