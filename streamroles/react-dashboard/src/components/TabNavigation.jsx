import './TabNavigation.css'

function TabNavigation({ activeTab, onTabChange }) {
  const tabs = [
    { id: 'overview', label: '📊 Overview' },
    { id: 'heatmap', label: '🔥 Heatmap' },
    { id: 'streamers', label: '👥 All Streamers' },
    { id: 'badges', label: '🏆 Badges & Achievements' },
    { id: 'insights', label: '💡 Insights' },
  ]

  return (
    <div className="tab-navigation">
      {tabs.map(tab => (
        <button
          key={tab.id}
          className={`tab-button ${activeTab === tab.id ? 'active' : ''}`}
          onClick={() => onTabChange(tab.id)}
        >
          {tab.label}
        </button>
      ))}
    </div>
  )
}

export default TabNavigation
