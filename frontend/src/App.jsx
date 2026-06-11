import { NavLink, Navigate, Route, Routes } from 'react-router-dom'
import NewTaskPage from './pages/NewTaskPage'
import RecipeDetailPage from './pages/RecipeDetailPage'
import RecipesPage from './pages/RecipesPage'
import RunDetailPage from './pages/RunDetailPage'
import RunDiffPage from './pages/RunDiffPage'
import RunsPage from './pages/RunsPage'
import SettingsPage from './pages/SettingsPage'
import SuiteDetailPage from './pages/SuiteDetailPage'
import SuitesPage from './pages/SuitesPage'

export default function App() {
  return (
    <div className="app">
      <nav className="sidebar">
        <h1>🦖 Automation Studio</h1>
        <NavLink to="/new">+ New Task</NavLink>
        <NavLink to="/runs">Runs</NavLink>
        <NavLink to="/recipes">Recipes</NavLink>
        <NavLink to="/suites">Test Suites</NavLink>
        <NavLink to="/settings">Settings</NavLink>
        <div className="sidebar-footer">powered by Botasaurus + OpenRouter</div>
      </nav>
      <main className="content">
        <Routes>
          <Route path="/" element={<Navigate to="/new" replace />} />
          <Route path="/new" element={<NewTaskPage />} />
          <Route path="/runs" element={<RunsPage />} />
          <Route path="/runs/:id" element={<RunDetailPage />} />
          <Route path="/runs/:a/diff/:b" element={<RunDiffPage />} />
          <Route path="/recipes" element={<RecipesPage />} />
          <Route path="/recipes/:id" element={<RecipeDetailPage />} />
          <Route path="/suites" element={<SuitesPage />} />
          <Route path="/suites/:id" element={<SuiteDetailPage />} />
          <Route path="/settings" element={<SettingsPage />} />
        </Routes>
      </main>
    </div>
  )
}
