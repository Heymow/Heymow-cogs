import { useState, useEffect } from 'react'
import api from '../../utils/api'
import './InsightsTab.css'

function InsightsTab({ period }) {
  const [health, setHealth] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    loadData()
  }, [period])

  const loadData = async () => {
    setLoading(true)
    setError(null)
    try {
      const result = await api.fetchCommunityHealth(period)
      setHealth(result)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  if (loading) return <div className="loading">Loading...</div>
  if (error) return <div className="error">Error: {error}</div>
  if (!health) return null

  const getHealthColor = (grade) => {
    if (grade.startsWith('A')) return '#4ade80'
    if (grade.startsWith('B')) return '#facc15'
    if (grade.startsWith('C')) return '#fb923c'
    if (grade.startsWith('D')) return '#f87171'
    return '#ef4444'
  }

  return (
    <div className="insights-tab">
      <div className="health-score-card">
        <h3>Community Health</h3>
        <div 
          className="health-score"
          style={{ color: getHealthColor(health.health_grade) }}
        >
          {health.health_score.toFixed(1)}/100
        </div>
        <div className="health-grade" style={{ color: getHealthColor(health.health_grade) }}>
          Grade: {health.health_grade}
        </div>
      </div>

      <div className="metrics-grid">
        <div className="metric-card">
          <div className="metric-icon">👥</div>
          <div className="metric-value">{health.total_streamers}</div>
          <div className="metric-label">Total Streamers</div>
        </div>

        <div className="metric-card">
          <div className="metric-icon">✅</div>
          <div className="metric-value">{health.active_last_7_days}</div>
          <div className="metric-label">Active (7 days)</div>
          <div className="metric-sub">{health.active_percentage}%</div>
        </div>

        <div className="metric-card">
          <div className="metric-icon">📺</div>
          <div className="metric-value">{health.total_streams}</div>
          <div className="metric-label">Total Streams</div>
        </div>

        <div className="metric-card">
          <div className="metric-icon">⏱️</div>
          <div className="metric-value">{health.total_hours}h</div>
          <div className="metric-label">Total Hours</div>
        </div>

        <div className="metric-card">
          <div className="metric-icon">📊</div>
          <div className="metric-value">{health.avg_streams_per_member}</div>
          <div className="metric-label">Avg Streams/Member</div>
        </div>

        <div className="metric-card">
          <div className="metric-icon">⏰</div>
          <div className="metric-value">{health.avg_hours_per_member}h</div>
          <div className="metric-label">Avg Hours/Member</div>
        </div>
      </div>

      <div className="growth-section">
        <h4>Growth Metrics</h4>
        <div className="growth-cards">
          <div className="growth-card">
            <div className="growth-label">Streamer Growth</div>
            <div className={`growth-value ${health.streamer_growth_pct >= 0 ? 'positive' : 'negative'}`}>
              {health.streamer_growth_pct >= 0 ? '+' : ''}{health.streamer_growth_pct}%
            </div>
          </div>
          <div className="growth-card">
            <div className="growth-label">Stream Volume Growth</div>
            <div className={`growth-value ${health.stream_growth_pct >= 0 ? 'positive' : 'negative'}`}>
              {health.stream_growth_pct >= 0 ? '+' : ''}{health.stream_growth_pct}%
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

export default InsightsTab
