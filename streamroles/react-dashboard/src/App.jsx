import { useState, useEffect } from 'react'
import './App.css'
import Header from './components/Header'
import TabNavigation from './components/TabNavigation'
import OverviewTab from './components/tabs/OverviewTab'
import HeatmapTab from './components/tabs/HeatmapTab'
import StreamersTab from './components/tabs/StreamersTab'
import BadgesTab from './components/tabs/BadgesTab'
import InsightsTab from './components/tabs/InsightsTab'
import HelpModal from './components/HelpModal'

function App() {
  const [activeTab, setActiveTab] = useState('overview')
  const [showHelp, setShowHelp] = useState(false)
  const [period, setPeriod] = useState('30d')

  return (
    <div className="app">
      <Header onHelpClick={() => setShowHelp(true)} />
      
      <div className="container">
        <TabNavigation 
          activeTab={activeTab} 
          onTabChange={setActiveTab}
        />

        <div className="controls">
          <label>
            Period:
            <select value={period} onChange={(e) => setPeriod(e.target.value)}>
              <option value="7d">Last 7 Days</option>
              <option value="30d">Last 30 Days</option>
              <option value="all">All Time</option>
            </select>
          </label>
        </div>

        <div className="tab-content">
          {activeTab === 'overview' && <OverviewTab period={period} />}
          {activeTab === 'heatmap' && <HeatmapTab period={period} />}
          {activeTab === 'streamers' && <StreamersTab period={period} />}
          {activeTab === 'badges' && <BadgesTab />}
          {activeTab === 'insights' && <InsightsTab period={period} />}
        </div>
      </div>

      {showHelp && <HelpModal onClose={() => setShowHelp(false)} />}
    </div>
  )
}

export default App
