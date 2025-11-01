import { useState, useEffect } from 'react'
import api from '../../utils/api'
import './BadgesTab.css'

function BadgesTab() {
  const [achievements, setAchievements] = useState({})
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    loadData()
  }, [])

  const loadData = async () => {
    setLoading(true)
    setError(null)
    try {
      const result = await api.fetchAchievements()
      setAchievements(result)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  if (loading) return <div className="loading">Loading...</div>
  if (error) return <div className="error">Error: {error}</div>

  return (
    <div className="badges-tab">
      <h3>🏆 Guild Achievements</h3>
      <p className="description">
        Competitive achievements awarded to top performers in the community
      </p>

      <div className="achievements-grid">
        {Object.entries(achievements).map(([id, achievement]) => (
          <div 
            key={id} 
            className={`achievement-card ${achievement.has_holder ? 'earned' : 'locked'}`}
          >
            <div className="achievement-emoji">{achievement.emoji}</div>
            <div className="achievement-info">
              <div className="achievement-name">{achievement.name}</div>
              <div className="achievement-description">{achievement.description}</div>
              {achievement.has_holder ? (
                <div className="achievement-holder">
                  👑 {achievement.holder_name}
                  <span className="achievement-value">
                    {achievement.value.toFixed(1)}
                  </span>
                </div>
              ) : (
                <div className="achievement-no-holder">
                  No holder yet (min: {achievement.minimum_value})
                </div>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

export default BadgesTab
