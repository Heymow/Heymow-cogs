import { useState, useEffect } from 'react'
import api from '../../utils/api'
import './HeatmapTab.css'

function HeatmapTab({ period }) {
  const [data, setData] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    loadData()
  }, [period])

  const loadData = async () => {
    setLoading(true)
    setError(null)
    try {
      const result = await api.fetchHeatmap(period)
      setData(result)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  if (loading) return <div className="loading">Loading...</div>
  if (error) return <div className="error">Error: {error}</div>

  const days = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
  const hours = Array.from({ length: 24 }, (_, i) => i)
  
  const maxCount = Math.max(...data.map(d => d.count), 1)
  
  const getColor = (count) => {
    if (count === 0) return 'rgba(61, 107, 77, 0.1)'
    const intensity = count / maxCount
    return `rgba(61, 107, 77, ${0.2 + intensity * 0.8})`
  }

  return (
    <div className="heatmap-tab">
      <h3>🔥 Weekly Streaming Activity</h3>
      <div className="heatmap-container">
        <div className="heatmap-grid">
          <div className="hour-labels">
            {hours.map(hour => (
              <div key={hour} className="hour-label">
                {hour}h
              </div>
            ))}
          </div>
          <div className="heatmap-content">
            <div className="day-labels">
              {days.map(day => (
                <div key={day} className="day-label">{day}</div>
              ))}
            </div>
            <div className="heatmap-cells">
              {days.map((day, dayIndex) => (
                <div key={dayIndex} className="day-column">
                  {hours.map(hour => {
                    const cell = data.find(d => d.day === dayIndex && d.hour === hour)
                    const count = cell ? cell.count : 0
                    return (
                      <div
                        key={`${dayIndex}-${hour}`}
                        className="heatmap-cell"
                        style={{ backgroundColor: getColor(count) }}
                        title={`${day} ${hour}:00 - ${count} streams`}
                      />
                    )
                  })}
                </div>
              ))}
            </div>
          </div>
        </div>
        <div className="heatmap-legend">
          <span>Less</span>
          <div className="legend-gradient" />
          <span>More</span>
        </div>
      </div>
    </div>
  )
}

export default HeatmapTab
