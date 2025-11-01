import { useState, useEffect } from 'react'
import { Bar } from 'react-chartjs-2'
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  BarElement,
  Title,
  Tooltip,
  Legend
} from 'chart.js'
import api from '../../utils/api'
import './OverviewTab.css'

ChartJS.register(
  CategoryScale,
  LinearScale,
  BarElement,
  Title,
  Tooltip,
  Legend
)

function OverviewTab({ period }) {
  const [data, setData] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [metric, setMetric] = useState('time')

  useEffect(() => {
    loadData()
  }, [period, metric])

  const loadData = async () => {
    setLoading(true)
    setError(null)
    try {
      const result = await api.fetchTop(period, metric, 10)
      setData(result)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  if (loading) return <div className="loading">Loading...</div>
  if (error) return <div className="error">Error: {error}</div>

  const chartData = {
    labels: data.map(d => d.display_name),
    datasets: [{
      label: metric === 'time' ? 'Hours Streamed' : 'Stream Count',
      data: data.map(d => metric === 'time' ? d.value_hours : d.value),
      backgroundColor: 'rgba(61, 107, 77, 0.8)',
      borderColor: 'rgba(61, 107, 77, 1)',
      borderWidth: 1,
    }]
  }

  const chartOptions = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: {
        display: false
      },
      tooltip: {
        backgroundColor: 'rgba(10, 21, 12, 0.9)',
        titleColor: '#e8f4ea',
        bodyColor: '#a8c4ac',
        borderColor: '#3d6b4d',
        borderWidth: 1,
        padding: 12,
        displayColors: false,
      }
    },
    scales: {
      y: {
        beginAtZero: true,
        ticks: { color: '#a8c4ac' },
        grid: { color: 'rgba(255, 255, 255, 0.1)' }
      },
      x: {
        ticks: { color: '#a8c4ac' },
        grid: { display: false }
      }
    }
  }

  return (
    <div className="overview-tab">
      <div className="metric-selector">
        <button 
          className={metric === 'time' ? 'active' : ''}
          onClick={() => setMetric('time')}
        >
          By Time
        </button>
        <button 
          className={metric === 'count' ? 'active' : ''}
          onClick={() => setMetric('count')}
        >
          By Count
        </button>
      </div>

      <div className="stats-grid">
        {data.slice(0, 3).map((streamer, index) => (
          <div key={streamer.member_id} className="stat-card">
            <div className="rank">#{index + 1}</div>
            <div className="name">{streamer.display_name}</div>
            <div className="value">
              {metric === 'time' 
                ? `${streamer.value_hours.toFixed(1)}h`
                : `${streamer.value} streams`
              }
            </div>
          </div>
        ))}
      </div>

      <div className="chart-container">
        <h3>Top 10 Streamers</h3>
        <div className="chart-wrapper">
          <Bar data={chartData} options={chartOptions} />
        </div>
      </div>
    </div>
  )
}

export default OverviewTab
