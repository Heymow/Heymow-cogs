const API_BASE = '/dashboard/proxy'

export const api = {
  async fetchTop(period = '30d', metric = 'time', limit = 10) {
    const response = await fetch(`${API_BASE}/top`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ period, metric, limit })
    })
    if (!response.ok) throw new Error('Failed to fetch top streamers')
    return response.json()
  },

  async fetchHeatmap(period = '30d') {
    const response = await fetch(`${API_BASE}/heatmap`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ period })
    })
    if (!response.ok) throw new Error('Failed to fetch heatmap data')
    return response.json()
  },

  async fetchAllMembers(period = '30d') {
    const response = await fetch(`${API_BASE}/all_members`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ period })
    })
    if (!response.ok) throw new Error('Failed to fetch all members')
    return response.json()
  },

  async fetchBadgesBatch(memberIds) {
    const response = await fetch(`${API_BASE}/badges_batch`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ member_ids: memberIds })
    })
    if (!response.ok) throw new Error('Failed to fetch badges')
    return response.json()
  },

  async fetchAchievements() {
    const response = await fetch(`${API_BASE}/achievements`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({})
    })
    if (!response.ok) throw new Error('Failed to fetch achievements')
    return response.json()
  },

  async fetchCommunityHealth(period = '30d') {
    const response = await fetch(`${API_BASE}/community_health`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ period })
    })
    if (!response.ok) throw new Error('Failed to fetch community health')
    return response.json()
  },
}

export default api
