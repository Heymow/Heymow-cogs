import { useState, useEffect } from 'react'
import api from '../../utils/api'
import './StreamersTab.css'

function StreamersTab({ period }) {
  const [data, setData] = useState([])
  const [badgeCounts, setBadgeCounts] = useState({})
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [sortBy, setSortBy] = useState('time')

  useEffect(() => {
    loadData()
  }, [period])

  const loadData = async () => {
    setLoading(true)
    setError(null)
    try {
      const members = await api.fetchAllMembers(period)
      setData(members)
      
      // Fetch badges for top 50
      if (members.length > 0) {
        const topIds = members.slice(0, 50).map(m => m.member_id)
        const badges = await api.fetchBadgesBatch(topIds)
        setBadgeCounts(badges)
      }
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  if (loading) return <div className="loading">Loading...</div>
  if (error) return <div className="error">Error: {error}</div>

  const sortedData = [...data].sort((a, b) => {
    if (sortBy === 'time') return b.total_time_seconds - a.total_time_seconds
    if (sortBy === 'count') return b.total_streams - a.total_streams
    return a.display_name.localeCompare(b.display_name)
  })

  const getRoleIcon = (role) => {
    const icons = {
      seed: '🌱', sprout: '🌿', flower: '🌸', rosegarden: '🌹',
      eden: '🌺', patrons: '💎', sponsor: '🏆', 
      garden_guardian: '🛡️', admin: '👑'
    }
    return icons[role] || ''
  }

  return (
    <div className="streamers-tab">
      <div className="sort-controls">
        <button 
          className={sortBy === 'time' ? 'active' : ''}
          onClick={() => setSortBy('time')}
        >
          Sort by Time
        </button>
        <button 
          className={sortBy === 'count' ? 'active' : ''}
          onClick={() => setSortBy('count')}
        >
          Sort by Count
        </button>
        <button 
          className={sortBy === 'name' ? 'active' : ''}
          onClick={() => setSortBy('name')}
        >
          Sort by Name
        </button>
      </div>

      <div className="streamers-list">
        {sortedData.map((streamer, index) => {
          const badges = badgeCounts[streamer.member_id]
          return (
            <div key={streamer.member_id} className="streamer-card">
              <div className="streamer-rank">#{index + 1}</div>
              <div className="streamer-info">
                <div className="streamer-name">
                  {getRoleIcon(streamer.role)} {streamer.display_name}
                  {streamer.role && (
                    <span className={`role-tag role-${streamer.role}`}>
                      {streamer.role}
                    </span>
                  )}
                </div>
                <div className="streamer-stats">
                  <span>{streamer.total_streams} streams</span>
                  <span>•</span>
                  <span>{streamer.total_time_hours}h</span>
                  {badges && (
                    <>
                      <span>•</span>
                      <span>🏆 {badges.earned}/{badges.total}</span>
                    </>
                  )}
                </div>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

export default StreamersTab
