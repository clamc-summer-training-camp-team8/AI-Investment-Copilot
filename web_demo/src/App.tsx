import { Route, Routes } from 'react-router-dom'
import { AppShell } from './components'
import {
  AnalysisReviewPage,
  DemoEntryPage,
  MaterialUploadPage,
  NotFoundPage,
  StatusDecisionPage,
  ThesisOverviewPage,
  TimelinePage,
} from './pages'

export default function App() {
  return (
    <AppShell>
      <Routes>
        <Route path="/" element={<DemoEntryPage />} />
        <Route path="/theses/:thesisId" element={<ThesisOverviewPage />} />
        <Route path="/theses/:thesisId/upload" element={<MaterialUploadPage />} />
        <Route path="/evidence/:evidenceId/analysis" element={<AnalysisReviewPage />} />
        <Route path="/theses/:thesisId/decision" element={<StatusDecisionPage />} />
        <Route path="/theses/:thesisId/timeline" element={<TimelinePage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Routes>
    </AppShell>
  )
}
