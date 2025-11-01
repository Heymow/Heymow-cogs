import './HelpModal.css'

function HelpModal({ onClose }) {
  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content" onClick={(e) => e.stopPropagation()}>
        <button className="modal-close" onClick={onClose}>×</button>
        <h2>📖 Dashboard Help</h2>
        
        <div className="help-section">
          <h3>🎯 Overview</h3>
          <p>View top streamers by time or stream count, with quick stats and interactive charts.</p>
        </div>

        <div className="help-section">
          <h3>🔥 Heatmap</h3>
          <p>Visualize community streaming activity by day and hour. Darker colors indicate more activity.</p>
        </div>

        <div className="help-section">
          <h3>👥 All Streamers</h3>
          <p>Complete list of all community streamers with badges, stats, and role information.</p>
        </div>

        <div className="help-section">
          <h3>🏆 Badges & Achievements</h3>
          <p>View your earned badges, progress toward locked badges, and guild-wide competitive achievements.</p>
        </div>

        <div className="help-section">
          <h3>💡 Insights</h3>
          <p>Community health metrics, growth trends, and analytics to help you understand streaming patterns.</p>
        </div>

        <div className="help-section">
          <h3>🎨 Role Colors</h3>
          <ul className="role-list">
            <li><span className="role-badge seed">Seed</span></li>
            <li><span className="role-badge sprout">Sprout</span></li>
            <li><span className="role-badge flower">Flower</span></li>
            <li><span className="role-badge rosegarden">Rosegarden</span></li>
            <li><span className="role-badge eden">Eden</span></li>
            <li><span className="role-badge patrons">Patrons</span></li>
            <li><span className="role-badge sponsor">Sponsor</span></li>
            <li><span className="role-badge garden_guardian">Garden Guardian</span></li>
            <li><span className="role-badge admin">Admin</span></li>
          </ul>
        </div>
      </div>
    </div>
  )
}

export default HelpModal
